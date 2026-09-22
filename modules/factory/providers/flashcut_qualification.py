"""A first live qualification is scoped to ONE fresh run, not a route promotion.

This scope permits transport construction only. It grants no budget authority;
normal quoted effects/reservations must still authorize every request.
"""
from datetime import datetime, timezone
import json

from .preflight import RequestNotSent


def acceptance_scope(db, connection):
    value=connection.get('acceptance_scope')
    if not isinstance(value,dict) or set(value)!={'run_id','seed_id','source_sha256','valid_until'}:
        return None
    try:
        if datetime.fromisoformat(value['valid_until'].replace('Z','+00:00'))<=datetime.now(timezone.utc):return None
        row=db.uow().records.get('autorun',value['run_id'])
        run=json.loads(row['body']) if row else {}
        if (run.get('seed_id')!=value['seed_id'] or run.get('params',{}).get('profile_id')!='flashcut_hypit.v1'
                or run.get('status') in ('succeeded','cancelled','failed')):return None
        seed=db.uow().records.get('seed',value['seed_id'])
        artifact=db.uow().artifacts.get(json.loads(seed['body'])['source_asset_id']) if seed else None
        if not artifact or artifact['sha256']!=value['source_sha256']:return None
    except (KeyError,TypeError,ValueError):return None
    return dict(value)


def require_acceptance_binding(db, scope, request):
    current=acceptance_scope(db,{'acceptance_scope':scope})
    if not current:raise RequestNotSent('flashcut_acceptance_scope_expired')
    binding=request.get('binding',{})
    rows=db.conn.execute("SELECT body FROM records WHERE kind='sourceevidence' AND status='complete' "
        "AND json_extract(body,'$.manifest.sha256')=?",(binding.get('evidence_sha256'),)).fetchall()
    if len(rows)!=1:raise RequestNotSent('flashcut_acceptance_scope_mismatch')
    evidence=json.loads(rows[0][0])
    if (evidence['run_id']!=current['run_id'] or binding.get('source_sha256')!=current['source_sha256']
            or evidence['binding']['seed_id']!=current['seed_id']
            or evidence['binding']['transcript_sha256']!=binding.get('transcript_sha256')):
        raise RequestNotSent('flashcut_acceptance_scope_mismatch')
