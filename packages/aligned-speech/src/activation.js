// Pure authoring adapter. No networking, model, alignment or media-generation Needs.
import { canonicalize, createMarkupSurfaceHostFacet, sealGraphFragment } from '@hypit/hypit/author-kit';
import { artifactTypes } from '@hypit/hypit/artifact';
import { narrativeTypes } from '@hypit/hypit/narrative';
import { speechTypes, materializeSemanticTake } from '@hypit/hypit/speech';

const moduleRef={name:'@factory/aligned-speech',version:'1'};
const alignmentType={module:moduleRef,name:'VerifiedAlignment'};
const producer={module:moduleRef,name:'import-aligned-take'};
const ports=[{name:'narrative',type:narrativeTypes.narrative},{name:'segment',type:narrativeTypes.excerpt},
  {name:'media',type:artifactTypes.blob},{name:'alignment',type:alignmentType}];
const output={name:'take',type:speechTypes.semanticTake};

// Only remove surrounding display punctuation. Internal punctuation, number
// pronunciation and token segmentation are not guessed or redistributed.
const normalize=text=>text.normalize('NFC').toLocaleLowerCase('en-US')
  .replace(/^[\p{P}\p{Z}\s]+|[\p{P}\p{Z}\s]+$/gu,'');

export function materializeAligned(narrative,excerpt,artifact,alignment) {
  const {frameCount,numerator,denominator,words}=alignment;
  if (![frameCount,numerator,denominator].every(n=>Number.isSafeInteger(n)&&n>0)
      || !Array.isArray(words) || artifact?.kind!=='blob' || artifact.mediaType!=='audio/wav')
    throw new Error('alignment_media_or_clock_invalid');
  const segment=narrative.segments.find(s=>s.id===excerpt.id);
  if (!segment || narrative.id!==excerpt.narrativeId || excerpt.kind!=='segment')
    throw new Error('alignment_segment_mismatch');
  const tokens=narrative.tokens.slice(segment.tokenStart,segment.tokenEndExclusive);
  if (tokens.length!==words.length) throw new Error('alignment_token_mapping_ambiguous');
  let previous=0;
  const anchors=[{identity:segment.startAnchorId,frame:0},{identity:segment.endAnchorId,frame:frameCount}];
  const timed=tokens.map((token,i)=>{
    const word=words[i];
    if (typeof word.text!=='string' || !normalize(word.text) || normalize(token.text)!==normalize(word.text)
        || !Number.isSafeInteger(word.startFrame) || !Number.isSafeInteger(word.endFrameExclusive)
        || !(previous<=word.startFrame && word.startFrame<word.endFrameExclusive && word.endFrameExclusive<=frameCount))
      throw new Error('alignment_text_or_timing_mismatch');
    previous=word.endFrameExclusive;
    anchors.push({identity:token.startAnchorId,frame:word.startFrame},
      {identity:token.endAnchorId,frame:word.endFrameExclusive});
    return {tokenId:token.id,segmentId:segment.id,startFrame:word.startFrame,endFrameExclusive:word.endFrameExclusive};
  });
  return materializeSemanticTake(narrative,excerpt,
    {timeline:{frameRate:{numerator,denominator},frameCount},audio:{artifact}},
    {tokens:timed,anchors});
}

const manifest={format:'hypit.module@1',...moduleRef,
  dependencies:[narrativeTypes.narrative.module,speechTypes.semanticTake.module,artifactTypes.blob.module].map(module=>({module})),
  types:[{name:alignmentType.name}],capabilities:[],producers:[{name:producer.name,inputs:ports,outputs:[output],needs:[]}]};
const fragment=sealGraphFragment({inputs:ports,
  operations:[{id:'import',producer,inputs:Object.fromEntries(ports.map(p=>[p.name,{kind:'fragment-input',name:p.name}])),
    result:{kind:'output',name:'take'}}],
  exports:[{...output,root:{kind:'fragment-operation',operation:'import'}}]});
const inline=record=>{
  if (record?.value.kind!=='inline') throw new Error('alignment_input_must_be_inline');
  return record.value.value;
};
const component={producers:[{producer,handler:({inputs})=>({outputs:{take:{kind:'inline',value:canonicalize(
  materializeAligned(inline(inputs.narrative),inline(inputs.segment),inputs.media.value,inline(inputs.alignment)))}},needs:{}})}],
  validators:[{type:alignmentType,handler:({value})=>{
    if (value.kind!=='inline' || !Array.isArray(value.value?.words)) throw new Error('alignment_input_invalid');
  }}]};
const declaration={name:'take',tag:'Take',mode:'structured',outputs:[alignmentType,speechTypes.semanticTake],vocabulary:{
  summary:'Import final verified speech timing without invoking speech analysis.',
  attributes:[{name:'id',kind:'identifier',required:true,summary:'Names the timing-only Take.'},
    ...ports.filter(p=>p.name!=='alignment').map(p=>({name:p.name,kind:'reference',required:true,accepts:[p.type],summary:p.name})),
    ...['frame-count','numerator','denominator'].map(name=>({name,kind:'text',required:true,summary:'Exact final frame clock.'}))],
  ports:[{...output,summary:'Native SemanticTake; include in Timeline, not Sound.'}],
  example:'<aligned:Take id="opening-take" narrative={story} segment={story.segment.opening} media={speech} frame-count="30" numerator="30" denominator="1"><aligned:Word text="Hello" start="1" end="29"/></aligned:Take>'}};
const integer=(value,label)=>{
  if (typeof value!=='string' || !/^\d+$/.test(value) || !Number.isSafeInteger(Number(value))) throw new Error(`alignment_invalid_${label}`);
  return Number(value);
};
const decode=({element,resolveReference})=>{
  const id=element.attributes.id;
  if (typeof id!=='string' || !/^[a-z][a-z0-9_-]*$/.test(id)) throw new Error('alignment_invalid_id');
  const inputs={};
  for (const port of ports.filter(p=>p.name!=='alignment')) {
    const attr=element.attributes[port.name];
    const ref=attr?.kind==='reference' ? resolveReference(attr.path) : undefined;
    if (!ref || ref.type.name!==port.type.name || ref.type.module.name!==port.type.module.name
        || ref.type.module.version!==port.type.module.version) throw new Error(`alignment_invalid_${port.name}_reference`);
    inputs[port.name]=ref.ref;
  }
  const words=[];
  for (const child of element.children) {
    if (child.kind==='text' && !child.value.trim()) continue;
    if (child.kind!=='element' || child.name.split(':').at(-1)!=='Word') throw new Error('alignment_unexpected_child');
    words.push({text:child.attributes.text,startFrame:integer(child.attributes.start,'word_start'),
      endFrameExclusive:integer(child.attributes.end,'word_end')});
  }
  const alignment={frameCount:integer(element.attributes['frame-count'],'frame_count'),
    numerator:integer(element.attributes.numerator,'numerator'),denominator:integer(element.attributes.denominator,'denominator'),words};
  inputs.alignment={kind:'record',id:`${id}.alignment`};
  return {records:[{id:`${id}.alignment`,type:alignmentType,value:{kind:'inline',value:canonicalize(alignment)},range:element.range}],
    components:[{id,fragment:fragment.id,inputs,outputs:{take:`${id}.take`},range:element.range}],fragments:[fragment],exports:[`${id}.take`]};
};
export const hypitPackage={format:'hypit.node-package@1',modules:[{manifest}],components:[component],
  hostFacets:[createMarkupSurfaceHostFacet({module:moduleRef,declaration,handler:decode})]};
export default hypitPackage;
