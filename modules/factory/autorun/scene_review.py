"""Read-only compatibility for retired scene-review records.

No submission, approval, override or replacement. Historical source-bound
corrections remain usable; unknown paid requests must still be reconciled.
"""
from ..domain.errors import ContractError
from ..domain.records import content_hash


class SceneReview:
    def __init__(self, services):
        self.s = services

    def jobs(self, run):
        return [job for tag in ('scene_review_correct', 'scene_review_verify')
                for job in run.state.get(tag + '_jobs') or []]

    def unfinished(self, run):
        return any(self.s.db.conn.execute(
            "SELECT 1 FROM attempts WHERE job_id=? AND status NOT IN "
            "('succeeded','downloaded','failed','cancelled')", (job,)).fetchone()
            or self.s.db.conn.execute(
                "SELECT 1 FROM jobs WHERE id=? AND status NOT IN ('succeeded','failed','cancelled','blocked')",
                (job,)).fetchone()
            for job in self.jobs(run))

    def guard_resume(self, run):
        if self.unfinished(run):
            raise ContractError('analysis_reconciliation_required', 'historical_review',
                                'Resolve the earlier paid request before continuing; scene review removal never authorizes a retry.')

    def verified(self, run, source_sha):
        state = run.state.get('scene_review') or {}
        return (bool(state.get('verified_at')) and state.get('policy') == 'scene-review.v1'
                and state.get('source_sha256') == source_sha
                and state.get('output_hash') == content_hash(run.state.get('analysis') or {}))

    def manual_verified(self, run, source_sha):
        state = run.state.get('manual_scene_review') or {}
        return (bool(state.get('reviewer')) and state.get('source_sha256') == source_sha
                and state.get('output_hash') == content_hash(run.state.get('analysis') or {}))
