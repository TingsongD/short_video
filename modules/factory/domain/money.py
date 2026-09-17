"""Typed money (handover §7.2, §10).

Amounts are integers in explicit units: provider credits are typed per
provider; dollars are integer microdollars. No binary floating point, no
negative amounts, no cross-unit mixing.
"""
from dataclasses import dataclass

from .errors import ContractError

UNITS = frozenset({
    "jimeng_credits",
    "elevenlabs_credits",
    "viral_outliers_credits",
    "usd_micros",          # integer microdollars; $1 = 1_000_000
})


@dataclass(frozen=True)
class Money:
    unit: str
    amount: int            # >= 0; None represented by absence, not zero

    def __post_init__(self):
        if self.unit not in UNITS:
            raise ContractError("unknown_unit", "unit", self.unit)
        if type(self.amount) is not int:
            raise ContractError("money_not_integer", "amount",
                                repr(self.amount))
        if self.amount < 0:
            raise ContractError("money_negative", "amount",
                                str(self.amount))

    def __add__(self, other):
        if self.unit != other.unit:
            raise ContractError("unit_mismatch", "unit",
                                f"{self.unit} + {other.unit}")
        return Money(self.unit, self.amount + other.amount)

    def __sub__(self, other):
        if self.unit != other.unit:
            raise ContractError("unit_mismatch", "unit",
                                f"{self.unit} - {other.unit}")
        return Money(self.unit, self.amount - other.amount)

    def to_dict(self):
        return {"unit": self.unit, "amount": self.amount}

    @staticmethod
    def from_dict(d):
        return Money(d["unit"], d["amount"])
