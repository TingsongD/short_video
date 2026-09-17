"""Deterministic clock. Tests advance time explicitly; nothing sleeps."""
import datetime as _dt


class FakeClock:
    """Fixed-at-construction UTC clock advanced only by explicit calls."""

    def __init__(self, start="2026-09-16T00:00:00Z"):
        self._t = _dt.datetime.strptime(start, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=_dt.timezone.utc)

    def now(self) -> _dt.datetime:
        return self._t

    def iso(self) -> str:
        return self._t.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    def advance(self, seconds=0.0, minutes=0.0, hours=0.0, days=0.0):
        self._t += _dt.timedelta(seconds=seconds, minutes=minutes,
                                 hours=hours, days=days)
        return self._t

    def monotonic(self) -> float:
        return self._t.timestamp()


def utcnow_iso():
    return _dt.datetime.now(_dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
