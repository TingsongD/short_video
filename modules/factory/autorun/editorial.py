"""One durably quoted semantic plan after final TTS, before footage submission."""
from ..analysis.editorial_planning import PlanningStore
from ..analysis.flashcut_vertex import ROUTE_LIMITS
from ..domain.errors import ContractError
from ..domain.records import content_hash
from ..services.editorial_work import planning_input


def prepare(autorun,run):
    s=autorun.s
    experiment=s._current(run.experiment_id,run.state['experiment_revision'],True)
    inputs,binding,evidence=planning_input(s,experiment)
    store=PlanningStore(s.db,s.source_evidence.blobs.root)
    existing=store.get(binding)
    if existing:
        run.state['editorial_intent']=existing['manifest'];autorun._put(run)
        return None
    adapter=s.providers.get('audiovisual_analysis_flashcut')
    if not adapter:raise ContractError('flashcut_route_unavailable','editorial')
    legacy_tag='editorial_'+content_hash(binding)[:16]
    legacy=bool(run.state.get(legacy_tag+'_jobs'))
    request={'task':'plan_flashcut_edits','model':adapter.model,
        'prompt_version':'flashcut_editorial.v1' if legacy else 'flashcut_editorial.v2',
        'limits':ROUTE_LIMITS,'binding':evidence,'editorial_binding':binding,'editorial_input':inputs,
        'understanding':experiment.packaging['flashcut_editorial']['understanding']}
    if not legacy:
        request['output_policy']='flashcut_output.v2'
    tag=legacy_tag if legacy else 'editorial_v2_'+content_hash(binding)[:16]
    result=autorun._run_effect(run,'analysis',adapter.name,adapter.model,[request],tag)
    if result!='wait':return result
    result=autorun._jobs(run,run.state[tag+'_jobs'],'editorial_planning_failed')
    if result!='next':return result
    output=s.commands.get(run.state[tag+'_jobs'][0])['command']['result']['result']
    if output['binding']!=binding:raise ContractError('editorial_evidence_mismatch','result')
    saved=store.save(binding,inputs,output['editorial'])
    origin = output.get('plan_origin') or (
        'local_conservative' if output.get('editorial_recovery') else 'provider')
    if origin not in ('provider', 'local_conservative'):
        raise ContractError('editorial_plan_unproven', 'plan_origin')
    run.state['editorial_plan_origin'] = origin
    if output.get('editorial_recovery'):
        run.notes.append(
            'Editorial provider response was capped or invalid; '
            'a deterministic conservative plan preserved source-bound cuts. '
            'No extra provider request was submitted.')
        run.state['editorial_recovery'] = output['editorial_recovery']
    run.state['editorial_intent']=saved['manifest'];autorun._put(run)
    return None
