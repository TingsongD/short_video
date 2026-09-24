"""Reuse completed, exact same-variant work after editorial-only revisions."""
import json

from ..domain.errors import ContractError


def reusable_picture(service,experiment_id,node):
    rows=service.db.conn.execute("SELECT w.body FROM records w JOIN records p "
        "ON p.kind='productionplan' AND p.id=json_extract(w.body,'$.plan_id') "
        "WHERE w.kind='workitem' AND json_extract(w.body,'$.kind')='picture' "
        "AND json_extract(p.body,'$.experiment_id')=? "
        "AND json_extract(w.body,'$.request_hash')=? ORDER BY w.created_at DESC,w.id DESC",
        (experiment_id,node['request_hash'])).fetchall()
    unresolved=False
    for row in rows:
        prior=json.loads(row['body'])
        if any(prior.get(k)!=node.get(k) for k in ('provider','model','request','takes','consumers')):
            continue
        def allocations(item):
            return [{k:a[k] for k in ('duration_s','offset_s','covers_s')} for a in item['allocations']]
        if allocations(prior)!=allocations(node):continue
        uncertain=service.db.conn.execute("SELECT 1 FROM attempts WHERE job_id=? "
            "AND status IN ('prepared','dispatching','unknown','accepted','running','cancel_requested') LIMIT 1",
            (prior['id'],)).fetchone()
        if uncertain:
            unresolved=True
            continue
        # Collection and overlay repairs store the currently selected bytes
        # on the download node. Picture nodes often have no artifact ids;
        # where they do, those ids can predate a verified repair.
        downloads=[d for d in service._nodes(prior['plan_id']).values()
                   if d['kind']=='download' and d.get('depends')==[prior['node_key']]]
        if downloads:
            if len(downloads)!=1:
                continue
            download=downloads[0]
            if download['status']=='downloaded':
                assets=download.get('artifact_ids',[])
            elif download['status']=='planned' and not download.get('artifact_ids'):
                assets=prior.get('artifact_ids',[])
            else:
                continue
        else:
            assets=prior.get('artifact_ids',[])
        if prior['status'] not in ('accepted','downloaded','manual') or len(assets)!=len(node['allocations']):
            continue
        for ident,allocation in zip(assets,node['allocations']):
            service.artifacts.verified_path(ident)
            artifact=service.db.uow().artifacts.get(ident)
            if (not artifact or artifact['kind']!='video'
                    or (json.loads(artifact['probe']).get('duration_s') or 0)+.0001<allocation['covers_s']):
                raise ContractError('reused_footage_invalid','artifact_id',ident)
        return {'work_id':prior['id'],'artifact_ids':assets}
    if unresolved:
        raise ContractError('prior_footage_unresolved','request_hash',
            'Matching footage is still unresolved. Reconcile its existing operation; do not regenerate it for a new editorial revision.')
    return None
