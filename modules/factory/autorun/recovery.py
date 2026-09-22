"""One recovery interface for inspection, accounting and run adoption.

Inspection is read-only. Mutation requires operator evidence and commits as one
transaction. No method submits provider work or manufactures an approval.
"""
import json

from ..domain.errors import ContractError
from ..execution import Executor
from ..providers.recovery import credential_recovery
from ..store.uow import utcnow

INVALID_RESPONSE = {'malformed_analysis', 'invalid_analysis_timing'}
UNFINISHED = {'prepared', 'dispatching', 'accepted', 'running', 'unknown', 'cancel_requested'}


class AnalysisRecovery:
    def __init__(self, services):
        self.s = services
        self.executor = Executor(services.db)

    def context(self, run):
        jobs = run.state.get('analysis_jobs') or []
        if not jobs and not run.params.get('workflow'):
            return None
        rows = []
        for job_id in jobs:
            rows.extend(self.s.db.conn.execute(
                'SELECT id,status,created_at,attempt_seq FROM attempts WHERE job_id=? ORDER BY attempt_seq',
                (job_id,)).fetchall())
        if run.params.get('workflow'):
            historical = self.s.db.conn.execute("""SELECT a.id,a.status,a.created_at,a.attempt_seq FROM attempts a
                JOIN intents i ON json_extract(i.body,'$.attempt_id')=a.id
                WHERE json_extract(i.body,'$.request.autorun_id')=? AND json_extract(i.body,'$.request.task')='analyze'""", (run.id,)).fetchall()
            rows = list({row['id']: row for row in [*rows, *historical]}.values())
        if not rows:
            return None
        unfinished = [row for row in rows if row['status'] in UNFINISHED]
        if len(unfinished) > 1:
            return {'ambiguous': [row['id'] for row in unfinished]}
        selected = unfinished[0] if unfinished else max(rows, key=lambda r: (r['created_at'], r['attempt_seq']))
        attempt = self.executor._attempt(selected['id'])
        intent = self.executor._intent_body(attempt['id'])
        from ..execution.effects import wire_hash
        if run.params.get('workflow') and (intent.get('request', {}).get('task') != 'analyze'
                or intent.get('job_id') != attempt['job_id']
                or wire_hash(intent.get('request')) != attempt['request_hash']
                or not isinstance(intent.get('extra', {}).get('operation_key'), str)):
            return {'ambiguous': [attempt['id']]}
        event = self.s.db.conn.execute("SELECT seq,body FROM events WHERE stream=? AND type='ack_lost' ORDER BY seq DESC LIMIT 1",
            ('attempt:' + attempt['id'],)).fetchone()
        diagnostic = json.loads(event['body']) if event else {}
        not_sent = self.s.db.conn.execute("SELECT body FROM events WHERE stream=? AND type='request_not_sent' ORDER BY seq DESC LIMIT 1",
            ('attempt:' + attempt['id'],)).fetchone()
        reservation = self.s.db.conn.execute('SELECT status FROM reservations WHERE id=?', (attempt.get('reservation_id'),)).fetchone()
        costs = {}
        for row in self.s.db.conn.execute('''SELECT b.unit,l.amount FROM reservation_lines l
                JOIN budgets b ON b.id=l.budget_id WHERE l.reservation_id=?''', (attempt.get('reservation_id'),)):
            costs[row['unit']] = max(costs.get(row['unit'], 0), row['amount'])
        return {'attempt': attempt, 'event_seq': event['seq'] if event else None,
                'cause': diagnostic.get('cause'), 'costs': costs,
                'not_sent_reason': json.loads(not_sent['body']).get('reason') if not_sent else None,
                'reservation_status': reservation['status'] if reservation else None}

    def describe(self, run):
        if run.status != 'paused' or run.stage not in ('video_analysis', 'sections', 'blueprint'):
            return None
        ctx = self.context(run)
        if not ctx or run.pause.get('code') == 'blueprint_flags':
            return None
        if ctx.get('ambiguous'):
            return {'kind': 'outcome_unknown', 'title': 'Multiple unresolved analysis attempts',
                    'message': 'Reconcile each listed operation before resuming; no old request will be replayed.',
                    'attempt_ids': ctx['ambiguous'], 'actions': [], 'can_resume': False}
        a = ctx['attempt']
        out = {'attempt_id': a['id'], 'event_seq': ctx['event_seq'],
               'estimate': ctx['costs'], 'estimate_kind': 'previous_request_estimate',
               'actions': [], 'can_resume': False}
        invalid = ctx['cause'] in INVALID_RESPONSE
        if a['status'] in UNFINISHED:
            out.update(kind='outcome_unknown', title='Provider outcome needs reconciliation',
                message='Do not retry or release this hold until the provider outcome is known.')
            if invalid:
                out.update(kind='response_invalid', title='Analysis returned, but failed validation',
                    message='This completed request is potentially billable. Recover its saved response locally first; recovery sends no new provider request.')
                adapter = self.s.providers.get('audiovisual_analysis')
                available = getattr(adapter, 'saved_response_available', None)
                request = self.executor._intent_body(a['id']).get('request') or {}
                if callable(available) and available(request, a['id']):
                    out['actions'].append('recover_saved')
                out['actions'].append('settle_unusable')
        elif a['status'] == 'failed' and ctx['reservation_status'] in ('released', 'settled'):
            out.update(kind='retry_ready', title='Previous attempt reconciled',
                message='A retry is a new provider request. Its fresh quote must fit the existing approved budgets.',
                actions=['retry_analysis'] if invalid else ['resume'], can_resume=not invalid)
            guidance = credential_recovery(ctx['not_sent_reason'])
            if guidance and ctx['reservation_status'] == 'released':
                out.update(kind='request_not_sent', title='Google sign-in failed before the request was sent',
                    message='The unsent attempt is closed and its hold was released. ' + guidance)
        else:
            return None
        return out

    def guard_resume(self, run, body):
        if run.stage not in ('video_analysis', 'sections', 'blueprint'):
            return
        for job_id in run.state.get('analysis_jobs') or []:
            for row in self.s.db.conn.execute('SELECT id,status FROM attempts WHERE job_id=?', (job_id,)):
                if row['status'] in UNFINISHED:
                    raise ContractError('analysis_reconciliation_required', 'attempt_id', row['id'])
        ctx = self.context(run)
        if not ctx:
            return
        if ctx.get('ambiguous'):
            raise ContractError('analysis_reconciliation_required', 'attempt_ids', ', '.join(ctx['ambiguous']))
        if ctx['attempt']['status'] in UNFINISHED:
            raise ContractError('analysis_reconciliation_required', 'attempt_id', ctx['attempt']['id'])
        if ctx['cause'] in INVALID_RESPONSE and ctx['attempt']['status'] == 'failed':
            if ctx['reservation_status'] != 'settled':
                raise ContractError('analysis_reconciliation_required', 'reservation_id')
            if body.get('approve_paid_analysis_retry') is not True or not str(body.get('reviewer') or '').strip():
                raise ContractError('paid_analysis_retry_approval_required', 'reviewer/approve_paid_analysis_retry')
            if (body.get('analysis_attempt_id') != ctx['attempt']['id']
                    or type(body.get('analysis_event_seq')) is not int
                    or body['analysis_event_seq'] != ctx['event_seq']):
                raise ContractError('analysis_retry_mismatch', 'analysis_attempt_id/analysis_event_seq',
                                    'The analysis attempt changed; reload and review the current failure.')
            return {'reviewer':str(body['reviewer']).strip(), 'attempt_id':ctx['attempt']['id'],
                    'validation_event_seq':ctx['event_seq']}

    @staticmethod
    def require_review(body):
        if (not str(body.get('reviewer') or '').strip() or not str(body.get('evidence') or '').strip()
                or type(body.get('event_seq')) is not int):
            raise ContractError('evidence_required', 'reviewer/evidence/event_seq')

    def settle_unusable(self, attempt_id, body):
        self.require_review(body)
        with self.s.db.uow():
            attempt = self.executor._attempt(attempt_id)
            rid = attempt.get('reservation_id')
            # A fresh HTTP idempotency key after a restart still cannot settle
            # twice or rewrite the original resolution evidence.
            prior = self.s.db.conn.execute("SELECT 1 FROM events WHERE stream=? AND type='human_resolution' AND json_extract(body,'$.outcome')='completed_unusable' AND json_extract(body,'$.event_seq')=?",
                ('attempt:' + attempt_id, body['event_seq'])).fetchone()
            if not (attempt['status'] == 'failed' and prior):
                evidence = (f"Operator-reviewed completed but unusable analysis; event {body['event_seq']}. "
                            f"{body['evidence']} Conservative usage estimate, not an invoice or no-charge finding.")
                self.s.settle_reservation(rid, {'reviewer': body['reviewer'], 'kind': 'usage_estimate', 'evidence': evidence})
                self.executor.resolve_unknown(attempt_id, evidence, 'completed_unusable', event_seq=body['event_seq'])
        return {'attempt_id': attempt_id, 'status': 'failed', 'reservation_id': rid,
                'settlement': 'usage_estimate', 'retry_started': False}

    def recover(self, run_id, body):
        self.require_review(body)
        auto = self.s.autorun
        with self.s.db.uow() as u:
            run = auto.get(run_id)
            previous = run.state.get('analysis_recovery') or {}
            if previous.get('event_seq') == body['event_seq'] and run.state.get('analysis'):
                return run.to_dict()
            jobs = run.state.get('analysis_jobs') or []
            ctx = self.context(run)
            if (run.stage != 'video_analysis' or run.status not in ('paused', 'running')
                    or not ctx or ctx.get('ambiguous') or
                    (u.jobs.get(ctx['attempt']['job_id']) or {}).get('status') != 'failed'):
                raise ContractError('analysis_recovery_unavailable', 'run_id')
            attempt_id = ctx['attempt']['id']
            if ctx['event_seq'] != body['event_seq'] or ctx['cause'] not in INVALID_RESPONSE:
                raise ContractError('analysis_resolution_unproven', 'event_seq')
            request = self.executor._intent_body(attempt_id).get('request') or {}
            seed = self.s.seeds.get(run.seed_id)
            source = run.params.get('analysis_asset_id') or seed.source_asset_id
            if source != request.get('artifact_id') or (run.params.get('analysis_asset_id') and source != seed.analysis_asset_id):
                raise ContractError('analysis_response_mismatch', 'artifact_id')
            adapter = self.s.providers.get('audiovisual_analysis')
            if not callable(getattr(adapter, 'revalidate_analysis_response', None)):
                raise ContractError('analysis_response_unavailable', 'provider')
            recovered = adapter.revalidate_analysis_response(request, attempt_id)
            self.settle_unusable(attempt_id, {**body, 'evidence': body['evidence'] + '\nLocal response revalidation: ' + json.dumps(recovered['evidence'], sort_keys=True)})
            run.pause = {'code': 'analysis_failed'}
            auto._reset_budget_blocked_effect(run)
            run.state['analysis'] = recovered['analysis']
            if request.get('artifact_id') == seed.source_asset_id:
                run.state['analysis_source_sha'] = request.get('artifact_sha256')
            run.state['analysis_recovery'] = {**recovered['evidence'], 'event_seq': body['event_seq']}
            run.status = 'paused'
            run.pause = {'code': 'analysis_recovered', 'stage': run.stage,
                'detail': 'Saved response revalidated locally; no new provider request.',
                'action': 'Resume to continue with recovered analysis', 'at': utcnow()}
            run.notes.append('Recovered saved analysis locally after conservative settlement; no new provider call.')
            auto._put(run)
            u.events.append('autorun:' + run.id, 'analysis_response_recovered', {'reviewer': body['reviewer'], **run.state['analysis_recovery']})
            return run.to_dict()
