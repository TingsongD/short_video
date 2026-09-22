"""Run-owned source evidence, never an edit to a shared reference transcript."""
import copy
import json
import math
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

from ..domain.errors import ContractError
from ..domain.records import content_hash

POLICY = 'source_timing.v1'


def tokens(text):
    return re.sub(r'[^\w\s]', '', str(text)).casefold().split()


def bounds(value):
    return (value.get('start_s', value.get('start_seconds', value.get('start'))),
            value.get('end_s', value.get('end_seconds', value.get('end'))))


def valid_bounds(s, e, start, end):
    return all(type(x) in (int, float) and math.isfinite(x) for x in (s,e)) and start <= s < e <= end


def words_ok(words, passage):
    s, e = bounds(passage)
    if not isinstance(words, list) or not words or any(not isinstance(w, dict) for w in words): return False
    if tokens(' '.join(str(w.get('text', w.get('word', ''))) for w in words)) != tokens(passage['text']): return False
    previous = s
    for word in words:
        start, end = bounds(word)
        if not valid_bounds(start, end, previous, e) or end - start > 2: return False
        previous = end
    return True


class SourceTimingService:
    def __init__(self, db, repair, progress=None):
        self.db, self.repair, self.progress = db, repair, progress

    def receipt(self, run_id, binding):
        row = self.db.conn.execute('SELECT value FROM meta WHERE key=?',
            (f'source-timing:{run_id}:{binding}',)).fetchone()
        return json.loads(row[0]) if row else None

    def _save(self, run_id, receipt):
        with self.db.uow() as u:
            u.conn.execute('INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)',
                (f'source-timing:{run_id}:{receipt["binding"]}', json.dumps(receipt)))
            if self.progress: self.progress(copy.deepcopy(receipt))

    def review(self, run_id, source_sha, transcript, beats, duration, language):
        binding = content_hash({'source':source_sha, 'transcript':transcript, 'policy':POLICY, 'language':language})
        receipt = self.receipt(run_id, binding) or {'policy':POLICY, 'binding':binding,
            'source_sha256':source_sha, 'transcript_hash':content_hash(transcript), 'passages':[]}
        result = copy.deepcopy(transcript)
        previous = 0
        for i, passage in enumerate(result):
            while len(receipt['passages']) <= i:
                receipt['passages'].append({'attempts':0, 'quality':'unchecked'})
            entry = receipt['passages'][i]
            s, e = bounds(passage)
            if not valid_bounds(s,e,previous,duration) or not tokens(passage.get('text','')):
                entry['quality'] = 'unreliable'; self._save(run_id, receipt)
                raise ContractError('source_timing_unreliable', f'passage:{i}',
                    f'Passage {i+1} has invalid bounds or text. Restore reliable source timing, then Resume; no scene approval is required.')
            previous = e
            if words_ok(passage.get('words'), passage):
                entry['quality'] = 'word_aligned'
                continue
            if words_ok(entry.get('words'), passage):
                passage['words'] = entry['words']; entry['quality'] = 'repaired'
                continue
            while entry['attempts'] < 2:
                entry['attempts'] += 1; entry['quality'] = 'repairing'
                # Intent precedes the local request. An interrupted attempt is
                # consumed, never reset or confused with a paid provider retry.
                self._save(run_id, receipt)
                try:
                    words = self.repair(passage, entry['attempts'], duration, language)
                except Exception as error:
                    entry['last_error'] = type(error).__name__; words = []
                if words_ok(words, passage):
                    entry.update(quality='repaired', words=words)
                    passage['words'] = words
                    break
            if entry['quality'] != 'repaired':
                owners = [b for b in beats if b['start_s'] <= s and e <= b['end_s']]
                entry['quality'] = 'passage_only' if len(owners) == 1 else 'unreliable'
                passage['words'] = []
                if len(owners) != 1:
                    self._save(run_id, receipt)
                    raise ContractError('source_timing_unreliable', f'passage:{i}',
                        f'Passage {i+1} ({s:g}–{e:g}s): two local repairs exhausted and scene ownership is uncertain. Import reliable timing for this passage, then Resume.')
            self._save(run_id, receipt)
        receipt['transcript'] = result
        self._save(run_id, receipt)
        return copy.deepcopy(receipt)


class LocalTimingRepair:
    """Only loopback WhisperX: this adapter cannot route to a paid provider."""
    def __init__(self, source, base_url='http://127.0.0.1:8765'):
        parsed = urlparse(base_url)
        if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1','localhost','::1') or parsed.username or parsed.query or parsed.fragment:
            raise ContractError('local_alignment_required', 'endpoint')
        self.source, self.url = str(source), base_url.rstrip('/')

    def __call__(self, passage, attempt, duration, language):
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                raise ContractError('local_alignment_redirect_refused', 'endpoint')
        opener = build_opener(ProxyHandler({}), NoRedirect())
        with opener.open(self.url + '/health', timeout=5) as response:
            health = json.load(response)
        if health.get('protocol') != 'hypit.whisperx-service@1' or health.get('ok') is not True:
            raise ContractError('local_alignment_unavailable', 'endpoint')
        start, end = bounds(passage)
        offset, finish = max(0, start-attempt), min(duration, end+attempt)
        with tempfile.TemporaryDirectory(prefix='factory-source-timing-') as folder:
            audio = Path(folder)/'passage.wav'
            subprocess.run(['ffmpeg','-nostdin','-v','error','-ss',str(offset),'-i',self.source,
                '-t',str(finish-offset),'-vn','-ac','1','-ar','16000','-c:a','pcm_s16le',str(audio)],
                capture_output=True, check=True, timeout=120)
            request = Request(self.url+'/transcribe', data=json.dumps({'audio_path':str(audio), 'language':language}).encode(),
                headers={'Content-Type':'application/json'}, method='POST')
            with opener.open(request, timeout=600) as response:
                data = json.load(response)
            words = []
            for segment in data.get('segments', []):
                for w in segment.get('words', []):
                    s,e = bounds(w)
                    if valid_bounds(s,e,0,finish-offset) and start <= s+offset < e+offset <= end:
                        words.append({'text':w.get('word',w.get('text','')), 'start_s':s+offset, 'end_s':e+offset})
            return words
