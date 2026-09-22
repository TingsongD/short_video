"""Exact source frames and clock-bound, audio-bearing interpretation windows."""
from bisect import bisect_left, bisect_right
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import tempfile

from ..domain.errors import ContractError
from ..media.source_clock import extract_audio


def _ranges(clock,fusion):
    times=[Fraction(f['source_time']) for f in clock['frames']]
    intervals=[]
    for candidate in fusion['candidates']:
        low=max(0,bisect_right(times,Fraction(candidate['context_start']))-1)
        high=min(len(times),bisect_left(times,Fraction(candidate['context_end'])))
        intervals.append((low,max(low+1,high),candidate['id']))
    merged=[]
    for low,high,ident in sorted(intervals):
        if merged and low<=merged[-1]['end_frame']:
            merged[-1]['end_frame']=max(high,merged[-1]['end_frame'])
            merged[-1]['candidate_ids'].append(ident)
        else:
            merged.append({'first_frame':low,'end_frame':high,'candidate_ids':[ident]})
    # Dense cuts can merge context across an entire source. Bound encoded
    # windows before payload quotation, with one second of overlap so every
    # half-second lead/trail candidate still has a complete context window.
    bounded=[]
    for item in merged:
        low=item['first_frame'];end=item['end_frame']
        while low<end:
            high=min(end,max(low+1,bisect_right(times,times[low]+4)-1))
            if Fraction(clock['duration'])-times[low]<=4:high=end
            bounded.append({'first_frame':low,'end_frame':high,'candidate_ids':item['candidate_ids']})
            if high==end:break
            low=max(low+1,bisect_left(times,times[high]-1))
    for item in bounded:
        item['source_start']=str(times[item['first_frame']])
        item['source_end']=str(times[item['end_frame']] if item['end_frame']<len(times) else Fraction(clock['duration']))
        item['candidate_ids']=[c['id'] for c in fusion['candidates']
            if Fraction(c['context_start'])<Fraction(item['source_end'])
            and Fraction(c['context_end'])>Fraction(item['source_start'])]
    if any(not any(Fraction(w['source_start'])<=Fraction(c['context_start'])
            and Fraction(w['source_end'])>=Fraction(c['context_end']) for w in bounded) for c in fusion['candidates']):
        raise ContractError('window_context_unavailable','selected_media','The source clock cannot preserve full candidate context within bounded windows.')
    return bounded


def _window(source,target,clock,interval,pcm=None,audio=None):
    import av
    import numpy as np
    low,high=Fraction(interval['source_start']),Fraction(interval['source_end'])
    base=Fraction(clock['video']['decoded_time_base'])
    with av.open(str(source)) as input_media, av.open(str(target),'w') as output:
        original=input_media.streams[clock['video']['index']]
        video=output.add_stream('libx264',rate=original.average_rate or Fraction(30))
        video.width,video.height=original.codec_context.width,original.codec_context.height
        video.pix_fmt='yuv420p'
        video.time_base=base
        video.codec_context.time_base=base
        video.options={'crf':'18','preset':'fast'}
        sound=None
        audio_cursor,audio_end,offset=0,0,0
        if pcm is not None:
            origin=Fraction(audio['source_origin'])
            audio_cursor=max(0,int((low-origin)*48000))
            audio_end=min(len(pcm),int((high-origin)*48000))
            offset=round((origin-low)*48000)
            if audio_cursor<audio_end:
                layout=input_media.streams[clock['audio']['index']].codec_context.layout.name
                layout={1:'mono',2:'stereo'}.get(audio['channels'],layout)
                sound=output.add_stream('aac',rate=48000)
                sound.layout=layout
                sound.bit_rate=192000
                sound.time_base=Fraction(1,48000)
        def emit_audio(until):
            nonlocal audio_cursor
            while sound is not None and audio_cursor<min(until,audio_end):
                end=min(audio_cursor+1024,audio_end,until)
                values=np.ascontiguousarray(pcm[audio_cursor:end].T,dtype=np.float32)
                frame=av.AudioFrame.from_ndarray(values,format='fltp',layout=sound.layout.name)
                frame.sample_rate=48000
                frame.time_base=Fraction(1,48000)
                frame.pts=offset+audio_cursor
                for packet in sound.encode(frame):
                    output.mux(packet)
                audio_cursor=end
        count=0
        for index,frame in enumerate(input_media.decode(original)):
            if index<interval['first_frame']:
                continue
            if index>=interval['end_frame']:
                break
            expected=clock['frames'][index]
            if frame.pts!=expected['pts'] or str(frame.time_base)!=expected['time_base'] or getattr(frame,'is_corrupt',False):
                raise ContractError('source_evidence_stale','window_frame')
            target_time=Fraction(expected['source_time'])-low
            frame.pts=round(target_time/base)
            frame.time_base=base
            for packet in video.encode(frame):
                output.mux(packet)
            emit_audio(max(audio_cursor,round(target_time*48000)-offset))
            count+=1
        emit_audio(audio_end)
        for packet in video.encode(None):
            output.mux(packet)
        if sound is not None:
            for packet in sound.encode(None):
                output.mux(packet)
        if count!=interval['end_frame']-interval['first_frame']:
            raise ContractError('coverage_incomplete','window_frames')
    with av.open(str(target)) as check:
        audio_present=bool(check.streams.audio)
        decoded=0
        for frame in check.decode(video=0):
            if decoded>=count or frame.pts is None:
                raise ContractError('window_clock_mismatch','selected_media')
            expected=Fraction(clock['frames'][interval['first_frame']+decoded]['source_time'])-low
            if abs(Fraction(frame.pts)*frame.time_base-expected)>base:
                raise ContractError('window_clock_mismatch','selected_media')
            decoded+=1
        if decoded!=count:
            raise ContractError('window_clock_mismatch','selected_media')
    return audio_present


def materialize_selected(source,clock,fusion,artifacts,workspace,*,progress=None):
    import av
    import numpy as np
    progress=progress or (lambda **_:None)
    indices=fusion['selected_frame_indices']
    ranges=_ranges(clock,fusion)
    if len(indices)>1024 or len(ranges)>64:
        raise ContractError('evidence_media_limit','selected_media',
                            'Mandatory context exceeds the bounded media plan; no frames were silently discarded.')
    source=Path(source)
    with source.open('rb') as stream:
        if hashlib.file_digest(stream,'sha256').hexdigest()!=clock['source_sha256']:
            raise ContractError('source_evidence_stale','source_bytes')
    workspace=Path(workspace)
    workspace.mkdir(parents=True,exist_ok=True,mode=0o700)
    images,windows=[],[]
    with tempfile.TemporaryDirectory(prefix='selected-',dir=workspace) as temporary:
        temp=Path(temporary)
        selected=set(indices)
        with av.open(str(source)) as container:
            for index,frame in enumerate(container.decode(container.streams[clock['video']['index']])):
                if index not in selected:
                    continue
                image=frame.to_image().convert('RGB')
                expected=clock['frames'][index]
                if hashlib.sha256(image.tobytes()).hexdigest()!=expected['pixel_sha256']:
                    raise ContractError('source_evidence_stale','selected_frame')
                path=temp/f'frame-{index}.png'
                image.save(path)
                detail={'source_sha256':clock['source_sha256'],'frame_index':index,'source_time':expected['source_time'],
                        'pixel_sha256':expected['pixel_sha256'],'version':'selected_media.v1'}
                artifact=artifacts.intake_file(path,'seed_source',f"flashcut:{clock['source_sha256']}:{index}",json.dumps(detail))
                images.append({**detail,'artifact_id':artifact.id,'sha256':artifact.sha256,'bytes':artifact.byte_count})
                progress(stage='selected_media')
        if len(images)!=len(selected):
            raise ContractError('coverage_incomplete','selected_frames')
        pcm,audio=None,None
        if clock['audio'] is not None:
            audio=extract_audio(source,clock,temp/'audio.f32')
            pcm=np.memmap(temp/'audio.f32',mode='r',dtype='<f4',shape=(audio['samples'],audio['channels']))
        for number,interval in enumerate(ranges):
            target=temp/f'window-{number}.mp4'
            audio_present=_window(source,target,clock,interval,pcm,audio)
            detail={**interval,'audio_present':audio_present,'source_sha256':clock['source_sha256'],
                    'version':'selected_media.v1','mapping':'source_time=window_time+source_start'}
            artifact=artifacts.intake_file(target,'seed_source',f"flashcut-window:{clock['source_sha256']}:{number}",json.dumps(detail))
            windows.append({**detail,'artifact_id':artifact.id,'sha256':artifact.sha256,'bytes':artifact.byte_count})
            progress(stage='selected_media')
        if pcm is not None:
            del pcm
    return {'version':'selected_media.v1','source_sha256':clock['source_sha256'],'images':images,'windows':windows}
