"""Typed contract errors. `code` is stable; `field` locates the problem."""


class ContractError(ValueError):
    def __init__(self, code, field=None, detail=""):
        self.code, self.field, self.detail = code, field, detail
        where = f"{field}: " if field else ""
        super().__init__(f"{code}: {where}{detail}")


def require(errors, ok, code, field=None, detail=""):
    if not ok:
        errors.append(ContractError(code, field, detail))
    return ok
