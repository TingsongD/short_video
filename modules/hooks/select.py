"""M4 hook selection: pick a curated hook by (niche, hook_type from the M3
format entry). Returns the hook dict with attribution intact. Raises
LookupError when the bank has nothing for that niche/type."""
import json
from pathlib import Path


def load_bank(path):
    return json.loads(Path(path).read_text())["hooks"]


def select(hooks, niche, hook_type=None):
    """Deterministic: newest added_at wins; id breaks ties.
    Falls back to any hook in the niche when no type match exists."""
    pool = [h for h in hooks if h["niche"] == niche]
    if not pool:
        raise LookupError(f"no hooks in bank for niche {niche!r}")
    typed = [h for h in pool if hook_type and h["hook_type"] == hook_type]
    chosen_pool = typed or pool
    return max(chosen_pool, key=lambda h: (h["added_at"], h["id"]))


def attribution(hook):
    return {"source_url": hook["source_url"], "hook_id": hook["id"]}
