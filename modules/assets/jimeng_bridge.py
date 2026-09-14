"""M6 Lane A (BEST-EFFORT, never blocks): drive jimeng.jianying.com through a
Kimi WebBridge-style HTTP bridge pointed at the user's logged-in browser.

Protocol: POST {bridge_url}/run  {"selector": key-or-css, "action": ..., "value": ...}
Selectors come from jimeng_selectors.json so UI drift is a config fix, not a
code change. If JIMENG_BRIDGE_URL isn't set or the bridge errors, we raise
BridgeUnavailable — callers must fall back to Lane B / Pexels.
"""
import json
import os
import time
import urllib.request
from pathlib import Path

SELECTORS_PATH = Path(__file__).parent / "jimeng_selectors.json"


class BridgeUnavailable(Exception):
    pass


def load_selectors(path=None):
    data = json.loads(Path(path or SELECTORS_PATH).read_text())
    required = {"site_url", "selectors"}
    missing = required - set(data)
    if missing:
        raise ValueError(f"selector file missing keys: {missing}")
    for key in ("login_check", "prompt_textarea", "submit_button",
                "result_item", "download_button"):
        if key not in data["selectors"]:
            raise ValueError(f"selectors missing: {key}")
    return data


class JimengBridge:
    def __init__(self, bridge_url=None, selectors_path=None, post=None):
        self.bridge_url = bridge_url or os.environ.get("JIMENG_BRIDGE_URL", "")
        self.cfg = load_selectors(selectors_path)
        self.post = post or self._http_post

    def _http_post(self, payload):
        if not self.bridge_url:
            raise BridgeUnavailable("JIMENG_BRIDGE_URL not configured")
        req = urllib.request.Request(
            f"{self.bridge_url}/run", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except OSError as e:
            raise BridgeUnavailable(str(e)) from e

    def _sel(self, key):
        return self.cfg["selectors"][key]

    def check_login(self):
        r = self.post({"action": "exists", "selector": self._sel("login_check")})
        return bool(r.get("ok") and r.get("found"))

    def submit_prompt(self, prompt, out_dir, shot_idx):
        """Best-effort: type prompt -> submit -> poll -> download."""
        if not self.bridge_url:
            raise BridgeUnavailable("JIMENG_BRIDGE_URL not configured")
        if not self.check_login():
            raise BridgeUnavailable("no logged-in Jimeng session detected")
        self.post({"action": "goto", "url": self.cfg["site_url"]})
        self.post({"action": "fill", "selector": self._sel("prompt_textarea"), "value": prompt})
        self.post({"action": "click", "selector": self._sel("aspect_9_16_option")})
        self.post({"action": "click", "selector": self._sel("submit_button")})
        deadline = time.time() + self.cfg["timeouts"]["render_max_s"]
        while time.time() < deadline:
            r = self.post({"action": "exists", "selector": self._sel("result_item")})
            if r.get("ok") and r.get("found"):
                break
            time.sleep(self.cfg["timeouts"]["render_poll_s"])
        else:
            raise BridgeUnavailable("render timed out")
        r = self.post({
            "action": "download",
            "selector": self._sel("download_button"),
            "save_as": str(Path(out_dir) / f"shot-{shot_idx:02d}.jimeng.mp4"),
        })
        if not r.get("ok"):
            raise BridgeUnavailable(r.get("error", "download failed"))
        return Path(out_dir) / f"shot-{shot_idx:02d}.jimeng.mp4"
