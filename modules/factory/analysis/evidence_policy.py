"""Versioned flash-cut policy. Defaults are frozen on new runs only."""
from copy import deepcopy
from ..domain.errors import ContractError
from ..domain.records import content_hash

PROFILE = 'flashcut_hypit.v1'
PE_COMMIT = '3e352cca660658d4b5c90f42a7808b11469e4c66'
PE_REVISION = 'aabf3b990573d8114ae6e501b4697106beac8f19'
PE_SHA256 = 'ccc8340a14ea3ebf557a288ba4ed4a5bc026ab98bb4da42fc745d44b4c5c5ffb'


def _policy(version, *, quality=None):
    value = {
        'version': version, 'profile_id': PROFILE,
        'renderer': 'hypit_primary.v1', 'editorial': 'semantic_edits.v1',
        'visual': {'coverage': 'all_frames', 'model': 'PE-Core-S16-384',
                   'code_revision': PE_COMMIT, 'checkpoint_revision': PE_REVISION,
                   'checkpoint_sha256': PE_SHA256, 'preprocessing': 'pe_squash384.v1',
                   'device': 'cpu', 'precision': 'float32', 'batch_size': 8, 'chunk_frames': 256},
        'audio': {'version': 'audio_events.v1', 'sample_rate': 48000, 'hop_samples': 480,
                  'rms_window': 960, 'onset_window': 2048, 'bass_window': 4096,
                  'bass_hz': [20, 200], 'chunk_seconds': 10, 'rhythm_context_seconds': 10,
                  'pause_min_ms': 80, 'channel_policy': 'aggregate_power',
                  'resampling': 'explicit_padding_1ms.v1'},
        'fusion': {'version': 'av_fusion.v1', 'context_ms': 500, 'baseline_seconds': 2,
                   'max_window_seconds':4,'window_overlap_seconds':1,'optional_stills':'one_per_second.v1'},
        'decision': {'provider': 'jev_decisions', 'model': 'jev-1.13.0', 'mode': 'shadow',
                     'rubric': 'optional_evidence.v1', 'fallback': 'conservative'},
        'understanding': {'provider': 'audiovisual_analysis_flashcut', 'model': 'gemini-3.8-flash',
                          'prompt': 'flashcut_understanding.v1', 'clarification_rounds': 2},
        'resources': {'repairs_per_chunk': 2, 'rss_bytes': 8 * 1024**3,
                      'max_decoded_frames': 18000, 'max_media_seconds': 600,
                      'queue_bytes': 256 * 1024**2, 'queue_frames': 16,
                      'max_disk_bytes': 32 * 1024**3, 'min_free_bytes': 10 * 1024**3,
                      'no_progress_seconds': 120},
    }
    if quality is not None:
        value['quality'] = deepcopy(quality)
    return value


def legacy_flashcut_policy():
    """Return the exact policy frozen into already-created v1 runs."""
    return _policy('flashcut_policy.v1')


def new_flashcut_policy():
    """Default policy for newly created flash-cut runs only."""
    return _policy('flashcut_policy.v2', quality={
        'technical_temporal': 'flashcut_temporal_qc.v1',
        'brief_event_max_frames': 6,
        'caption_alignment': 'final_speech_schedule.v1',
    })


def validate_flashcut_policy(value):
    # Each version is one frozen configuration, not arbitrary executable input
    # from the dashboard. Historical v1 records retain historical behavior.
    if value not in (legacy_flashcut_policy(), new_flashcut_policy()):
        raise ContractError('unsupported_flashcut_policy', 'flashcut_policy')
    return deepcopy(value)


def policy_hash(value):
    return content_hash(validate_flashcut_policy(value))
