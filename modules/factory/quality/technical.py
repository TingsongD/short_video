"""Decode and measure final video; absent measurements are blocking findings."""
import json
import math
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
        temporal_coverage = None
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
            if expected.get('temporal') is not None:
                temporal_findings, temporal_coverage = self._temporal(
                    path, expected, nb)
                findings += temporal_findings
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
        report = {'ok':not findings,'findings':findings,'frames':nb,
                  'fps':fps,'duration_s':duration,
                  'streams':{'video':bool(vids),'audio':bool(auds)}}
        if temporal_coverage is not None:
            report['temporal_coverage'] = temporal_coverage
        return report

    def _temporal(self, path, expected, frame_count):
        """Inspect every output timestamp plus bound caption/event schedules.

        The schedule proves where the final edit says an event occurs. Decoded
        hashes prove frames occupy that interval and differ at its boundary.
        They do not prove semantic identity or lip synchronization.
        """
        policy = expected['temporal']
        coverage = {
            'video_pts': {'frames': 0,
                          'method': 'ffprobe_all_decoded_frame_timestamps'},
            'captions': {'count': 0,
                         'method': 'schedule_vs_final_speech_alignment',
                         'pixel_ocr': False},
            'brief_events': {
                'inspected': [],
                'method': 'decoded_frame_boundary_presence',
                'semantic_identity': False,
            },
            'lip_sync': 'not_verified',
        }
        findings = []
        def add(code, at='timeline', detail=''):
            findings.append({'code': code, 'at': at, 'detail': detail})
        if (not isinstance(policy, dict)
                or policy.get('version') != 'flashcut_temporal_qc.v1'
                or policy.get('caption_alignment')
                != 'final_speech_schedule.v1'):
            add('temporal_evidence_invalid', detail='unsupported policy')
            return findings, coverage

        # Full decoded presentation-timestamp coverage. The final profile is
        # CFR, so a missing, repeated, reversed or oversized step is a defect.
        pts = self._ff([
            'ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-show_frames', '-show_entries',
            'frame=best_effort_timestamp_time', '-of', 'json', str(path),
        ], timeout=120)
        try:
            if pts.returncode:
                raise ValueError('ffprobe')
            rows = json.loads(pts.stdout)['frames']
            times = [Fraction(row['best_effort_timestamp_time'])
                     for row in rows]
            if any(not math.isfinite(float(value)) for value in times):
                raise ValueError('non-finite')
        except (KeyError, TypeError, ValueError, ZeroDivisionError,
                json.JSONDecodeError):
            add('temporal_detector_failed', 'video_pts',
                'decoded timestamps unavailable')
            times = []
        coverage['video_pts']['frames'] = len(times)
        if times:
            if len(times) != frame_count:
                add('video_pts_coverage_incomplete', 'video_pts',
                    f'{len(times)}/{frame_count}')
            rate = (Fraction(expected['fps_num'], expected['fps_den'])
                    if expected.get('fps_num') and expected.get('fps_den')
                    else Fraction(str(expected['fps'])))
            step = 1 / rate
            tolerance = step / 4
            if abs(times[0]) > tolerance:
                add('video_pts_start_offset', 'frame:0', str(times[0]))
            for index, (prior, current) in enumerate(
                    zip(times, times[1:]), start=1):
                delta = current - prior
                if delta <= 0 or abs(delta - step) > tolerance:
                    add('video_pts_discontinuity', f'frame:{index}',
                        f'{delta} vs {step}')

        caption_findings, caption_count = self._caption_alignment(
            policy, frame_count)
        findings += caption_findings
        coverage['captions']['count'] = caption_count

        events = policy.get('brief_events', [])
        maximum = policy.get('brief_event_max_frames', 6)
        valid_events = (isinstance(events, list)
                        and type(maximum) is int and 1 <= maximum <= 30)
        if not valid_events:
            add('temporal_evidence_invalid', 'brief_events')
            events = []
        for event in events:
            try:
                start, end = event['start_frame'], event['end_frame']
                if (not isinstance(event.get('id'), str) or not event['id']
                        or event.get('required') is not True
                        or type(start) is not int or type(end) is not int
                        or not 0 <= start < end <= frame_count
                        or end - start > maximum):
                    raise ValueError()
            except (KeyError, TypeError, ValueError):
                add('temporal_evidence_invalid', 'brief_event')
                continue
            coverage['brief_events']['inspected'].append(event['id'])

        if coverage['brief_events']['inspected']:
            hashes = self._frame_hashes(path)
            if hashes is None:
                add('temporal_detector_failed', 'brief_events',
                    'decoded frame hashes unavailable')
            elif len(hashes) != frame_count:
                add('frame_hash_coverage_incomplete', 'brief_events',
                    f'{len(hashes)}/{frame_count}')
            else:
                by_id = {event.get('id'): event for event in events
                         if isinstance(event, dict)}
                for ident in coverage['brief_events']['inspected']:
                    event = by_id[ident]
                    start, end = event['start_frame'], event['end_frame']
                    boundaries = set()
                    if start:
                        boundaries.add(hashes[start - 1])
                    if end < frame_count:
                        boundaries.add(hashes[end])
                    interval = hashes[start:end]
                    visible = (any(value not in boundaries
                                   for value in interval)
                               if boundaries else len(set(interval)) > 1)
                    if not visible:
                        add('brief_event_not_visible', f'event:{ident}',
                            f'frames {start}-{end}')
        return findings, coverage

    @staticmethod
    def _caption_alignment(policy, frame_count):
        findings = []
        def fail(detail):
            findings.append({'code': 'caption_alignment_drift',
                             'at': 'captions', 'detail': detail})
        captions = policy.get('captions')
        passages = policy.get('passages')
        if not isinstance(captions, list) or not isinstance(passages, list):
            fail('caption or final-speech schedule unavailable')
            return findings, len(captions) if isinstance(captions, list) else 0
        expected = []
        try:
            prior_passage = 0
            for passage in passages:
                low, high = passage['in_frame'], passage['out_frame']
                words, phrases = passage['words'], passage['phrases']
                if (type(low) is not int or type(high) is not int
                        or not prior_passage <= low < high <= frame_count
                        or not isinstance(words, list) or not words
                        or not isinstance(phrases, list)):
                    raise ValueError()
                prior_passage = high
                last = low
                for word in words:
                    if (not isinstance(word.get('text'), str)
                            or not word['text'].strip()
                            or type(word.get('start_frame')) is not int
                            or type(word.get('end_frame')) is not int
                            or not last <= word['start_frame']
                            < word['end_frame'] <= high):
                        raise ValueError()
                    last = word['end_frame']
                if (' '.join(word['text'] for word in words).split()
                        != passage['text'].split()):
                    raise ValueError()
                refs = []
                for phrase in phrases:
                    if (not isinstance(phrase, list) or not phrase
                            or any(type(index) is not int
                                   or not 0 <= index < len(words)
                                   for index in phrase)):
                        raise ValueError()
                    refs.extend(phrase)
                    expected.append((
                        ' '.join(words[index]['text'] for index in phrase).split(),
                        words[phrase[0]]['start_frame'],
                        words[phrase[-1]]['end_frame'],
                    ))
                if refs != list(range(len(words))):
                    raise ValueError()
            actual = [
                (caption['text'].split(), caption['start_frame'],
                 caption['end_frame'])
                for caption in sorted(captions,
                                      key=lambda item: item['start_frame'])
            ]
            if actual != expected:
                fail('caption phrases do not match final replacement speech')
        except (KeyError, TypeError, ValueError):
            fail('invalid final-speech alignment schedule')
        return findings, len(captions)

    def _frame_hashes(self, path):
        result = self._ff([
            'ffmpeg', '-v', 'error', '-i', str(path), '-map', '0:v:0',
            '-f', 'framemd5', '-'
        ], timeout=120)
        if result.returncode:
            return None
        hashes = []
        for line in (result.stdout or '').splitlines():
            if not line or line.startswith('#'):
                continue
            parts = line.split(',')
            if len(parts) < 6 or not parts[-1].strip():
                return None
            hashes.append(parts[-1].strip())
        return hashes or None

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
