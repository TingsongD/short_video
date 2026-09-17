"""Auditable creator-specific preceding-post cohorts, with explicit availability."""
from datetime import datetime, timezone
from statistics import mean,median
import math
from ..domain.errors import ContractError
DEFAULT_MIN=20
DEFAULT_MAX=50
MIXED_PERIOD_DAYS=30


def _day(value):
    try:
        result=datetime.fromisoformat(value.replace('Z','+00:00'))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (AttributeError,ValueError,TypeError):return None


def build_cohort(seed,videos,min_size=DEFAULT_MIN,max_size=DEFAULT_MAX,now=None):
    if not 1<=min_size<=max_size<=100:raise ContractError('invalid_cohort_size','policy')
    cutoff=_day(now or seed.get('observed_at'));published=_day(seed.get('published_at'))
    included=[];excluded=[];seen=set();creator=seed.get('creator_id')
    for v in videos:
        pid=v.get('post_id');identity=(v.get('platform'),pid);date=_day(v.get('published_at'));observed=_day(v.get('observed_at'))
        reason=None
        if pid==seed.get('post_id') and v.get('platform')==seed.get('platform'):reason='is_seed'
        elif not pid:reason='missing_post_identity'
        elif not creator or not v.get('creator_id'):reason='missing_creator'
        elif v['creator_id']!=creator:reason='different_creator'
        elif not v.get('platform') or v['platform']!=seed.get('platform'):reason='different_platform'
        elif not seed.get('format') or v.get('format')!=seed['format']:reason='mixed_format'
        elif not published or not date:reason='missing_publication_date'
        elif date>=published:reason='published_after_seed'
        elif not cutoff or not observed:reason='missing_observation_date'
        elif observed>cutoff or date>observed:reason='future_observation'
        elif v.get('views') is None:reason='missing_views'
        elif type(v['views']) not in (int,float) or not math.isfinite(v['views']) or v['views']<0:reason='invalid_views'
        elif identity in seen:reason='duplicate_post'
        if reason:excluded.append({'post_id':pid,'creator_id':v.get('creator_id'),'reason':reason})
        else:seen.add(identity);included.append(v)
    included.sort(key=lambda v:_day(v['published_at']),reverse=True)
    excluded += [{'post_id':v['post_id'],'reason':'beyond_cohort_max'} for v in included[max_size:]]
    included=included[:max_size];counts=[v['views'] for v in included]
    flags=[]
    if len(included)<min_size:flags.append('small_sample')
    if not creator:flags.append('creator_unavailable')
    if not cutoff:flags.append('observation_cutoff_unavailable')
    if included and (_day(included[0]['published_at'])-_day(included[-1]['published_at'])).days>MIXED_PERIOD_DAYS:flags.append('mixed_periods')
    available=len(included)>=min_size and bool(creator and cutoff and published)
    return {'included':[v['post_id'] for v in included],'excluded':excluded,'size':len(included),
            'available':available,'mean_views':mean(counts) if available else None,'median_views':median(counts) if available else None,
            'observed_mean_views':mean(counts) if counts else None,'observed_median_views':median(counts) if counts else None,
            'flags':flags,'creator_id':creator,'observed_at':cutoff.isoformat() if cutoff else None,
            'policy':{'minimum':min_size,'maximum':max_size,'format':seed.get('format'),'preceding':seed.get('published_at')},
            'observations':[{k:v.get(k) for k in ('post_id','creator_id','platform','format','views','published_at','observed_at')} for v in included]}
