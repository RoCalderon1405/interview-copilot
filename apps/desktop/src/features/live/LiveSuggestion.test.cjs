/** Render the real TSX component with the existing TypeScript/React dependencies. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const React = require('react');
const {renderToStaticMarkup} = require('react-dom/server');
function load(file, imports = {}, globals = {}) {
  const compiled = ts.transpileModule(fs.readFileSync(path.join(__dirname,file),'utf8'), {
    compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS},
  }).outputText;
  const module = {exports:{}};
  vm.runInNewContext(compiled,{require: id => Object.hasOwn(imports,id) ? imports[id] : require(id),
    exports:module.exports,module,window:{},...globals});
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
const {DeepgramSettings}=load('../settings/DeepgramSettings.tsx', {'../../api':{api:{}},'../../i18n':i18n});
const {default:App} = load('../../App.tsx', {'./api':{api:{}},'./features/live/LiveWorkspace':{LiveWorkspace},'./features/settings/DeepgramSettings':{DeepgramSettings},'./i18n':i18n});
const render = item => renderToStaticMarkup(React.createElement(LiveSuggestion,{item}));
test('native Settings event navigates to the existing Deepgram section in EN/ES and unsubscribes',()=>{
  try { for(language of ['es','en']) {
    let cursor=0, mounted=false, callback, focused;
    const slots=[], effects=[],cleanups=[];
    const hooks={...React,useState(initial){const index=cursor++;if(!(index in slots))slots[index]=initial;
      return [slots[index],value=>{slots[index]=typeof value==='function'?value(slots[index]):value;}];},
      useRef(initial){const index=cursor++;return slots[index]??(slots[index]={current:initial});},
      useEffect(effect){if(!mounted)effects.push(effect);}};
    const bridge={onDeepgramSettings:fn=>{callback=fn;return ()=>{callback=null;};},getWindowState:async()=>({mode:'expanded'})};
    const {default:Shell}=load('../../App.tsx',{
      react:hooks,'./api':{api:{health:async()=>{},documents:async()=>({documents:[]})}},
      './features/live/LiveWorkspace':{LiveWorkspace},'./features/settings/DeepgramSettings':{DeepgramSettings},'./i18n':i18n,
    },{window:{copilotDesktop:bridge},requestAnimationFrame:fn=>fn(),
      document:{documentElement:{classList:{toggle(){},remove(){}}},getElementById:id=>({focus:()=>{focused=id;}})}});
    const render=()=>{cursor=0;return renderToStaticMarkup(Shell());};
    render();mounted=true;for(const effect of effects)cleanups.push(effect());
    assert.equal(typeof callback,'function');callback();
    const html=render();
    assert.match(html,/id="deepgram-settings-title" tabindex="-1"/);
    assert.match(html,language==='es'?/Configurar clave/:/Configure key/);
    assert.equal(focused,'deepgram-settings-title');
    for(const cleanup of cleanups)cleanup?.();
    assert.equal(callback,null);
  }}finally{language='es';}
});
test('Deepgram Settings never renders a credential input and explains Windows entry and independent consent in EN/ES',()=>{
  try{
    for(language of ['en','es']){
      const html=renderToStaticMarkup(React.createElement(DeepgramSettings));
      assert.match(html,/Deepgram/);assert.match(html,/Vosk/);
      assert.match(html,language==='en'?/Configure key/:/Configurar clave/);
      assert.match(html,language==='en'?/Never enter your Windows password/:/Nunca introduzcas tu contraseña de Windows/);
      assert.match(html,language==='en'?/not configured|unconfirmed/:/sin confirmar/);
      assert.match(html,language==='en'?/Remote verification: not performed/:/Verificación remota: no realizada/);
      assert.match(html,/COPILOT_DEEPGRAM_API_KEY/);
      assert.doesNotMatch(html,/<input|<textarea|type="password"|localStorage/);
    }
  }finally{language='es';}
});

/** Minimal hook driver for async presentation behavior, not native/Windows acceptance. */
function settingsHarness(manage, status, replayEffect=false) {
  const slots=[];
  let cursor=0, started=false, tree;
  const effects=[];
  const hooks={...React,
    useState(initial){const index=cursor++;if(!(index in slots))slots[index]=initial;
      return [slots[index],value=>{slots[index]=typeof value==='function'?value(slots[index]):value;}];},
    useRef(initial){const index=cursor++;return slots[index]??(slots[index]={current:initial});},
    useEffect(effect){if(!started)effects.push(effect);},
  };
  const {DeepgramSettings:Settings}=load('../settings/DeepgramSettings.tsx',{
    react:hooks,'../../api':{api:{liveStatus:status}},'../../i18n':i18n,
  },{window:{copilotDesktop:{manageDeepgramKey:manage,cancelDeepgramKey:async()=>true}}});
  const render=()=>{cursor=0;tree=Settings();return renderToStaticMarkup(tree);};
  const find=(node,label)=>{
    if(!React.isValidElement(node))return;
    if(node.type==='button' && node.props.children===label)return node;
    for(const child of React.Children.toArray(node.props.children)){const found=find(child,label);if(found)return found;}
  };
  render();started=true;for(const effect of effects){if(replayEffect)effect()();effect();}
  return {html:render,async click(label){render();const button=find(tree,label);assert.ok(button,label);
    assert.notEqual(button.props.disabled,true);await button.props.onClick();await new Promise(setImmediate);return render();},
    async settle(){await new Promise(setImmediate);return render();}};
}

test('credential operations keep localized success when subsequent Windows/backend refresh fails',async()=>{
  try {
    for(language of ['en','es'])for(const action of ['configure','replace','delete']) {
      let stored=action!=='configure',completed=false;
      const harness=settingsHarness(async operation=>{
        if(operation==='status'){
          if(completed)throw new Error('private native detail');
          return {result:'status',stored};
        }
        assert.equal(operation,action);completed=true;stored=operation!=='delete';
        return {result:operation==='delete'?'deleted':'configured',stored};
      },async()=>{if(completed)throw new Error('private backend detail');
        return {providers:{deepgram:{credential_source:'environment'}}};});
      await harness.settle();
      if(action==='delete')await harness.click(language==='en'?'Delete stored key':'Eliminar clave guardada');
      const label=action==='configure'?['Configure key','Configurar clave']:action==='replace'?['Replace key','Reemplazar clave']:['Confirm deletion','Confirmar eliminación'];
      const html=await harness.click(label[language==='en'?0:1]);
      const expected=action==='configure'?['Key saved in Windows.','Clave guardada en Windows.']
        :action==='replace'?['Key replaced in Windows.','Clave reemplazada en Windows.']
        :['Stored key deleted.','Clave guardada eliminada.'];
      assert.ok(html.includes(expected[language==='en'?0:1]));
      assert.match(html,language==='en'?/Windows status could not be refreshed/:/No se pudo actualizar el estado de Windows/);
      assert.match(html,language==='en'?/Backend status unconfirmed/:/Estado del backend sin confirmar/);
      assert.doesNotMatch(html,/private native detail|private backend detail/);
    }
  } finally {language='es';}
});

test('credential outcome messages distinguish cancel, timeout, unknown result and rejected invocation in EN/ES',async()=>{
  try {
    for(language of ['en','es'])for(const outcome of ['cancelled','timed_out','unexpected','throws']) {
      const harness=settingsHarness(async operation=>{
        if(operation==='status')return {result:'status',stored:false};
        if(outcome==='throws')throw new Error('private provider detail');
        return {result:outcome,stored:null};
      },async()=>({providers:{deepgram:{credential_source:'none'}}}));
      await harness.settle();
      const html=await harness.click(language==='en'?'Configure key':'Configurar clave');
      const expected={cancelled:['Operation cancelled.','Operación cancelada.'],
        timed_out:['It may have completed.','La operación puede haberse completado.'],
        unexpected:['Outcome unconfirmed.','Resultado sin confirmar.'],
        throws:['The outcome could not be confirmed.','No se pudo confirmar el resultado.']};
      assert.ok(html.includes(expected[outcome][language==='en'?0:1]));
      assert.doesNotMatch(html,/private provider detail/);
    }
  } finally {language='es';}
});

test('deletion keeps effective environment source explicit and Keep never calls delete',async()=>{
  const actions=[];
  let stored=true;
  const harness=settingsHarness(async operation=>{actions.push(operation);if(operation==='delete')stored=false;
    return {result:operation==='status'?'status':'deleted',stored};
  },async()=>({providers:{deepgram:{credential_source:'environment'}}}));
  await harness.settle();
  await harness.click('Eliminar clave guardada');
  assert.match(await harness.click('Conservar clave'),/Eliminación cancelada/);
  assert.ok(!actions.includes('delete'));
  await harness.click('Eliminar clave guardada');
  const html=await harness.click('Confirmar eliminación');
  assert.match(html,/Clave guardada en Windows: no configurada/);
  assert.match(html,/Tiene prioridad sobre Windows/);
  assert.match(html,/reinicia el backend/);
});

test('development effect replay starts one status request and invalid environment never implies Windows fallback',async()=>{
  let calls=0,complete;
  const pending=new Promise(resolve=>{complete=resolve;});
  const harness=settingsHarness(async()=>{calls++;await pending;return {result:'status',stored:true};},
    async()=>({providers:{deepgram:{configured:false,credential_source:'error',configuration_error:'invalid_environment'}}}),true);
  let html=await harness.settle();
  assert.equal(calls,1);
  assert.match(html,/aria-busy="true"/);
  assert.match(html,/<button[^>]*disabled=""[^>]*>Actualizar disponibilidad/);
  complete();html=await harness.settle();
  assert.match(html,/aria-busy="false"/);
  assert.match(html,/Clave guardada en Windows: configurada/);
  assert.match(html,/no se usa la clave de Windows/);
  assert.match(html,/Verificación remota: no realizada/);
});

test('Settings availability shows loading and visible completion on success, no-change and failure in EN/ES',async()=>{
  try {for(language of ['en','es']) {
    const pending=[];
    const h=settingsHarness(async()=>({result:'status',stored:true}),
      ()=>new Promise((resolve,reject)=>pending.push({resolve,reject})));
    const loading=language==='en'?/Refreshing availability…/:/Actualizando disponibilidad…/;
    const complete=language==='en'?/Status refreshed\./:/Estado actualizado\./;
    const ready=language==='en'?/configured locally.*Remote verification: not performed/:/configurado localmente.*Verificación remota: no realizada/;
    const refresh=language==='en'?'Refresh availability':'Actualizar disponibilidad';
    let html=await h.settle();
    assert.match(html,loading);assert.match(html,/aria-busy="true"/);
    assert.match(html,/class="availability-notice" data-kind="loading" role="status" aria-live="polite" aria-atomic="true"/);
    const result={providers:{deepgram:{available:true,configured:true,runtime_installed:true,credential_source:'windows'}}};
    pending[0].resolve(result);html=await h.settle();
    assert.match(html,complete);assert.match(html,ready);assert.match(html,/aria-busy="false"/);
    assert.match(html,/data-kind="available"/);
    // A second, unchanged response must still replace loading with visible feedback.
    html=await h.click(refresh);assert.match(html,loading);assert.match(html,/aria-busy="true"/);
    assert.equal(pending.length,2);
    pending[1].resolve(result);html=await h.settle();
    assert.match(html,language==='en'?/Availability refreshed\. No changes\./:/Disponibilidad actualizada\. Sin cambios\./);
    assert.match(html,ready);assert.doesNotMatch(html,loading);
    html=await h.click(refresh);assert.match(html,loading);
    pending[2].reject(new Error('private network detail'));html=await h.settle();
    assert.match(html,/data-kind="failure"/);
    assert.match(html,language==='en'?/Availability check failed/:/Error al comprobar la disponibilidad/);
    assert.match(html,language==='en'?/Could not check Deepgram availability.*refresh again/:/No se pudo comprobar la disponibilidad de Deepgram.*vuelve a actualizar/);
    assert.doesNotMatch(html,ready);assert.doesNotMatch(html,/private network detail/);
    assert.match(html,/aria-busy="false"/);
    pending.length=0;
    await h.click(refresh);pending[0].resolve(result);html=await h.settle();
    assert.match(html,complete);assert.match(html,ready);
  }}finally{language='es';}
});

test('availability banners distinguish every local cause with translated visible headings',async()=>{
  const cases=[
    [{configured:false,credential_source:'none'},'missing-credentials','Falta la clave de Deepgram','Deepgram key missing'],
    [{runtime_installed:false},'missing-runtime','Falta una dependencia de Deepgram','Deepgram dependency missing'],
    [{configuration_error:'invalid_environment'},'invalid-configuration','Configuración local inválida','Invalid local configuration'],
    [undefined,'unknown','Disponibilidad sin confirmar','Availability unconfirmed'],
    [{available:true,configured:true},'available','Deepgram configurado localmente','Deepgram configured locally'],
  ];
  try {for(language of ['es','en'])for(const [provider,kind,es,en] of cases){
    const h=settingsHarness(async()=>({result:'status',stored:true}),async()=>({providers:{deepgram:provider}}));
    const html=await h.settle();
    assert.ok(html.includes(`data-kind="${kind}"`));
    assert.ok(html.includes(`<strong>${language==='es'?es:en}</strong>`));
    assert.match(html,/<svg[^>]+aria-hidden="true"[^>]+focusable="false"/);
    assert.match(html,language==='en'?/Refresh availability/:/Actualizar disponibilidad/);
  }}finally{language='es';}
});

test('shared availability palette meets text and icon contrast and provides non-color cues',()=>{
  const css=fs.readFileSync(path.join(__dirname,'../settings/availability-notice.css'),'utf8');
  const luminance=hex=>{
    const rgb=hex.match(/[a-f\d]{2}/gi).map(value=>parseInt(value,16)/255)
      .map(value=>value<=0.04045?value/12.92:((value+0.055)/1.055)**2.4);
    return rgb[0]*0.2126+rgb[1]*0.7152+rgb[2]*0.0722;
  };
  const palettes=[...css.matchAll(/--notice-bg:(#[a-f\d]{6});--notice-text:(#[a-f\d]{6});--notice-border:(#[a-f\d]{6})/g)];
  assert.equal(palettes.length,7);
  for(const [,bg,text,border] of palettes){
    const ratio=(a,b)=>(Math.max(luminance(a),luminance(b))+0.05)/(Math.min(luminance(a),luminance(b))+0.05);
    assert.ok(ratio(bg,text)>=4.5,`${bg}/${text}`);
    assert.ok(ratio(bg,border)>=3,`${bg}/${border}`);
  }
  assert.match(css,/\.availability-notice>svg/);
  assert.match(css,/forced-colors:active/);
});

test('Settings availability distinguishes local causes from unknown results in EN/ES',async()=>{
  const cases=[
    [{configured:false,credential_source:'none'},/No hay una API Key/,/No Deepgram API Key is configured/],
    [{configured:true,runtime_installed:false},/Falta la dependencia websockets/,/dependency websockets is missing/],
    [{configured:false,configuration_error:'invalid_environment'},/Corrígela o elimínala y reinicia el backend; no se usa la clave de Windows/,/Correct or remove it and restart the backend; the Windows key is not used/],
    [{configured:false,configuration_error:'credential_unavailable'},/configuración local.*inválida/,/local configuration.*invalid/],
    [{configured:true,available:false},/Disponibilidad de Deepgram sin confirmar/,/Deepgram availability is unconfirmed/],
    [undefined,/Disponibilidad de Deepgram sin confirmar/,/Deepgram availability is unconfirmed/],
  ];
  try {for(language of ['es','en'])for(const [provider,es,en] of cases) {
    const h=settingsHarness(async()=>({result:'status',stored:true}),async()=>({providers:{deepgram:provider}}));
    const html=await h.settle();
    assert.match(html,language==='es'?es:en);
    assert.match(html,provider ? (language==='es'?/Estado actualizado\./:/Status refreshed\./)
      : (language==='es'?/Estado del backend sin confirmar/:/Backend status unconfirmed/));
    assert.match(html,language==='es'?/Verificación remota: no realizada/:/Remote verification: not performed/);
  }}finally{language='es';}
});

test('availability source changes are not reported as unchanged readiness',async()=>{
  let source='windows';
  const h=settingsHarness(async()=>({result:'status',stored:true}),async()=>({providers:{deepgram:{
    available:true,configured:true,runtime_installed:true,credential_source:source,
  }}}));
  await h.settle();source='environment';
  let html=await h.click('Actualizar disponibilidad');
  assert.match(html,/Tiene prioridad sobre Windows/);
  assert.match(html,/Estado actualizado\./);
  assert.doesNotMatch(html,/Sin cambios/);
  html=await h.click('Actualizar disponibilidad');
  assert.match(html,/Disponibilidad actualizada\. Sin cambios\./);
});

test('availability HTTP checks use a deadline and cache bypass and reject timeouts without leaking details',async()=>{
  const controller=new AbortController();
  const {api}=load('../../api.ts',{}, {
    AbortSignal:{timeout(ms){assert.equal(ms,10000);return controller.signal;}},
    fetch:async(url,options)=>{
      assert.match(url,/\/live\/status$/);assert.equal(options.cache,'no-store');
      assert.equal(options.signal,controller.signal);
      return new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new Error('private timeout detail'))));
    },
  });
  const pending=api.liveStatus();controller.abort();
  await assert.rejects(pending,/No se pudo conectar al backend/);
});

test('save, replacement and deletion automatically recheck availability without clearing operation feedback',async()=>{
  try {for(language of ['en','es'])for(const operation of ['configure','replace','delete']) {
    let stored=operation!=='configure',backendCalls=0,complete;
    const h=settingsHarness(async action=>{
      if(action==='status')return {result:'status',stored};
      assert.equal(action,operation);stored=action!=='delete';
      return {result:stored?'configured':'deleted',stored};
    },()=>{
      if(++backendCalls===1)return Promise.resolve({providers:{deepgram:{configured:stored,available:stored,credential_source:stored?'windows':'none'}}});
      return new Promise(resolve=>{complete=resolve;});
    });
    await h.settle();
    if(operation==='delete')await h.click(language==='en'?'Delete stored key':'Eliminar clave guardada');
    const labels={configure:['Configure key','Configurar clave'],replace:['Replace key','Reemplazar clave'],delete:['Confirm deletion','Confirmar eliminación']};
    let html=await h.click(labels[operation][language==='en'?0:1]);
    assert.equal(backendCalls,2);
    assert.match(html,language==='en'?/Refreshing availability…/:/Actualizando disponibilidad…/);
    const expected=operation==='delete'?(language==='en'?/Stored key deleted\./:/Clave guardada eliminada\./)
      :operation==='replace'?(language==='en'?/Key replaced in Windows\./:/Clave reemplazada en Windows\./)
      :(language==='en'?/Key saved in Windows\./:/Clave guardada en Windows\./);
    assert.match(html,expected);
    complete({providers:{deepgram:{configured:stored,available:stored,runtime_installed:true,credential_source:stored?'windows':'none'}}});
    html=await h.settle();
    assert.match(html,expected);
    assert.match(html,stored?(language==='en'?/configured locally/:/configurado localmente/)
      :(language==='en'?/No Deepgram API Key is configured/:/No hay una API Key/));
    assert.match(html,/aria-busy="false"/);
  }}finally{language='es';}
});
function renderState(view) {
  const {LiveWorkspace:Workspace}=load('LiveWorkspace.tsx',{
    '../../api':{api:{}},'./LiveSuggestion':{LiveSuggestion},'../../i18n':i18n,
    './liveState':{initialLiveState:view,receiveLiveEvent,restoreLiveState},
  });
  return renderToStaticMarkup(React.createElement(Workspace,{showError:()=>{}}));
}
test('generated answers show unverified AI provenance, not documentary attribution',()=>{
  const documentary={type:'suggestion',session_id:'s',question_id:'s:1',question:'Explain caching?',
    status:'no_evidence',answer:null,source:null,match_type:null};
  const generated={type:'generated_suggestion',kind:'ai_generated',session_id:'s',question_id:'s:1',question:documentary.question,
    answer:'<script>untrusted</script>',provider:'ollama',model:'local',source:null};
  const html=renderState(restoreLiveState([documentary,generated],[]));
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

test('each generation failure has a localized reason alongside no_evidence, never an AI answer or source',()=>{
  const item={type:'suggestion',session_id:'s',question_id:'s:1',question:'Original question',
    status:'no_evidence',answer:null,source:null,match_type:null};
  const reasons={
    disabled:['desactivada','disabled'], not_configured:['incompleta o inválida','incomplete or invalid'],
    invalid_input:['no cumple los límites','does not meet'], unavailable:['no está disponible','unavailable'],
    timeout:['agotó el tiempo','timed out'], invalid_response:['formato o seguridad','format or safety'],
    provider_error:['no pudo completar','could not complete'],
  };
  try {
    for(const locale of ['es','en']) {
      language=locale;
      for(const [failure,copy] of Object.entries(reasons)) {
        const html=renderState(restoreLiveState([item,{type:'generation_failed',
          session_id:item.session_id,question_id:item.question_id,code:failure}],[]));
        assert.ok(html.includes(copy[locale==='es'?0:1]));
        assert.match(html,/role="status"/);assert.match(html,/Original question/);
        assert.match(html,locale==='es'?/Sin respuesta suficientemente relacionada/:/No sufficiently related answer/);
        assert.doesNotMatch(html,/Sugerencia generada|AI-generated suggestion|Fuente:|Source:/);
      }
    }
  } finally {language='es';}
});

test('failure updates only its correlated unresolved card; replay and lifecycle remain intact',()=>{
  const documentary={type:'suggestion',question:'Repeated question',status:'no_evidence',answer:null,source:null,
    match_type:null,session_id:'session-1',question_id:'session-1:connection:1'};
  const failure={type:'generation_failed',session_id:documentary.session_id,question_id:documentary.question_id,code:'timeout'};
  const listening=receiveLiveEvent(initialLiveState,{type:'status',text:'Vosk listo. Reproduce una frase en Windows.'});
  const before=receiveLiveEvent(receiveLiveEvent(listening,{type:'partial',text:'Ongoing speech'}),documentary);
  const after=receiveLiveEvent(before,failure);
  assert.equal(after.phase,'listening');assert.equal(after.partial,'Ongoing speech');
  assert.equal(after.suggestions.length,1);assert.equal(after.sequence,before.sequence);
  assert.equal(after.suggestions[0].generationFailure,'timeout');
  assert.deepEqual(JSON.parse(JSON.stringify(after.suggestions[0].event)),documentary);
  assert.equal(restoreLiveState([documentary,failure],[failure]).suggestions[0].generationFailure,'timeout');
  const noFailure=state=>assert.equal(state.suggestions.some(item=>item.generationFailure),false);
  noFailure(receiveLiveEvent(before,{...failure,session_id:'another-session'}));
  noFailure(receiveLiveEvent(before,{...failure,question_id:'session-1:old:1'}));
  const olderFailure=receiveLiveEvent(receiveLiveEvent(before,{...documentary,question_id:'session-1:connection:2'}),failure);
  assert.equal(olderFailure.suggestions[0].generationFailure,undefined);
  assert.equal(olderFailure.suggestions[1].generationFailure,'timeout');
  noFailure(receiveLiveEvent(receiveLiveEvent(listening,{...documentary,status:'found',answer:'Stored',match_type:'exact_qa'}),failure));
  noFailure(receiveLiveEvent(receiveLiveEvent(before,{type:'status',text:'Captura detenida.'}),failure));
  noFailure(receiveLiveEvent(receiveLiveEvent(before,{type:'generated_suggestion',session_id:documentary.session_id,
    question_id:documentary.question_id,question:documentary.question,answer:'Successful answer'}),failure));
});

test('EN/ES presentation changes immediately while source content and canonical Live states stay unchanged',()=>{
  const item={type:'suggestion',question:'Transcripción',answer:'Fuente:',status:'found',match_type:'exact_qa',
    source:{document_name:'Diagnóstico',location:'Pregunta'}};
  const original=JSON.stringify(item);
  language='en';
  try {
    const html=render(item);
    assert.match(html,/Exact answer from document/);
    assert.match(html,/<h3[^>]*>Transcripción<\/h3>/);assert.match(html,/<p>Fuente:<\/p>/);
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

test('workspace uses one answer-first queue and no separate history, without hiding capture controls',()=>{
  const html=renderToStaticMarkup(React.createElement(LiveWorkspace,{showError:()=>{}}));
  assert.ok(html.indexOf('id="live-current-title"') < html.indexOf('id="live-transcript-title"'));
  assert.match(html,/tabindex="0" role="region" aria-label="Cola de preguntas y respuestas"/);
  assert.doesNotMatch(html,/Historial de respuestas|live-suggestions/);
  assert.match(html,/tabindex="0" role="region" aria-label="Historial de transcripción"/);
  const disclosures=html.match(/<details\b[\s\S]*?<\/details>/g);
  assert.equal(disclosures.length,4);
  assert.match(html,/<div class="live-results"><section class="panel live-current live-answer-column"/);
  assert.match(disclosures.find(item=>item.includes('live-diagnostics')),/Diagnóstico[\s\S]*tramas PCM/);
  for(const name of ['live-manual','live-diagnostics']) {
    assert.doesNotMatch(disclosures.find(item=>item.includes(name)),/^<details[^>]*\bopen\b/);
  }
  const compact=renderToStaticMarkup(React.createElement(LiveWorkspace,{showError:()=>{},windowState:{mode:'compact',backgroundOpacity:0.8,available:true,transparencyAvailable:true}}));
  assert.doesNotMatch(compact,/<details[^>]*\bopen\b/);
  assert.match(compact,/Expandir/);assert.match(compact,/Fondo opaco/);
  const essential=html.replace(/<details\b[\s\S]*?<\/details>/g,'');
  assert.match(essential,/Preparar captura/);
  assert.match(essential,/Detener y cerrar/);
  assert.match(html,/Captura toda la salida de Windows/);
  assert.match(html,/no garantiza invisibilidad/);
});

test('transcript stays visible without a toggle in both modes; compact keeps Q&A first in EN/ES',()=>{
  try {
    for(const locale of ['es','en']) {
      language=locale;
      for(const mode of ['expanded','compact']) {
        const html=renderToStaticMarkup(React.createElement(LiveWorkspace,{showError:()=>{},windowState:{mode,available:true}}));
        const transcript=html.match(/<section class="panel live-transcript"[\s\S]*?<\/section>/)[0];
        const feed=transcript.match(/<div id="live-transcript-feed"[^>]*>/)[0];
        assert.match(transcript,new RegExp(locale==='es'?'Transcripción':'Transcript'));
        assert.doesNotMatch(html,/Newest first|Lo más reciente arriba/);
        assert.doesNotMatch(transcript,/<details|<summary/);
        assert.doesNotMatch(transcript,/<button|aria-expanded/);
        assert.doesNotMatch(feed,/\bhidden\b/);
        assert.ok(html.indexOf('live-answer-column')<html.indexOf('panel live-transcript'));
        assert.match(feed,/tabindex="0" role="region"/);
      }
    }
  } finally {language='es';}
});

test('Live appearance is findable in both modes; alpha requires compact/support and opaque recovery remains available',()=>{
  for(const [mode,supported] of [['expanded',true],['compact',true],['compact',false]]) {
    const html=renderToStaticMarkup(React.createElement(LiveWorkspace,{showError:()=>{},windowState:{
      mode,available:true,backgroundOpacity:1,transparencyAvailable:supported,
    }}));
    const appearance=html.match(/<details class="panel live-appearance"[\s\S]*?<\/details>/)[0];
    assert.doesNotMatch(appearance,/<details[^>]*hidden/);
    assert.ok(html.indexOf('live-appearance')<html.indexOf('live-current-title'));
    assert.match(appearance,/<summary>Aspecto del overlay<\/summary>/);
    assert.match(appearance,/<input type="range" min="80" max="100" step="1"/);
    assert.match(appearance,/Opacidad en modo compacto/);
    if(supported)assert.match(appearance,/Para redimensionar, selecciona Fondo opaco/);
    assert.equal(/<input[^>]*disabled/.test(appearance),mode!=='compact'||!supported);
    const opaque=appearance.match(/<button[^>]*>Fondo opaco<\/button>/)[0];
    assert.doesNotMatch(opaque,/disabled/);
    if(mode==='expanded')assert.match(appearance,/Activa Modo compacto/);
  }
});

test('pin renders confirmed native on/off, unknown and pending states with localized text and pressed semantics',()=>{
  try {
    for(const locale of ['es','en']) {
      language=locale;
      for(const confirmed of [true,false,null]) {
        const html=renderToStaticMarkup(React.createElement(LiveWorkspace,{showError:()=>{},
          windowState:{mode:'compact',available:true,alwaysOnTop:true},onTopState:confirmed}));
        const pin=html.match(/<button[^>]*class="btn secondary live-pin"[\s\S]*?<\/button>/)[0];
        assert.match(pin,new RegExp(`data-state="${confirmed===null?'unknown':confirmed?'on':'off'}"`));
        if(confirmed===null)assert.doesNotMatch(pin,/aria-pressed=/);
        else assert.match(pin,new RegExp(`aria-pressed="${confirmed}"`));
        assert.match(pin,new RegExp(locale==='es'?'Siempre visible':'Always on top'));
        const label=confirmed===null?['Sin confirmar','Unconfirmed']:confirmed?['Activado','On']:['Desactivado','Off'];
        assert.ok(pin.includes(`>${label[locale==='es'?0:1]}</strong>`));
      }
      const busy=renderToStaticMarkup(React.createElement(LiveWorkspace,{showError:()=>{},
        windowState:{available:true},onTopState:false,onTopBusy:true}));
      assert.match(busy,/<button[^>]*class="btn secondary live-pin"[^>]*aria-pressed="false"[^>]*aria-busy="true"[^>]*disabled/);
      assert.match(busy,locale==='es'?/Actualizando…/:/Updating…/);
    }
  } finally {language='es';}
});

test('transcript removes visible final badges while preserving interim distinction, final announcements and newest-first content',()=>{
  const view=restoreLiveState([{type:'final',text:'Older synthetic text'},{type:'final',text:'Latest synthetic text'},
    {type:'partial',text:'Changing synthetic words'}],[]);
  const {LiveWorkspace:TranscriptWorkspace}=load('LiveWorkspace.tsx',{
    '../../api':{api:{}},'./LiveSuggestion':{LiveSuggestion},'../../i18n':i18n,
    './liveState':{initialLiveState:view,receiveLiveEvent,restoreLiveState},
  });
  try {
    for(const locale of ['es','en']) {
      language=locale;
      const html=renderToStaticMarkup(React.createElement(TranscriptWorkspace,{showError:()=>{}}));
      assert.match(html,new RegExp(`role="group" aria-label="${locale==='es'?'Transcripción provisional':'Interim transcript'}"`));
      assert.match(html,/class="live-listening-dot" aria-hidden="true"/);
      assert.match(html,locale==='es'?/Escuchando…/:/Listening…/);
      assert.ok(html.indexOf('Changing synthetic words')<html.lastIndexOf('Latest synthetic text'));
      assert.ok(html.lastIndexOf('Latest synthetic text')<html.indexOf('Older synthetic text'));
      const confirmed=locale==='es'?'Transcripción confirmada':'Finalized transcript';
      assert.ok(html.includes(`role="status" aria-atomic="true">${confirmed}: Latest synthetic text`));
      const finals=html.match(/<div class="live-transcript-entry">[\s\S]*?<\/div>/g);
      assert.equal(finals.length,2);
      for(const entry of finals) {
        assert.ok(entry.includes(`<span class="visually-hidden">${confirmed}: </span>`));
        assert.doesNotMatch(entry,/live-entry-label|>Final<|>Finalized</);
      }
    }
  } finally {language='es';}
});

test('question queue upserts by both IDs without reordering, coalesces AI and ignores unrelated events',()=>{
  const qa={type:'suggestion',question:'Same wording',status:'no_evidence',answer:null,source:null,match_type:null,
    session_id:'s',question_id:'s:conn:1'};
  const generated={type:'generated_suggestion',question:qa.question,answer:'Old generated answer',session_id:'s',question_id:qa.question_id};
  let view=receiveLiveEvent(initialLiveState,qa);
  const firstId=view.suggestions[0].id;
  assert.equal(view.suggestions[0].generationState,'unconfirmed');
  view=receiveLiveEvent(view,generated);
  assert.equal(view.suggestions.length,1);
  assert.equal(view.suggestions[0].id,firstId);
  assert.equal(view.suggestions[0].generated.answer,generated.answer);
  assert.equal(view.suggestions[0].generationState,undefined);
  view=receiveLiveEvent(view,{...qa,question_id:'s:conn:2'});
  const secondId=view.suggestions[0].id;
  view=receiveLiveEvent(view,{...generated,answer:'Late completed answer'});
  assert.deepEqual(Array.from(view.suggestions,item=>item.id),[secondId,firstId]);
  assert.equal(view.suggestions[1].generated.answer,'Late completed answer');
  view=receiveLiveEvent(view,{...generated,question_id:'other:conn:2',session_id:'other'});
  assert.equal(view.suggestions.length,2);
  assert.equal(view.suggestions[0].generated,undefined);
  view=receiveLiveEvent(view,{type:'generation_failed',session_id:'s',question_id:'s:conn:2',code:'timeout'});
  assert.equal(view.suggestions[0].generationFailure,'timeout');
  view=receiveLiveEvent(view,{...qa,status:'found',answer:'Documentary',match_type:'exact_qa'});
  assert.deepEqual(Array.from(view.suggestions,item=>item.id),[secondId,firstId]);
  assert.equal(view.suggestions[1].generated,undefined);
  assert.equal(view.suggestions[1].event.answer,'Documentary');
  view=receiveLiveEvent(view,generated);
  assert.equal(view.suggestions[1].generated,undefined);
  view=receiveLiveEvent(view,{...qa,session_id:'another-session'});
  assert.equal(view.suggestions.length,3); // Same question ID/wording alone is not identity.
  assert.equal(restoreLiveState([generated],[]).suggestions.length,0);
});

test('one rendered card contains documentary absence and correlated unverified AI; pending never claims completion',()=>{
  const documentary={type:'suggestion',session_id:'s',question_id:'s:1',question:'Explain cache expiry?',
    status:'no_evidence',answer:null,source:null,match_type:null};
  const ai={type:'generated_suggestion',session_id:'s',question_id:'s:1',question:documentary.question,
    answer:'Synthetic unverified suggestion',provider:'ollama',model:'synthetic',source:null};
  const exact={...documentary,question_id:'s:0',question:'Older question?',status:'found',answer:'Stored answer',
    match_type:'exact_qa',source:{document_name:'synthetic.md',location:'Line 1'}};
  const pending=restoreLiveState([exact,documentary],[]);
  try {
    for(const locale of ['es','en']) {
      language=locale;
      const waiting=renderState(pending);
      assert.match(waiting,locale==='es'?/El inicio de la generación no está confirmado/:/Generation start is unconfirmed/);
      assert.doesNotMatch(waiting,/Synthetic unverified suggestion|Generando|Generating|Completed|Completado/);
      const html=renderState(receiveLiveEvent(pending,ai));
      assert.equal((html.match(/<article\b/g)||[]).length,2);
      assert.equal((html.match(/>Explain cache expiry\?<\/h3>/g)||[]).length,1);
      assert.ok(html.indexOf('Explain cache expiry?')<html.indexOf('Older question?'));
      assert.doesNotMatch(html,/live-suggestions|Historial de respuestas|Answer history/);
      const card=html.match(/<article[^>]*data-question-id="s:1"[\s\S]*?<\/article>/)[0];
      assert.match(card,locale==='es'?/Sin respuesta suficientemente relacionada/:/No sufficiently related answer/);
      assert.match(card,locale==='es'?/Sugerencia generada por IA — revisar/:/AI-generated suggestion — review/);
      assert.match(card,locale==='es'?/No verificada/:/Unverified/);
      assert.doesNotMatch(card,/Fuente:|Source:|Stored answer|Generation start is unconfirmed/);
      assert.match(html,locale==='es'?/Fuente: synthetic.md/:/Source: synthetic.md/);
    }
  } finally {language='es';}
});

test('replacement, stop and restart keep unanswered outcomes explicit and suppress obsolete AI without erasing cards',()=>{
  const qa={type:'suggestion',session_id:'s',question_id:'s:1',question:'Question?',status:'no_evidence',answer:null,source:null,match_type:null};
  const ai={type:'generated_suggestion',session_id:'s',question_id:'s:1',question:qa.question,answer:'Late AI'};
  let view=restoreLiveState([qa,{...qa,question_id:'s:2'}],[]);
  assert.equal(view.suggestions[1].generationState,'replaced');
  assert.equal(view.suggestions[0].generationState,'unconfirmed');
  assert.match(renderState(view),/Pregunta reemplazada/);
  view=receiveLiveEvent(view,{type:'status',text:'Deteniendo y cancelando transcripción pendiente…'});
  assert.ok(view.suggestions.every(item=>item.generationState==='stopped'));
  assert.match(renderState(view),/Detención de captura/);
  view=receiveLiveEvent(view,ai);
  assert.ok(view.suggestions.every(item=>!item.generated));
  view=receiveLiveEvent(view,{type:'status',text:'Solicitando audio del sistema…'});
  view=receiveLiveEvent(view,ai);
  assert.equal(view.suggestions.length,2);
  assert.ok(view.suggestions.every(item=>!item.generated));
  const interrupted=receiveLiveEvent(receiveLiveEvent(initialLiveState,qa),{type:'error',text:'Synthetic disconnection'});
  assert.equal(interrupted.suggestions[0].generationState,'interrupted');
  assert.match(renderState(interrupted),/Sesión interrumpida o reiniciada/);
  assert.equal(receiveLiveEvent(interrupted,ai).suggestions[0].generated,undefined);
  const failure={type:'generation_failed',session_id:'s',question_id:'s:1',code:'timeout'};
  const failed=restoreLiveState([qa,failure,{type:'status',text:'Captura detenida.'}],[]);
  assert.equal(failed.suggestions[0].generationFailure,'timeout');
  const restarted=restoreLiveState([qa,failure,{type:'status',text:'Captura detenida.'},
    {type:'status',text:'Solicitando audio del sistema…'},qa,ai],[]);
  assert.equal(restarted.suggestions[0].generationFailure,'timeout');
  assert.equal(restarted.suggestions[0].generated,undefined);
});

test('queue bounds count questions, not updates; replay upserts once and evicted or uncorrelated results cannot recreate cards',()=>{
  const qa={type:'suggestion',session_id:'s',question_id:'s:1',question:'Same wording',status:'no_evidence',answer:null,source:null,match_type:null};
  const ai={type:'generated_suggestion',session_id:'s',question_id:'s:1',question:qa.question,answer:'AI'};
  const failure={type:'generation_failed',session_id:'s',question_id:'s:1',code:'timeout'};
  let view=restoreLiveState([qa,failure],[failure,qa,ai,qa]);
  assert.equal(view.suggestions.length,1);
  assert.equal(view.suggestions[0].generated.answer,'AI');
  assert.equal(view.suggestions[0].generationFailure,undefined);
  const id=view.suggestions[0].id;
  for(let i=0;i<30;i++)view=receiveLiveEvent(view,ai);
  assert.equal(view.suggestions[0].id,id);
  assert.equal(view.suggestions.length,1);
  for(let i=2;i<24;i++)view=receiveLiveEvent(view,{...qa,question_id:'s:'+i});
  assert.equal(view.suggestions.length,20);
  assert.equal(view.suggestions[0].event.question_id,'s:23');
  view=receiveLiveEvent(receiveLiveEvent(view,ai),failure);
  assert.equal(view.suggestions.length,20);
  assert.ok(view.suggestions.every(item=>item.event.question_id!=='s:1'));
  const legacy={...qa,session_id:undefined,question_id:undefined};
  view=restoreLiveState([legacy,legacy,ai],[]);
  assert.equal(view.suggestions.length,2); // No unsafe text-based identity for legacy events.
  assert.ok(view.suggestions.every(item=>!item.generated));
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
  assert.deepEqual(Array.from(state.suggestions,x=>x.event.type),['suggestion']); // Uncorrelated AI cannot create a question.
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
