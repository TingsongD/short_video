"""Small LLM client interface shared by grill/script/publish modules.
All providers are OpenAI-compatible chat-completions endpoints.
`transport` is injectable: tests pass a fake, production uses urllib.
"""
import json
import urllib.request

PROVIDER_URLS = {
    "kimi": "https://api.moonshot.cn/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "openai": "https://api.openai.com/v1",
}


class LLMClient:
    def __init__(self, provider="kimi", api_key="", model="", base_url="", transport=None):
        self.provider = provider
        self.api_key = api_key
        self.model = model
        self.base_url = (base_url or PROVIDER_URLS.get(provider, "")).rstrip("/")
        self.transport = transport or self._live_transport

    @classmethod
    def from_secrets(cls, secrets, transport=None):
        return cls(
            provider=secrets.get("LLM_PROVIDER", "kimi"),
            api_key=secrets.get("LLM_API_KEY", ""),
            model=secrets.get("LLM_MODEL", ""),
            base_url=secrets.get("LLM_BASE_URL", ""),
            transport=transport,
        )

    def complete(self, system, user, temperature=0.0):
        if not self.api_key or not self.model:
            raise RuntimeError("LLM_API_KEY / LLM_MODEL not configured")
        return self.transport(
            f"{self.base_url}/chat/completions",
            {
                "model": self.model,
                "temperature": temperature,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )

    def _live_transport(self, url, payload):
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            body = json.loads(r.read())
        return body["choices"][0]["message"]["content"]


def parse_json(text):
    """Extract a JSON object/array from an LLM response (tolerates fences)."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1].rsplit("```", 1)[0]
    start_obj, start_arr = t.find("{"), t.find("[")
    if start_arr != -1 and (start_obj == -1 or start_arr < start_obj):
        return json.loads(t[start_arr:t.rfind("]") + 1])
    return json.loads(t[start_obj:t.rfind("}") + 1])


class FakeLLM:
    """Deterministic test double: responder is a str or callable(system,user)->str."""

    def __init__(self, responder):
        self.responder = responder
        self.calls = []

    def complete(self, system, user, temperature=0.0):
        self.calls.append({"system": system, "user": user, "temperature": temperature})
        return self.responder(system, user) if callable(self.responder) else self.responder
