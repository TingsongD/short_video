"""Decode and measure final video; absent measurements are blocking findings."""
import json
import re
import subprocess
from fractions import Fraction


class TechnicalQC:
    def __init__(self, runner=None):
        self.runner = runner or (lambda argv, timeout=60: subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout))

    def _ff(self, argv, timeout=60):
        return self.runner(argv, timeout=timeout)

    def probe(self, path):
        r = self._ff(['ffprobe','-v','error','-print_format','json','-show_streams','-show_format',str(path)])
        if r.returncode:
            raise ValueError('probe_failed')
        return json.loads(r.stdout)

    def inspect(self, path, expected):
        findings = []
        def add(code, at='video', detail=''):
            findings.append({'code':code,'at':at,'detail':detail})
        try:
            info = self.probe(path)
            vids = [s for s in info['streams'] if s.get('codec_type')=='video']
            auds = [s for s in info['streams'] if s.get('codec_type')=='audio']
            if not vids:
                raise ValueError('no_video')
            v = vids[0]; fps = float(Fraction(v['avg_frame_rate']))
            nb = int(v['nb_frames']); duration = float(v['duration'])
            if (v['width'],v['height']) != (expected['width'],expected['height']):
                add('wrong_dimensions')
            if abs(fps-float(expected['fps'])) > .0001:
                add('wrong_fps',detail=str(fps))
            if expected.get('frames') and nb != expected['frames']:
                add('wrong_frame_count',detail=f"{nb} != {expected['frames']}")
            wanted = expected.get('duration_s',expected.get('frames',nb)/expected['fps'])
            if abs(duration-wanted) > 1/expected['fps'] + .0001:
                add('wrong_duration',detail=f'{duration} != {wanted}')
            if expected.get('has_audio'):
                if not auds:
                    add('no_audio','container')
                else:
                    a = auds[0]; start = float(a.get('start_time',0)); end = start+float(a['duration'])
                    if start > .03 or end < wanted-.03:
                        add('insufficient_audio_coverage','audio',f'{start}-{end}')
            dec = self._ff(['ffmpeg','-v','error','-i',str(path),'-f','null','-'],timeout=120)
            if dec.returncode or dec.stderr.strip():
                add('decode_error','stream')
            findings += self._black_freeze(path, duration, expected.get('intentional_stills',[]))
            if auds and expected.get('has_audio'):
                findings += self._audio_levels(path)
            for narration in expected.get('narration',[]):
                ni=self.probe(narration['path']); n=next(s for s in ni['streams'] if s['codec_type']=='audio')
                required=(narration['end_frame']-narration['start_frame'])/expected['fps']
                if abs(float(n['duration'])-required) > .02:
                    add('narration_duration_mismatch','audio')
                import hashlib
                from pathlib import Path
                if hashlib.sha256(Path(narration['path']).read_bytes()).hexdigest()!=narration['sha256']:
                    add('narration_hash_mismatch','audio')
            if expected.get('narration_required') and not expected.get('narration'):
                add('missing_narration_evidence','audio')
        except (ValueError, KeyError, TypeError, ZeroDivisionError, StopIteration, OSError, subprocess.SubprocessError) as e:
            add('probe_or_detector_failed','container',type(e).__name__)
            return {'ok':False,'findings':findings}
        return {'ok':not findings,'findings':findings,'frames':nb,
                'fps':fps,'duration_s':duration,'streams':{'video':bool(vids),'audio':bool(auds)}}

    def _black_freeze(self, path, duration=None, intentional_stills=()):
        r = self._ff(['ffmpeg','-v','info','-i',str(path),'-vf',
                      'blackdetect=d=0.5:pix_th=0.10,freezedetect=n=0.001:d=0.5',
                      '-an','-f','null','-'],timeout=120)
        if r.returncode:
            return [{'code':'detector_failed','at':'video','detail':'black/freeze'}]
        out=[]; log=r.stderr or ''
        for m in re.finditer(r'black_start:\s*([\d.]+)\s+black_end:\s*([\d.]+)',log):
            out.append({'code':'black_section','at':f'{m[1]}-{m[2]}s','detail':'black frames'})
        start=None
        for m in re.finditer(r'freeze_(start|end):\s*([\d.]+)',log):
            if m[1]=='start':
                start=float(m[2])
            elif start is not None:
                out.extend(self._freeze(start,float(m[2]),intentional_stills)); start=None
        if start is not None:
            out.extend(self._freeze(start,duration,intentional_stills))
        return out

    @staticmethod
    def _freeze(start,end,allowed):
        if end is not None and any(r.get('approved') and r['start_s'] <= start+.04 and r['end_s'] >= end-.04 for r in allowed):
            return []
        return [{'code':'frozen_section','at':f'{start}-{end if end is not None else "EOF"}s','detail':'frozen frames'}]

    def _audio_levels(self,path):
        r=self._ff(['ffmpeg','-v','info','-i',str(path),'-af','volumedetect','-vn','-f','null','-'],timeout=120)
        pattern=r'([-\d.]+|-?inf)'
        mean=re.search(r'mean_volume:\s*'+pattern+r' dB',r.stderr or '')
        peak=re.search(r'max_volume:\s*'+pattern+r' dB',r.stderr or '')
        if r.returncode or not mean or not peak:
            return [{'code':'detector_failed','at':'audio','detail':'levels unavailable'}]
        out=[]
        if float(mean[1]) < -60:
            out.append({'code':'silent_audio','at':'audio','detail':mean[1]})
        if float(peak[1]) >= -.05:
            out.append({'code':'clipping','at':'audio','detail':peak[1]})
        return out
