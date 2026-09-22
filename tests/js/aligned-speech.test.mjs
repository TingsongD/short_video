import { test } from 'node:test';
import assert from 'node:assert/strict';
import { materializeAligned, hypitPackage } from '../../packages/aligned-speech/src/activation.js';

const segment={id:'opening',tokenStart:0,tokenEndExclusive:2,startAnchorId:'segment:start',endAnchorId:'segment:end'};
const tokens=['Hello','world'].map((text,i)=>({id:`native-token-${i}`,segmentId:'opening',text,
  startAnchorId:`native-start-${i}`,endAnchorId:`native-end-${i}`}));
const narrative={id:'native-story',segments:[segment],tokens,semanticIndex:{anchors:[
  {id:segment.startAnchorId,segmentId:'opening'},{id:segment.endAnchorId,segmentId:'opening'},
  ...tokens.flatMap(t=>[{id:t.startAnchorId,segmentId:'opening'},{id:t.endAnchorId,segmentId:'opening'}])
]}};
const excerpt={kind:'segment',narrativeId:narrative.id,id:segment.id,tokenStart:0,tokenEndExclusive:2};
const media={kind:'blob',resource:'res_verified-waveform',mediaType:'audio/wav',size:96044};
const alignment={frameCount:30,numerator:30,denominator:1,words:[
  {text:'Hello,',startFrame:1,endFrameExclusive:10},{text:'world!',startFrame:14,endFrameExclusive:29}
]};

test('imports verified timings using native token identities and no provider capabilities',()=>{
  const take=materializeAligned(narrative,excerpt,media,alignment);
  assert.deepEqual(take.tokens.map(t=>[t.tokenId,t.startFrame,t.endFrameExclusive]),
    [['native-token-0',1,10],['native-token-1',14,29]]);
  assert.deepEqual(take.media.audio.artifact,media);
  assert.deepEqual(hypitPackage.modules[0].manifest.capabilities,[]);
  assert.deepEqual(hypitPackage.modules[0].manifest.producers[0].needs,[]);
});

test('rejects missing words, changed text, overlap and invented timing',()=>{
  for (const words of [alignment.words.slice(0,1),
    [{...alignment.words[0],text:'Goodbye'},alignment.words[1]],
    [alignment.words[0],{...alignment.words[1],startFrame:9}],
    [{...alignment.words[0],endFrameExclusive:1},alignment.words[1]]]) {
    assert.throws(()=>materializeAligned(narrative,excerpt,media,{...alignment,words}),/alignment/);
  }
});

test('refuses ambiguous provider word to native-token mapping',()=>{
  const cjk={...narrative,tokens:tokens.map((t,i)=>({...t,text:i?'好':'你'}))};
  assert.throws(()=>materializeAligned(cjk,excerpt,media,{...alignment,words:[
    {text:'你好',startFrame:1,endFrameExclusive:29}
  ]}),/alignment/);
});
