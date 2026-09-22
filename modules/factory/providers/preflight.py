"""Positive local evidence, not inference from a provider error's name."""
from ..testing.fakes import ProviderError


class RequestNotSent(ProviderError):
    """Only raised before entering a new billable request's transport."""
    receipt = None


def submission_bearer(auth):
    # Do not use for observation, or after any earlier billable request.
    try:
        return auth.bearer()
    except ProviderError as error:
        raise RequestNotSent(error.code) from None
