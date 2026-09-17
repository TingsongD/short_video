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


def bootstrap(root, *, providers=None, drive=None, settings=None):
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
    from .studio.launcher import LocalStudioLauncher
    services.studio.launcher=LocalStudioLauncher(registry,data/'studio')
    if drive is not None:
        from .delivery.service import DeliveryService
        services.delivery=DeliveryService(db,drive,artifacts,executor=executor)
    # Register recovery roots before any local builds or provider receipts.
    import json
    with db.uow() as u:
        u.conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('recovery_roots',?)",(json.dumps(
            {name:str(data/name) for name in ('providers','compositions','renders','processes','studio')}),))
    return services
