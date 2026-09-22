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
    request={'task':'plan_flashcut_edits','model':adapter.model,'prompt_version':'flashcut_editorial.v1',
        'limits':ROUTE_LIMITS,'binding':evidence,'editorial_binding':binding,'editorial_input':inputs,
        'understanding':experiment.packaging['flashcut_editorial']['understanding']}
    tag='editorial_'+content_hash(binding)[:16]
    result=autorun._run_effect(run,'analysis',adapter.name,adapter.model,[request],tag)
    if result!='wait':return result
    result=autorun._jobs(run,run.state[tag+'_jobs'],'editorial_planning_failed')
    if result!='next':return result
    output=s.commands.get(run.state[tag+'_jobs'][0])['command']['result']['result']
    if output['binding']!=binding:raise ContractError('editorial_evidence_mismatch','result')
    saved=store.save(binding,inputs,output['editorial'])
    if output.get('editorial_recovery'):
        run.notes.append(
            'Editorial provider response was complete but invalid; '
            'a deterministic conservative plan preserved source-bound cuts. '
            'No extra provider request was submitted.')
        run.state['editorial_recovery'] = output['editorial_recovery']
    run.state['editorial_intent']=saved['manifest'];autorun._put(run)
    return None
