/** Render the real TSX component with the existing TypeScript/React dependencies. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const React = require('react');
const {renderToStaticMarkup} = require('react-dom/server');
function load(file) {
  const compiled = ts.transpileModule(fs.readFileSync(path.join(__dirname,file),'utf8'), {
    compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS},
  }).outputText;
  const module = {exports:{}};
  vm.runInNewContext(compiled,{require,exports:module.exports,module});
  return module.exports;
}
const {LiveSuggestion} = load('LiveSuggestion.tsx');
const {initialLiveState, receiveLiveEvent, restoreLiveState} = load('liveState.ts');
const render = item => renderToStaticMarkup(React.createElement(LiveSuggestion,{item}));
test('generated answers show unverified AI provenance, not documentary attribution',()=>{
  const html=render({type:'generated_suggestion',kind:'ai_generated',question:'Explain caching?',
    answer:'<script>untrusted</script>',provider:'ollama',model:'local',source:null});
  assert.match(html,/Sugerencia generada por IA — revisar/);
  assert.match(html,/ollama · local · Sin respaldo documental/);
  assert.match(html,/No verificada/);
  assert.doesNotMatch(html,/Respuesta exacta|Fuente:|<script>/);
  assert.match(html,/&lt;script&gt;/);
});
test('exact and semantic answers retain source-backed labels',()=>{
  for(const match_type of ['exact_qa','semantic_qa']) {
    const html=render({type:'suggestion',question:'Question?',answer:'Stored wording',status:'found',
      match_type,matched_question:'Original?',source:{document_name:'synthetic.md',location:'Line 1'}});
    assert.match(html,/Fuente: synthetic.md/);
    assert.match(html,match_type==='exact_qa'?/Respuesta exacta del documento/:/Posible respuesta semántica — revisar/);
    assert.doesNotMatch(html,/generada por IA|Sin respaldo documental/);
  }
});
test('no evidence remains visible without a fabricated answer',()=>{
  const html=render({type:'suggestion',question:'Question?',status:'no_evidence',answer:null,source:null,match_type:null});
  assert.match(html,/Sin respuesta suficientemente relacionada/);
  assert.doesNotMatch(html,/generada por IA|Fuente:/);
});

test('interim text is replaced in place; finals and answers have separate newest-first bounds',()=>{
  let state=receiveLiveEvent(initialLiveState,{type:'final',text:'Older final'});
  const olderId=state.transcript[0].id;
  state=receiveLiveEvent(state,{type:'partial',text:'First hypothesis'});
  state=receiveLiveEvent(state,{type:'partial',text:'Revised hypothesis'});
  assert.equal(state.partial,'Revised hypothesis');
  assert.equal(state.transcript.length,1);
  state=receiveLiveEvent(state,{type:'final',text:'Newer final'});
  assert.equal(state.partial,'');
  assert.deepEqual(Array.from(state.transcript,x=>x.text),['Newer final','Older final']);
  assert.equal(state.transcript[1].id,olderId);
  state=receiveLiveEvent(state,{type:'suggestion',question:'Unknown?',status:'no_evidence',answer:null,source:null,match_type:null});
  state=receiveLiveEvent(state,{type:'generated_suggestion',question:'Unknown?',answer:'Unverified'});
  for(let i=0;i<100;i++) state=receiveLiveEvent(state,{type:'final',text:`Final ${i}`});
  assert.equal(state.transcript.length,80);
  assert.equal(state.transcript[0].text,'Final 99');
  assert.deepEqual(Array.from(state.suggestions,x=>x.event.type),['generated_suggestion','suggestion']);
  for(let i=0;i<30;i++) state=receiveLiveEvent(state,{type:'suggestion',question:`Question ${i}`,status:'no_evidence'});
  assert.equal(state.suggestions.length,20);
  assert.equal(state.suggestions[0].event.question,'Question 29');
  assert.equal(state.transcript[0].text,'Final 99');
});

test('initial snapshot overlap does not duplicate finals or resurrect an obsolete interim',()=>{
  const old={type:'final',text:'Old'};
  const recent={type:'final',text:'Recent'};
  const state=restoreLiveState([old,recent],[{type:'partial',text:'Obsolete'},recent,{type:'partial',text:'Current'}]);
  assert.deepEqual(Array.from(state.transcript,x=>x.text),['Recent','Old']);
  assert.equal(state.partial,'Current');
  const repeated=receiveLiveEvent(state,recent);
  assert.equal(repeated.transcript.length,3); // Same words can be a legitimate later utterance.
});

test('session presentation follows existing status events and clears interim text on stop/error',()=>{
  let state=receiveLiveEvent(initialLiveState,{type:'status',text:'Confirma la captura en la ventana de audio.'});
  assert.equal(state.phase,'consent');
  assert.equal(state.provider,null);
  state=receiveLiveEvent(state,{type:'status',text:'Comprobando Deepgram Nova-3…'});
  assert.equal(state.phase,'connecting');
  assert.equal(state.provider,'Deepgram Nova-3');
  state=receiveLiveEvent(state,{type:'status',text:'Deepgram Nova-3 listo. Reproduce una frase en Windows.'});
  assert.equal(state.phase,'listening');
  state=receiveLiveEvent(state,{type:'partial',text:'Interim'});
  state=receiveLiveEvent(state,{type:'status',text:'Deteniendo y cancelando transcripción pendiente…'});
  assert.equal(state.phase,'stopping');
  assert.equal(state.partial,'');
  state=receiveLiveEvent(state,{type:'status',text:'Captura y STT detenidos.'});
  state=receiveLiveEvent(state,{type:'partial',text:'Late interim'});
  assert.equal(state.phase,'stopped');
  assert.equal(state.partial,'');
  state=receiveLiveEvent(state,{type:'error',text:'Synthetic failure'});
  assert.equal(state.phase,'error');
  state=receiveLiveEvent(state,{type:'status',text:'Solicitando audio del sistema…'});
  assert.equal(state.phase,'connecting');
  assert.equal(state.provider,null);
  state=receiveLiveEvent(state,{type:'status',text:'Comprobando Faster-Whisper…'});
  assert.equal(state.provider,'Faster-Whisper');
});
