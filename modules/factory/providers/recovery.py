"""Operator guidance only; never authorization to retry or release money."""

MESSAGES = {
    "reauth_required": "Reconnect the configured Google account using Application Default Credentials, then use Providers → Re-check readiness.",
    "no_credentials": "Configure Google Application Default Credentials for the approved account, then re-check readiness.",
    "expired": "Refresh the configured Google credentials, then re-check readiness.",
    "credential_transport_failed": "Check the network connection to Google authentication, then re-check readiness.",
    "credential_dependency_missing": "Install the project's Google authentication dependencies in the service environment, restart the service, then re-check readiness.",
    "credential_refresh_failed": "Google credential refresh failed. Check the configured account and authentication service, then re-check readiness.",
    "loader_failed": "The older generic credential error does not prove whether a request was sent. Check provider readiness and review the attempt evidence.",
}


def credential_recovery(reason):
    message = MESSAGES.get(reason)
    if message:
        return message + " Reconcile any unknown attempt before Resume; reconnecting does not release a budget hold."
    return None


def analysis_recovery(reason):
    if reason == 'analysis_throttle_exhausted':
        return ('Google rejected this analysis request as temporarily busy (HTTP 429), including two bounded retries. '
                'Generated clips are preserved. Check provider capacity/quota before authorizing a fresh review; '
                'Resume will not reset the retry limit or regenerate footage.')
    if reason in ('malformed_analysis', 'invalid_analysis_timing'):
        return ('The analysis response failed format or timing checks. This request is potentially billable. '
                'Review the saved response and validation event; an operator must reconcile the completed '
                'unusable attempt and settle its estimate before Resume. Do not release it as uncharged '
                'or repeatedly retry. Scene and passage timing must remain valid.')
    return None
