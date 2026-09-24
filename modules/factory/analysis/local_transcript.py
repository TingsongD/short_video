"""Detect source speech locally when the pinned Hypit CLI needs a language.

The local WhisperX service accepts automatic detection; the pinned CLI only
accepts en/zh/es. Use the same service protocol and transcript file format,
without a second decode or a paid-provider fallback.
"""
import json
import subprocess
import tempfile
import wave
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from ..domain.errors import ContractError


def transcribe_auto(source, destination, base_url, language='auto'):
    parsed = urlparse(base_url)
    if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ('', '/')):
        raise ContractError('local_transcription_required', 'endpoint')
    destination = Path(destination)
    if destination.exists():
        raise ContractError('transcript_exists', 'destination')

    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise ContractError('local_transcription_redirect_refused', 'endpoint')

    opener = build_opener(ProxyHandler({}), NoRedirect())
    url = base_url.rstrip('/')

    def request_json(request, timeout):
        with opener.open(request, timeout=timeout) as response:
            body = response.read(4 * 1024 * 1024 + 1)
        if len(body) > 4 * 1024 * 1024:
            raise ContractError('local_transcription_invalid', 'response_size')
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ContractError('local_transcription_invalid', 'response')
        return data

    health = request_json(url + '/health', 5)
    if health.get('protocol') != 'hypit.whisperx-service@1' or health.get('ok') is not True:
        raise ContractError('local_transcription_unavailable', 'endpoint')
    with tempfile.TemporaryDirectory(prefix='factory-source-speech-') as folder:
        audio = Path(folder) / 'speech.wav'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(source),
            '-map', '0:a:0', '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(audio)],
            capture_output=True, check=True, timeout=120)
        with wave.open(str(audio), 'rb') as wav:
            seconds = wav.getnframes() / wav.getframerate()
        response = request_json(Request(url + '/transcribe', data=json.dumps({
            'audio_path': str(audio), 'language': language}).encode(),
            headers={'Content-Type': 'application/json'}, method='POST'), 1800)

    segments = response.get('segments')
    if not isinstance(segments, list):
        raise ContractError('local_transcription_invalid', 'segments')
    passages = []
    for segment in segments:
        if not isinstance(segment, dict) or not isinstance(segment.get('words', []), list):
            raise ContractError('local_transcription_invalid', 'segment')
        words = []
        for word in segment.get('words', []):
            if not isinstance(word, dict):
                raise ContractError('local_transcription_invalid', 'word')
            words.append({'text': word.get('text', word.get('word', '')),
                **{k: word[k] for k in ('speaker', 'speaker_status') if k in word},
                **{target: word[key] for key, target in (
                    ('start', 'start_seconds'), ('end', 'end_seconds'), ('score', 'score'))
                   if key in word}})
        # Missing acoustic timing stays missing; downstream validation and
        # bounded timing repair decide whether the evidence is usable.
        passages.append({'text': segment.get('text', ''), 'words': words,
            **({'speaker': segment['speaker']} if 'speaker' in segment else {}),
            **{target: segment[key] for key, target in (
                ('start', 'start_seconds'), ('end', 'end_seconds')) if key in segment}})
    document = {'format': 'hypit.transcript@1', 'source': str(source),
        'language': response.get('language'), 'audio_seconds': seconds, 'passages': passages}
    if 'diarization' in response:
        document['diarization'] = response['diarization']
    if 'stt_segments' in response:
        document['stt_segments'] = response['stt_segments']
    serialized = json.dumps(document, ensure_ascii=False, allow_nan=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('x') as output:
        output.write(serialized)
    return document
