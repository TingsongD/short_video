"""Bounded JSON command inputs. Domain services still enforce authority."""
import json
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from ..domain.errors import ContractError

class Command(BaseModel):
    model_config=ConfigDict(extra='allow',strict=True)

class SeedInput(Command):
    url: str=Field(min_length=1,max_length=4096)

class MediaInput(Command):
    artifact_id: str=Field(min_length=1,max_length=256)

class AnalysisInput(Command):
    observations: dict
    reviewer: str=Field(min_length=1,max_length=256)

class ReviewInput(Command):
    check_type: str
    verdict: str
    target_hash: str
    reviewer: str=Field(min_length=1,max_length=256)

class TargetInput(Command):
    start_frame:int=Field(ge=0)
    end_frame:int=Field(gt=0)

class SegmentInput(Command):
    id:str=Field(min_length=1,max_length=256)
    target:TargetInput
    picture:dict
    speech:dict={}
    spoken_copy:str=Field(default='',alias='copy')
    captions:list[dict]=[]

class BranchInput(Command):
    key:str
    factor:str
    regions:list[dict]
    segments:list[SegmentInput]=Field(min_length=1,max_length=100)
    hypothesis:str
    primary_metric:str
    allowed_fields:list[str]

class ExperimentInput(Command):
    blueprint_id: str
    template_id: str
    segments: list[SegmentInput]=Field(min_length=1,max_length=100)
    variants: list[BranchInput]=Field(min_length=3,max_length=3)

class DeliveryInput(MediaInput):
    folder_id: str
    account: str
    reviewer: str=Field(min_length=1,max_length=256)
    valid_until: str
    target_hash: str
    check_ids: list[str]=Field(min_length=1)

async def json_command(request):
    data=bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data)>1024*1024:raise ContractError('too_large','json')
    try:
        body=json.loads(data)
        path=request.url.path
        schema=SeedInput if path=='/api/seeds' else ExperimentInput if path=='/api/experiments' else \
            MediaInput if '/seeds/' in path and path.endswith('/media') else \
            AnalysisInput if path.endswith('/analyze') else \
            ReviewInput if path.endswith('/reviews') else DeliveryInput if path.endswith('/deliver') else Command
        schema.model_validate(body)
        from ..events.redact import redact
        if redact(body)!=body:raise ContractError('sensitive_input','body','Use configured credentials and registered artifacts')
        return body
    except ContractError:
        raise
    except (ValueError,ValidationError) as exc:
        # Never return raw inputs from Pydantic errors (they may contain secrets).
        detail='JSON object required'
        if isinstance(exc,ValidationError):
            detail='; '.join('.'.join(map(str,e['loc']))+': '+e['type'] for e in exc.errors(include_input=False))
        raise ContractError('invalid_command','body',detail) from None
