/** Render the real TSX component with the existing TypeScript/React dependencies. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const React = require('react');
const {renderToStaticMarkup} = require('react-dom/server');
function load(file, imports = {}) {
  const compiled = ts.transpileModule(fs.readFileSync(path.join(__dirname,file),'utf8'), {
    compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS},
  }).outputText;
  const module = {exports:{}};
  vm.runInNewContext(compiled,{require: id => Object.hasOwn(imports,id) ? imports[id] : require(id),
    exports:module.exports,module,window:{}});
  return module.exports;
}
const translations = {window:{}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../../public/ui-language.js'),'utf8'), translations);
let language = 'es';
const i18n = {useI18n:()=>({language,saved:true,setLanguage(){},t:text=>translations.window.copilotUi.translate(language,text)})};
const {LiveSuggestion} = load('LiveSuggestion.tsx', {'../../i18n':i18n});
const {initialLiveState, receiveLiveEvent, restoreLiveState} = load('liveState.ts');
const {LiveWorkspace} = load('LiveWorkspace.tsx', {
  '../../api': {api:{}}, './LiveSuggestion': {LiveSuggestion},
  '../../i18n':i18n,
  './liveState': {initialLiveState,receiveLiveEvent,restoreLiveState},
});
const {default:App} = load('../../App.tsx', {'./api':{api:{}},'./features/live/LiveWorkspace':{LiveWorkspace},'./i18n':i18n});
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

test('EN/ES presentation changes immediately while source content and canonical Live states stay unchanged',()=>{
  const item={type:'suggestion',question:'Transcripción',answer:'Fuente:',status:'found',match_type:'exact_qa',
    source:{document_name:'Diagnóstico',location:'Pregunta'}};
  const original=JSON.stringify(item);
  language='en';
  try {
    const html=render(item);
    assert.match(html,/Exact answer from document/);
    assert.match(html,/<h3>Transcripción<\/h3>/);assert.match(html,/<p>Fuente:<\/p>/);
    assert.match(html,/Source: Diagnóstico · Pregunta/);
    const workspace=renderToStaticMarkup(React.createElement(LiveWorkspace,{showError:()=>{}}));
    assert.match(workspace,/aria-label="Transcript history"/);assert.match(workspace,/Prepare capture/);
    const shell=renderToStaticMarkup(React.createElement(App));
    assert.match(shell,/Interface language/);assert.match(shell,/Knowledge Base/);
    const state=receiveLiveEvent(initialLiveState,{type:'status',text:'Deepgram Nova-3 listo. Reproduce una frase en Windows.'});
    assert.equal(state.phase,'listening');assert.equal(state.provider,'Deepgram Nova-3');
    assert.equal(translations.window.copilotUi.translate('en',state.status),'Deepgram Nova-3 ready. Play a sentence in Windows.');
    assert.equal(JSON.stringify(item),original);
  } finally {language='es';}
  assert.match(render(item),/Respuesta exacta del documento/);
  const shell=renderToStaticMarkup(React.createElement(App));
  assert.match(shell,/Idioma de interfaz/);assert.match(shell,/Base de conocimiento/);
});

test('locale preference validates persisted values and tolerates denied storage',()=>{
  const {readUiLanguage,saveUiLanguage}=load('../../i18n.tsx');
  for(const value of [null,'fr','en-US','ES',''])assert.equal(readUiLanguage({getItem:()=>value}),'es');
  assert.equal(readUiLanguage({getItem:()=> 'en'}),'en');
  assert.equal(readUiLanguage({getItem(){throw new Error('denied');}}),'es');
  const stored=[];
  assert.equal(saveUiLanguage({setItem:(...args)=>stored.push(args)},'en'),true);
  assert.deepEqual(stored,[['copilot.ui-language','en']]);
  assert.equal(saveUiLanguage({setItem(){throw new Error('quota');}},'es'),false);
});

test('workspace puts answers first in reading order and keeps diagnostics secondary, not capture controls',()=>{
  const html=renderToStaticMarkup(React.createElement(LiveWorkspace,{showError:()=>{}}));
  assert.ok(html.indexOf('id="live-answers-title"') < html.indexOf('id="live-transcript-title"'));
  assert.match(html,/tabindex="0" role="region" aria-label="Historial de respuestas"/);
  assert.match(html,/tabindex="0" role="region" aria-label="Historial de transcripción"/);
  const disclosures=html.match(/<details\b[\s\S]*?<\/details>/g);
  assert.equal(disclosures.length,2);
  assert.ok(disclosures.every(item=>!/^<details[^>]*\bopen\b/.test(item)));
  assert.match(disclosures[1],/Diagnóstico[\s\S]*tramas PCM/);
  const essential=html.replace(/<details\b[\s\S]*?<\/details>/g,'');
  assert.match(essential,/Preparar captura/);
  assert.match(essential,/Detener y cerrar/);
  assert.match(essential,/Captura toda la salida de Windows/);
  assert.match(essential,/no garantiza invisibilidad/);
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
