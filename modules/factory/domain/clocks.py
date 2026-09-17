"""Rational frame clock (handover §5.3).

Frame rates are num/den rationals. Frame intervals are half-open:
[start, end) — start included, end excluded. Source seconds map to target
frames exactly once: round the picture duration to the output clock once,
never per-beat accumulation.
"""
from dataclasses import dataclass
from fractions import Fraction

from .errors import ContractError


@dataclass(frozen=True)
class RationalRate:
    num: int
    den: int = 1

    def __post_init__(self):
        if self.den <= 0 or self.num <= 0:
            raise ContractError("invalid_frame_rate", "clock",
                                f"{self.num}/{self.den}")

    @property
    def fps(self) -> Fraction:
        return Fraction(self.num, self.den)

    def seconds_to_frames(self, seconds) -> int:
        return int(Fraction(str(seconds)) * self.fps + Fraction(1, 2))

    def frames_to_seconds(self, frames: int) -> Fraction:
        return Fraction(frames) / self.fps


FPS_30 = RationalRate(30, 1)
FPS_24 = RationalRate(24, 1)


@dataclass(frozen=True)
class FrameInterval:
    """Half-open [start, end) in target output frames."""
    start: int
    end: int

    def __post_init__(self):
        if self.start < 0 or self.end <= self.start:
            raise ContractError("invalid_frame_interval", "interval",
                                f"[{self.start},{self.end})")

    @property
    def length(self) -> int:
        return self.end - self.start

    def overlaps(self, other: "FrameInterval") -> bool:
        return self.start < other.end and other.start < self.end

    def adjacent(self, other: "FrameInterval") -> bool:
        return self.end == other.start or other.end == self.start

    def contains(self, other: "FrameInterval") -> bool:
        return self.start <= other.start and other.end <= self.end

    def to_dict(self):
        return {"start_frame": self.start, "end_frame": self.end}

    @staticmethod
    def from_dict(d):
        return FrameInterval(d["start_frame"], d["end_frame"])


def check_partition(intervals, total_frames):
    """Intervals must tile [0,total) without gaps or overlaps."""
    errs = []
    ordered = sorted(intervals, key=lambda i: i.start)
    cursor = 0
    for i, iv in enumerate(ordered):
        if iv.start > cursor:
            errs.append(ContractError("frame_gap", f"intervals[{i}]",
                                      f"gap {cursor}..{iv.start}"))
        if iv.start < cursor:
            errs.append(ContractError("frame_overlap", f"intervals[{i}]",
                                      f"overlap before {iv.start}"))
        cursor = max(cursor, iv.end)
    if cursor != total_frames:
        errs.append(ContractError("frame_coverage", "intervals",
                                  f"covered {cursor} of {total_frames}"))
    return errs
