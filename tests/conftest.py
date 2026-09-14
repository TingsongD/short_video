"""Shared pytest setup: make the repo root importable so tests can do
`import modules.<x>` regardless of pytest's sys.path handling."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"
