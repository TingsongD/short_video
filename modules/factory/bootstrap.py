"""One composition root for the loopback API and independent worker."""
from pathlib import Path
from .store import Database
from .operations.paths import data_root
from .operations.config import load_config
from .artifacts.registry import ArtifactStore
from .seeds.registry import SeedRegistry
from .analysis.service import AnalysisService
from .analysis.review import BlueprintReview
from .templates.service import TemplateService
from .experiments.service import ExperimentService
from .scheduler import Scheduler
from .execution import Executor
from .production.plan import ProductionService
from .composition.compiler import CompositionService
from .rendering.service import RenderService
from .quality.service import QualityService
from .quality.technical import TechnicalQC
from .quality.regions import RegionGate
from .resources.service import ResourceRegistry, CleanupService
from .studio.service import StudioService
from .services.app import FactoryServices


def bootstrap(root, *, providers=None, drive=None, settings=None,publisher=None,analytics_client=None):
    root=Path(root).resolve(); data=data_root(root); data.mkdir(parents=True,exist_ok=True)
    config=load_config(root)['values']
    settings={**{'mode':config.get('FACTORY_EXECUTION_MODE','offline'), 'drive_folder_id':config.get('DRIVE_FOLDER_ID','')}, **(settings or {})}
    if settings['mode'] not in ('offline','live'):
        from .domain.errors import ContractError
        raise ContractError('invalid_execution_mode','mode')
    db=Database(data/'factory.db'); artifacts=ArtifactStore(data/'artifacts',db)
    if providers is None and drive is None:
        from .providers.configured import configured_adapters
        providers,drive=configured_adapters(db,data,settings['mode'],artifacts)
    from .providers.configured import configured_auxiliary
    extra_providers,configured_publisher,configured_analytics,extra_settings=configured_auxiliary(root,data,settings["mode"],artifacts)
    providers={**extra_providers,**(providers or {})};publisher=publisher or configured_publisher;analytics_client=analytics_client or configured_analytics
    settings={**extra_settings,**settings}
    seeds=SeedRegistry(db); scheduler=Scheduler(db); executor=Executor(db)
    registry=ResourceRegistry(db); cleanup=CleanupService(registry)
    services=FactoryServices(db,seeds=seeds,experiments=ExperimentService(db),scheduler=scheduler,
        artifacts=artifacts,executor=executor,providers=providers,
        analysis=AnalysisService(db,seeds,artifacts,executor,None),blueprints=BlueprintReview(db),
        templates=TemplateService(db),quality=QualityService(db,TechnicalQC(),RegionGate()),
        production=ProductionService(db,scheduler,executor,artifacts=artifacts),
        composition=CompositionService(db,artifacts,data/'compositions'),
        rendering=RenderService(db,artifacts,data/'renders'),resources=registry,cleanup=cleanup,
        studio=StudioService(db,registry,cleanup=cleanup),config=settings)
    from .providers.router import ProviderRouter
    services.production.router=ProviderRouter(db,services.providers,executor=executor,live=settings["mode"]=="live")
    from .studio.launcher import LocalStudioLauncher
    services.studio.launcher=LocalStudioLauncher(registry,data/'studio')
    from .services.effect_work import EffectWork
    services.effect_work=EffectWork(services)
    from .autorun.service import AutoRunService
    services.autorun=AutoRunService(services)
    from .services.audio_work import AudioWork
    services.audio_work=AudioWork(services)
    from .services.analysis_work import AnalysisWork
    services.analysis_work=AnalysisWork(services)
    from .analysis.deep import ReferenceAnalysisService, HypitTransport
    services.ref_analysis=ReferenceAnalysisService(
        db,seeds,artifacts,data/'analysis-projects',
        HypitTransport(root/'scripts'/'hypit.sh'))
    from .analysis.source_evidence import SourceEvidenceService, binding_from_db
    from .services.source_work import SourceEvidenceWork
    services.source_evidence = SourceEvidenceService(db, data/'source_evidence',
        verify_lease=scheduler._verify_lease, current_binding=lambda rid: binding_from_db(db, rid))
    services.source_work = SourceEvidenceWork(services, Path(__file__).resolve().parents[2])
    from .publishing.service import PublishingService
    from .analytics.service import ReadbackService
    from .learning.service import LearningService
    from .services.publication_work import PublicationWork
    from .audio.mix import MixService
    services.mix=MixService(db,artifacts)
    services.publishing=PublishingService(db,publisher=publisher,accounts=settings.get('publication_accounts',{}),executor=executor,max_per_day=settings.get('posts_per_day',2))
    # Publisher-routed metrics for non-YouTube destinations (PL-04);
    # populated only by adapters that expose a verified analytics call.
    pub_metrics={}
    if publisher is not None and hasattr(publisher,'analytics'):
        pub_metrics['upload_post']=publisher.analytics
    services.readback=ReadbackService(db,analytics_client,
                                      publisher_metrics=pub_metrics)
    from .metadata.service import MetadataService
    services.metadata=MetadataService(db)
    services.learning=LearningService(db)
    services.publication_work=PublicationWork(services)
    # Delayed metric checkpoints: scheduled once a publication reaches
    # a confirmed public state, claimed by the collect queue when due.
    from .services.checkpoints import CheckpointService
    services.checkpoints=CheckpointService(db,services.commands,
                                           lambda: services.readback)
    services.publishing.on_public=services.checkpoints.schedule_for
    from .services.rounds import RoundService
    services.rounds=RoundService(services)
    if drive is not None:
        from .delivery.service import DeliveryService
        services.delivery=DeliveryService(db,drive,artifacts,executor=executor)
    # Register recovery roots before any local builds or provider receipts.
    import json
    with db.uow() as u:
        u.conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('recovery_roots',?)",(json.dumps(
            {name:str(data/name) for name in ('providers','compositions','renders','processes','studio','source_evidence')}),))
    return services
