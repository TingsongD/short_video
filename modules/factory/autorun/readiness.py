"""Non-billable checks before creating new paid scope, never a retry policy."""
from ..domain.errors import ContractError
from ..providers.recovery import credential_recovery


def runtime_ready(services):
    if services.config.get('mode') != 'live':
        return
    health = services.health()['worker']
    if not health['available']:
        raise ContractError('worker_unavailable', 'worker', 'Start the worker and wait for its heartbeat, then try again.')
    if health['paused'] or health['draining']:
        raise ContractError('queue_paused', 'worker', 'Resume the queue before starting this run.')
    capacity = services.scheduler.status_snapshot()['capacities'].get('dispatch') or {}
    if capacity.get('used', 0) >= capacity.get('limit', 1):
        raise ContractError('queue_capacity_full', 'worker', 'Wait for active work or reconcile unknown operations; do not blindly retry.')


def provider_ready(services, provider, *, run_id=None):
    if services.config.get('mode') != 'live':
        return None
    adapter = services.providers.get(provider)
    acceptance_run=getattr(adapter,'acceptance_run_id',None)
    if acceptance_run and acceptance_run!=run_id:
        return ('pause','flashcut_acceptance_scope_mismatch',provider+': qualification is limited to another run.',
                'Do not inherit another run’s qualification or spending approval.')
    check = getattr(adapter, 'refresh_readiness', None) or getattr(adapter, 'readiness', None)
    if not callable(check):
        return ('pause', 'provider_not_ready', provider + ': readiness_unavailable', 'Configure and re-check this provider before Resume.')
    try:
        ready = check()
    except Exception:
        ready = {'reason': 'readiness_check_failed'}
    if ready.get('authenticated') is not True:
        if provider=='jev_decisions' and ready.get('can_attempt_authorized') is True and (
                ready.get('live_qualified') is True or acceptance_run==run_id and run_id is not None):
            return None
        # Only expose allow-listed reasons. Provider messages can contain secrets.
        reason = ready.get('reason')
        message = credential_recovery(reason)
        reason = reason if message else 'provider_not_authenticated'
        return ('pause', 'provider_not_ready', provider + ': ' + reason,
                message or 'Reconnect this provider and re-check readiness before Resume.')
    return None
