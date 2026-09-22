"""Native Hypit authoring from verified final speech, never source timings."""
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re

from modules.assemble.hypit_markup import escape_markup_text
from ..domain.errors import ContractError
from ..domain.records import content_hash

PACKAGE=Path(__file__).resolve().parents[3]/'packages/aligned-speech'


def frozen_package():
    # JavaScript is already the executable build. Freeze all allowed source
    # bytes, not a symlink to mutable workspace code or installed dependencies.
    names=['package.json','src/activation.js','README.md']
    files={f'packages/aligned-speech/{name}':(PACKAGE/name).read_text() for name in names}
    digest=content_hash({k:hashlib.sha256(v.encode()).hexdigest() for k,v in files.items()})
    return files,digest


def validate_editorial(editorial,variant,clock,artifacts,captions,segments=()):
    if editorial.get('version')!='semantic_edits.v1' or editorial.get('variant_key')!=variant:
        raise ContractError('semantic_revision_mismatch','editorial')
    passages=editorial.get('passages')
    if not isinstance(passages,list):
        raise ContractError('semantic_passages_required','editorial')
    previous=0; seen=set(); expected=[]; moments={}
    for passage in passages:
        ident=passage.get('id','')
        if not re.fullmatch('[a-z][a-z0-9-]{0,48}',ident) or ident in seen or ident=='script':
            raise ContractError('semantic_passage_id','editorial')
        seen.add(ident)
        low,high=passage['in_frame'],passage['out_frame']
        if type(low) is not int or type(high) is not int or not previous<=low<high<=clock['total_frames']:
            raise ContractError('semantic_passage_interval','editorial')
        previous=high
        art=artifacts.db.uow().artifacts.get(passage['artifact_id'])
        if not art or art['kind']!='audio' or art['sha256']!=passage['sha256']:
            raise ContractError('semantic_audio_mismatch',ident)
        artifacts.verified_path(art['id'])
        probe=json.loads(art['probe'])
        if 'wav' not in probe.get('format_name','') or abs(probe['duration_s']-(high-low)/clock['fps'])>1/48000:
            raise ContractError('semantic_audio_duration_mismatch',ident)
        if any(not re.fullmatch('[a-f0-9]{64}',str(passage.get(k,''))) for k in ('speech_hash','alignment_hash')):
            raise ContractError('semantic_alignment_identity_required',ident)
        words=passage['words'];last=low
        if not isinstance(words,list) or not words or ' '.join(w['text'] for w in words).split()!=passage['text'].split():
            raise ContractError('semantic_text_mismatch',ident)
        for index,word in enumerate(words):
            if (type(word['start_frame']) is not int or type(word['end_frame']) is not int
                    or not last<=word['start_frame']<word['end_frame']<=high):
                raise ContractError('semantic_word_timing_invalid',ident)
            last=word['end_frame']
            # Hypit's first marker at a structural edge denotes the Segment
            # boundary, not a guessed first-word boundary after leading silence.
            moments[f'{ident}-word-{index}']=low if index==0 else word['start_frame']
        refs=[i for group in passage['phrases'] for i in group]
        if refs!=list(range(len(words))) or any(not group for group in passage['phrases']):
            raise ContractError('semantic_phrase_coverage_invalid',ident)
        for group in passage['phrases']:
            expected.append((' '.join(words[i]['text'] for i in group).split(),
                             words[group[0]]['start_frame'],words[group[-1]]['end_frame']))
    actual=[(c['text'].split(),c['start_frame'],c['end_frame']) for c in sorted(captions,key=lambda c:c['start_frame'])]
    if expected!=actual:
        raise ContractError('semantic_caption_mismatch','final_narration')
    for segment in segments:
        if segment.get('semantic_start') and moments.get(segment['semantic_start'])!=segment['in_frame']:
            raise ContractError('semantic_cut_binding_mismatch',segment['id'])


def script_literal(text):
    return re.sub(r'([\\@<>{}|])',r'\\\1',text)


def declarations(editorial,clock,artifacts):
    passages=editorial['passages'];lines=[];bindings=[]
    if passages:
        lines.append('  <script:script id="story">')
        for p in passages:
            tokens=[]
            beginnings={g[0]:n for n,g in enumerate(p['phrases'])}
            endings={g[-1]:n for n,g in enumerate(p['phrases'])}
            for i,w in enumerate(p['words']):
                if i in beginnings:tokens.append(f'@{p["id"]}-phrase-{beginnings[i]}')
                tokens.extend([f'@{p["id"]}-word-{i}!',script_literal(w['text'])])
                if i in endings:
                    tokens.append(f'@/{p["id"]}-phrase-{endings[i]}')
                    if i!=len(p['words'])-1:tokens.append('||')
            lines.append(f'    <{p["id"]}> '+ ' '.join(tokens)+f' </{p["id"]}>')
        lines.append('  </script:script>')
    rate=Fraction(clock.get('fps_num',str(clock['fps'])),clock.get('fps_den',1)) if 'fps_num' in clock else Fraction(str(clock['fps'])).limit_denominator(100000)
    for p in passages:
        ident=p['id']
        lines.append(f'  <asset:Audio id="speech-{ident}" src="./assets/speech-{ident}.wav"/>')
        lines.append(f'  <aligned:Take id="take-{ident}" narrative={{story}} segment={{story.segment.{ident}}} media={{speech-{ident}}} frame-count="{p["out_frame"]-p["in_frame"]}" numerator="{rate.numerator}" denominator="{rate.denominator}">')
        for word in p['words']:
            lines.append(f'    <aligned:Word text="{escape_markup_text(word["text"])}" start="{word["start_frame"]-p["in_frame"]}" end="{word["end_frame"]-p["in_frame"]}"/>')
        lines.append('  </aligned:Take>')
        bindings.append({'binding':f'speech-{ident}','role':'semantic_timing','track':'timing',
            'artifact_id':p['artifact_id'],'sha256':p['sha256'],'in_frame':p['in_frame'],'out_frame':p['out_frame'],
            'speech_hash':p['speech_hash'],'alignment_hash':p['alignment_hash']})
    lines.append(f'  <time:Timeline id="program" clock={{clock}} end="{clock["total_frames"]}f">')
    lines.extend(f'    <time:Take source={{take-{p["id"]}.take}} at="{p["in_frame"]}f"/>' for p in passages)
    lines.append('  </time:Timeline>')
    return lines,bindings


def caption_track(editorial):
    lines=['  <asset:Font id="caption-font" src="./assets/caption.ttf" weight="400" style="normal"/>',
           '  <caption-fine:Style id="cap" recipe={look.caption.primary} font={caption-font}/>',
           '  <caption-fine:Track id="captions" document={story.caption} timeline={program.timeline}>']
    for p in editorial['passages']:
        for n,_ in enumerate(p['phrases']):
            lines.append(f'    <caption-fine:Use style={{cap}} during={{story.selection.{p["id"]}-phrase-{n}}}/>')
    lines.append('  </caption-fine:Track>')
    return lines


def caption_recipe(width):
    return ('  caption.primary { stack-order: 70; x: 0.5; y: 0.88; width: 0.84; height: 0.22; '
            'anchor-x: center; anchor-y: bottom; align: center; block-align: end; inline-size: fixed; '
            f'wrap: word; size: {48*width/720:g}; line-height: 1.2; fill: #FFFFFF; '
            'background: #000000CC; padding: "2"; radius: 2; karaoke: off; '
            'cue-enter: none; cue-exit: none; lead-frames: 0; tail-frames: 0; handoff: cut; }\n')
