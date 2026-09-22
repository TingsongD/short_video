"""Full-video variant provenance: every beat must use independent footage."""
from ..domain.errors import ContractError


def full_video_evidence(services, plan, variant):
    nodes = services.production._nodes(plan['id'])
    proof, all_hashes = [], {}
    for key in 'ABCD':
        v = services.experiments._variant(plan['experiment_id'], key)
        for seg in v.segments:
            pics = [n for n in nodes.values() if n['kind'] == 'picture'
                    and any(t['variant'] == key and t['slot'] == seg['id'] for t in n['takes'])]
            if len(pics) != 1 or pics[0]['consumers'] != [key]:
                raise ContractError('full_video_coverage_invalid', 'picture', f'{key}:{seg["id"]}')
            downloads = [n for n in nodes.values() if n['kind'] == 'download'
                         and pics[0]['node_key'] in n['depends']]
            if len(downloads) != 1 or not downloads[0].get('artifact_ids'):
                raise ContractError('full_video_coverage_invalid', 'download')
            hashes = []
            for aid in downloads[0]['artifact_ids']:
                services.artifacts.verified_path(aid)
                art = services.db.uow().artifacts.get(aid)
                if not art or art['kind'] != 'video':
                    raise ContractError('full_video_requires_motion', 'artifact_id')
                owner = all_hashes.setdefault(art['sha256'], key)
                if owner != key:
                    raise ContractError('cross_variant_footage_reuse', 'artifact_id')
                hashes.append(art['sha256'])
            proof.append({'variant': key, 'segment': seg['id'], 'hashes': hashes})
    control = services.experiments._variant(plan['experiment_id'], 'A')
    unchanged_audio = []
    for a, b in zip(control.segments, variant.segments):
        if a['id'] != b['id'] or a['target'] != b['target']:
            raise ContractError('full_video_timing_changed', 'segments')
        if a.get('copy') == b.get('copy') and a.get('speech') == b.get('speech'):
            unchanged_audio.append(a['target'])
    return {'ok': True, 'mode': 'full_video', 'coverage': proof}, unchanged_audio
