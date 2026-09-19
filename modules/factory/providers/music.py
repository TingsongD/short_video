"""ElevenLabs Music generation; its own qualified route and pricing snapshot.

Instrumental underscore beds for experiments. The account and credential
scope are shared with the TTS connection but this route carries its own
dated pricing evidence and qualification — TTS qualification never implies
music qualification.
"""
import json
from .synchronous import SynchronousAdapter
from ..execution.context import current_effect
from ..execution.policy import ExecutionPolicy
from ..integrations.http import BoundedHTTP
from ..testing.fakes import ProviderError


class MusicAdapter(SynchronousAdapter):
    name = "generated_music"

    def __init__(self, state_dir, credentials=None, transport=None, policy=None,
                 account=None, pricing=None, model="music_v1"):
        super().__init__(state_dir)
        self.account, self.pricing, self.model = account, pricing, model
        self.credentials = credentials or (lambda: {})
        self.live = transport is None
        self.policy = policy or ExecutionPolicy()
        self.transport = transport or BoundedHTTP("generated_music", self.policy, 64 * 1024 * 1024)

    def readiness(self):
        return {'ready': bool(self.account and self.pricing), 'installed': True,
                'authenticated': bool(self.credentials().get("ELEVENLABS_API_KEY")),
                'catalog_visible': True, 'contract_tested': True,
                'live_qualified': getattr(self, 'qualified', False),
                'reason': f'Credential verification occurs at the transport boundary; model {self.model}'}

    def price(self, request):
        from ..domain.errors import ContractError
        if not self.pricing or request.get('model') != self.model \
                or not isinstance(request.get('prompt'), str):
            raise ContractError('pricing_unavailable', 'generated_music')
        rate = self.pricing.get('credits_per_second')
        if type(rate) not in (int, float) or rate <= 0:
            raise ContractError('pricing_unavailable', 'credits_per_second')
        ms = request.get('music_length_ms')
        if type(ms) is not int or not 3000 <= ms <= 600000:
            raise ContractError('invalid_music_length', 'music_length_ms')
        amount = max(1, int(round(ms / 1000 * rate)))
        return {'kind': 'usage_estimate', 'unit': 'elevenlabs_credits',
                'amount': amount, 'reserve_amount': amount,
                'valid_until': self.pricing.get('valid_until', ''),
                'rate_basis': self.pricing.get('evidence', '')}

    def execute(self, request):
        prompt = request.get('prompt')
        ms = request.get('music_length_ms')
        if request.get('model') != self.model or not isinstance(prompt, str) \
                or not prompt.strip() or len(prompt) > 4000:
            raise ProviderError('music_route_unqualified')
        if type(ms) is not int or not 3000 <= ms <= 600000:
            raise ProviderError('invalid_music_length')
        if self.live:
            binding = current_effect.get()
            if not binding or binding['provider'] != self.name:
                raise ProviderError('authority_required')
        # Credentials are only resolved while dispatch is executing.
        key = self.credentials().get('ELEVENLABS_API_KEY', '')
        headers = {'xi-api-key': key, 'Content-Type': 'application/json'}
        payload = {'prompt': prompt, 'music_length_ms': ms, 'model_id': self.model,
                   'force_instrumental': bool(request.get('instrumental', True))}
        url = 'https://api.elevenlabs.io/v1/music?output_format=mp3_44100_128'
        status, response_headers, raw = self.transport('POST', url, json.dumps(payload).encode(), headers)
        if status != 200:
            raise ProviderError('music_http_error', http_status=status)
        if not raw or len(raw) < 1024:
            raise ProviderError('malformed_music_response')
        # Only the charged header is charge evidence — x-credits-remaining
        # is the account balance and must never settle an operation's spend.
        actual = response_headers.get('x-credits-charged')
        return {}, raw, {'request_id': response_headers.get('request-id'),
                         'actual_credits': int(actual) if actual and str(actual).lstrip('-').isdigit() else None,
                         'content_type': 'audio/mpeg'}
