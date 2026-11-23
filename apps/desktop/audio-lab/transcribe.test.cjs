const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, 'transcribe.js'), 'utf8');

test('compact capture keeps authorization and stop visible while diagnostics and duplicate feeds start collapsed', () => {
  const html = fs.readFileSync(path.join(__dirname, 'transcribe.html'), 'utf8');
  const disclosures = html.match(/<details\b[\s\S]*?<\/details>/g);
  assert.equal(disclosures.length, 2);
  assert.ok(disclosures.every(item => !/^<details[^>]*\bopen\b/.test(item)));
  for (const id of ['info', 'speech-latency', 'semantic-status']) assert.ok(disclosures[0].includes(`id="${id}"`));
  for (const id of ['questions', 'question-hint', 'partial', 'finals']) assert.ok(disclosures[1].includes(`id="${id}"`));
  const essential = html.replace(/<details\b[\s\S]*?<\/details>/g, '');
  for (const id of ['provider', 'language', 'vocabulary-profile', 'consent', 'consent-description', 'start', 'stop', 'status', 'speech-status']) {
    assert.ok(essential.includes(`id="${id}"`), `${id} must not be inside a disclosure`);
    assert.equal(html.split(`id="${id}"`).length - 1, 1);
  }
  assert.match(essential, /toda la salida de Windows/);
  assert.match(essential, /Deepgram envía audio a la nube y puede generar cargos/);
  assert.match(essential, /puede aparecer al compartir pantalla/);
  assert.doesNotMatch(essential, /id="consent"[^>]*\bchecked\b/);
});

function harness({selected = 'vosk', available = true, deferCapture = false, bridge = false, deferWorklet = false,
  deepgram, uiLanguage = 'es', liveStatus, availabilitySignal = () => new AbortController().signal} = {}) {
  const elements = new Map();
  const calls = [];
  const sockets = [];
  const packets = [], worklets = [], contexts = [];
  let now=1, resolveWorklet;
  let resolveCapture;
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      value: id === 'provider' ? selected : id === 'language' ? 'en-US' : id === 'vocabulary-profile' ? 'general' : '',
      disabled: id === 'vocabulary-profile' && selected !== 'deepgram', checked: id === 'consent', textContent: '', style: {}, dataset: {}, handlers: {},
      addEventListener(type, handler) { this.handlers[type] = handler; },
      replaceChildren() {}, appendChild() {},
    });
    return elements.get(id);
  }
  const track = {readyState: 'live', addEventListener() {}, stop() { calls.push('track.stop'); }};
  const node = {connect() {}, disconnect() {}};
  class Context {
    constructor(){contexts.push(this);}
    state = 'running';
    destination = {};
    audioWorklet = {addModule: () => { calls.push('worklet');return deferWorklet ? new Promise(resolve=>{resolveWorklet=resolve;}) : Promise.resolve(); }};
    createMediaStreamSource() { return node; }
    createAnalyser() { return {...node, fftSize: 4, getFloatTimeDomainData() {}}; }
    createGain() { return {...node, gain: {value: 0}}; }
    async resume() {}
    async close() {}
  }
  class Socket {
    static OPEN = 1;
    readyState = 1;
    bufferedAmount = 0;
    sent = [];
    constructor() { sockets.push(this); }
    send(data) { this.sent.push(data); }
    close() { calls.push('socket.close'); }
  }
  const statuses = {languages: {'en-US': {available}}, providers: {
    vosk: {languages: {'en-US': {available}}},
    'faster-whisper': {languages: {'en-US': {available}}},
    deepgram: deepgram ?? {languages: {'en-US': {available}}},
  }};
  const translationContext = {window:{}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../public/ui-language.js'),'utf8'), translationContext);
  const context = {
    document: {getElementById: element, createElement: () => element('created'),createTextNode:text=>({textContent:text})},
    window: {addEventListener() {}, copilotCaptureUi:{
      set:(element,text)=>{element.textContent=translationContext.window.copilotUi.translate(uiLanguage,text);},
      content:(element,text)=>{element.textContent=text;},
    }, ...(bridge ? {copilotCapture:{publish:packet=>packets.push(packet),hideControls:async()=>true,
      openDeepgramSettings:async()=>{calls.push('open-settings');return true;}}} : {})},
    navigator: {mediaDevices: {getDisplayMedia(options) {
      calls.push(['capture', options]);
      const captured = {getAudioTracks: () => [track], getTracks: () => [track]};
      return deferCapture ? new Promise(resolve => { resolveCapture = () => resolve(captured); }) : Promise.resolve(captured);
    }}},
    fetch: async (url, options) => {
      calls.push(['fetch', url, options?.body && JSON.parse(options.body)]);
      if (url.endsWith('/live/status') && liveStatus) return liveStatus(options);
      const payload = url.endsWith('/live/status') ? statuses
        : url.endsWith('/live-token') ? {token: 'synthetic-token'} : {id: 'synthetic-session'};
      return {ok: true, json: async () => payload};
    },
    AbortSignal: {timeout(ms){assert.equal(ms,10000);return availabilitySignal();}},
    AudioContext: Context, MediaStream: class {}, WebSocket: Socket,
    AudioWorkletNode: class {constructor(){worklets.push(this);}port = {}; connect() {} disconnect() {}},
    requestAnimationFrame: () => 1, cancelAnimationFrame() {},
    setTimeout: () => 1, clearTimeout() {}, performance: {now: () => now},
  };
  vm.runInNewContext(script, context);
  return {element, calls, sockets, packets, worklets, contexts, statuses, advance:ms=>{now+=ms;},resolveWorklet:()=>resolveWorklet(), resolveCapture: () => resolveCapture()};
}

test('Deepgram unavailable causes and start failures are actionable in EN/ES without remote validation claims', async () => {
  const cases = [
    [{configured:false,credential_source:'none',runtime_installed:true}, /No hay una API Key/, /No Deepgram API Key is configured/],
    [{configured:true,credential_source:'windows',runtime_installed:false}, /Falta la dependencia websockets/, /dependency websockets is missing/],
    [{configured:false,credential_source:'error',configuration_error:'invalid_environment'}, /prioridad.*Windows.*Corrige o elimina.*reinicia el backend/, /overrides the Windows key.*Correct or remove.*restart the backend/],
    [{configured:false,credential_source:'error',configuration_error:'credential_unavailable'}, /no puede leer.*no se ha confirmado/, /cannot read.*no remote authentication failure/],
    [{configured:false,configuration_error:'unknown_configuration_error'}, /configuración local.*inválida/, /local configuration.*invalid/],
    [{configured:true,credential_source:'windows',runtime_installed:true}, /Disponibilidad.*sin confirmar.*No se ha confirmado/, /availability is unconfirmed.*No remote authentication failure/],
    [undefined, /Disponibilidad.*sin confirmar/, /availability is unconfirmed/],
  ];
  for (const uiLanguage of ['es','en']) for (const [state, es, en] of cases) {
    const h=harness({selected:'deepgram',available:false,deepgram:state,uiLanguage,bridge:true});
    await new Promise(setImmediate);
    const expected=uiLanguage==='es'?es:en;
    assert.match(h.element('speech-status').textContent,expected);
    const kind=state?.runtime_installed===false?'missing-runtime'
      :state?.configuration_error || state?.credential_source==='error'?'invalid-configuration'
      :state?.credential_source==='none'?'missing-credentials':'unknown';
    assert.equal(h.element('availability-notice').dataset.kind,kind);
    assert.ok(h.element('speech-status-title').textContent);
    assert.equal(h.element('open-settings').hidden,false);
    await h.element('start').handlers.click();
    assert.match(h.element('status').textContent,expected);
    assert.equal(h.sockets.length,0);
    assert.ok(h.calls.includes('track.stop'));
    assert.equal(h.element('provider').value,'deepgram');
    assert.equal(h.calls.some(call=>call[0]==='fetch' && call[1].endsWith('/live-token')),false);
  }
});

test('availability deadline ends loading with localized failure and allows retry without granting consent', async () => {
  for (const uiLanguage of ['en','es']) {
    const controller=new AbortController();
    let first=true;
    const h=harness({selected:'deepgram',uiLanguage,availabilitySignal:()=>controller.signal,
      liveStatus:options=>{
        if(!first)return Promise.resolve({ok:true,json:async()=>({providers:{deepgram:{configured:false,credential_source:'none'}}})});
        first=false;
        return new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new Error('private timeout detail'))));
      }});
    assert.equal(h.element('refresh-provider').disabled,true);
    controller.abort();await new Promise(setImmediate);
    assert.equal(h.element('availability-notice').dataset.kind,'failure');
    assert.match(h.element('speech-status').textContent,uiLanguage==='en'?/Could not check the engine/:/No se pudo consultar/);
    assert.equal(h.element('refresh-provider').disabled,false);
    await h.element('refresh-provider').handlers.click();
    assert.match(h.element('speech-status').textContent,uiLanguage==='en'?/No Deepgram API Key/:/No hay una API Key/);
    assert.equal(h.sockets.length,0);
    assert.ok(!h.calls.some(call=>Array.isArray(call) && call[0]==='capture'));
  }
});

test('refresh picks up a Windows key without restarting, capturing, changing provider or granting consent', async () => {
  for(const uiLanguage of ['es','en']) {
    const h=harness({selected:'deepgram',available:false,bridge:true,uiLanguage,
      deepgram:{configured:false,credential_source:'none',runtime_installed:true}});
    await new Promise(setImmediate);
    h.element('consent').checked=false;
    await h.element('open-settings').handlers.click();
    assert.ok(h.calls.includes('open-settings'));
    h.statuses.providers.deepgram={configured:true,credential_source:'windows',runtime_installed:true,
      languages:{'en-US':{available:true}}};
    await h.element('refresh-provider').handlers.click();
    assert.match(h.element('speech-status').textContent,uiLanguage==='es'?/configurado localmente.*no realizada/:/configured locally.*not performed/);
    assert.equal(h.element('consent').checked,false);
    assert.equal(h.element('provider').value,'deepgram');
    assert.equal(h.calls.some(call=>call[0]==='capture'),false);
    assert.equal(h.element('refresh-provider').disabled,false);
  }
});

test('generic backend speech_error never becomes a confirmed remote authentication failure', async () => {
  for(const uiLanguage of ['es','en']) {
    const h=harness({selected:'deepgram',bridge:true,uiLanguage});
    await h.element('start').handlers.click();
    assert.equal(h.element('open-settings').disabled,true);
    h.sockets[0].onmessage({data:JSON.stringify({type:'error',code:'speech_error',message:'Selected speech recognition could not start'})});
    await new Promise(setImmediate);
    assert.match(h.element('status').textContent,uiLanguage==='es'?/causa remota no está confirmada.*no demuestra que la API Key sea inválida/:/remote cause is unconfirmed.*does not prove the API Key is invalid/);
    assert.equal(h.element('open-settings').disabled,false);
    assert.ok(h.calls.includes('track.stop'));
  }
});

test('speech_unavailable rechecks the existing backend status for the current cause', async () => {
  const h=harness({selected:'deepgram',bridge:true});
  await h.element('start').handlers.click();
  h.statuses.providers.deepgram={configured:false,credential_source:'error',configuration_error:'invalid_environment'};
  h.sockets[0].onmessage({data:JSON.stringify({type:'error',code:'speech_unavailable'})});
  await new Promise(setImmediate);
  assert.match(h.element('speech-status').textContent,/COPILOT_DEEPGRAM_API_KEY.*Corrige o elimina/);
  assert.equal(h.element('open-settings').disabled,false);
  assert.ok(h.calls.includes('track.stop'));
});

test('Settings navigation failures are localized and retryable without starting capture', async () => {
  for (const uiLanguage of ['es','en']) {
    const h=harness({selected:'deepgram',uiLanguage});
    await h.element('open-settings').handlers.click();
    assert.match(h.element('speech-status').textContent,uiLanguage==='es'?/No se pudo abrir configuración/:/Could not open Settings/);
    assert.equal(h.element('open-settings').disabled,false);
    assert.equal(h.calls.some(call=>call[0]==='capture'),false);
  }
});

test('late availability responses cannot overwrite the selected provider or a newer refresh', async () => {
  const pending=[];
  const h=harness({selected:'deepgram',liveStatus:()=>new Promise(resolve=>pending.push(resolve))});
  h.element('provider').value='vosk';
  h.element('provider').handlers.change();
  pending[1]({ok:true,json:async()=>({providers:{vosk:{languages:{'en-US':{available:true}}}}})});
  await new Promise(setImmediate);
  pending[0]({ok:true,json:async()=>({providers:{deepgram:{configured:false,credential_source:'none'}}})});
  await new Promise(setImmediate);
  assert.match(h.element('speech-status').textContent,/Vosk disponible/);
  assert.equal(h.element('open-settings').hidden,true);
});

test('availability refresh failure is recoverable and Settings stays hidden in standalone lab', async () => {
  let failed=true;
  const h=harness({selected:'deepgram',liveStatus:async()=>{if(failed)throw new Error('private detail');return {ok:true,json:async()=>({})};}});
  await new Promise(setImmediate);
  assert.match(h.element('speech-status').textContent,/Verifica el backend/);
  assert.equal(h.element('refresh-provider').disabled,false);
  assert.equal(h.element('open-settings').hidden,true);
  failed=false;
  await h.element('refresh-provider').handlers.click();
  assert.match(h.element('speech-status').textContent,/Disponibilidad.*sin confirmar/);
});

test('capture availability refresh shows loading then visible success, no-change and failure in EN/ES',async()=>{
  for(const uiLanguage of ['es','en']) {
    const pending=[];
    const h=harness({selected:'deepgram',uiLanguage,
      liveStatus:()=>new Promise((resolve,reject)=>pending.push({resolve,reject}))});
    const loading=uiLanguage==='es'?/Actualizando disponibilidad…/:/Refreshing availability…/;
    const ready=uiLanguage==='es'?/configurado localmente.*no realizada/:/configured locally.*not performed/;
    assert.match(h.element('speech-status').textContent,loading);
    assert.equal(h.element('availability-notice').dataset.kind,'loading');
    assert.equal(h.element('refresh-provider').disabled,true);
    const response={ok:true,json:async()=>({providers:{deepgram:{configured:true,runtime_installed:true,languages:{'en-US':{available:true}}}}})};
    pending[0].resolve(response);await new Promise(setImmediate);
    assert.match(h.element('speech-status').textContent,ready);
    assert.equal(h.element('availability-notice').dataset.kind,'available');
    assert.equal(h.element('refresh-provider').disabled,false);
    const unchanged=h.element('refresh-provider').handlers.click();
    assert.match(h.element('speech-status').textContent,loading);
    pending[1].resolve(response);await unchanged;
    assert.match(h.element('speech-status').textContent,ready);
    assert.equal(h.element('refresh-provider').disabled,false);
    const failed=h.element('refresh-provider').handlers.click();
    assert.match(h.element('speech-status').textContent,loading);
    pending[2].resolve({ok:false});await failed;
    assert.equal(h.element('availability-notice').dataset.kind,'failure');
    assert.match(h.element('speech-status').textContent,uiLanguage==='es'?/No se pudo consultar el motor/:/Could not check the engine/);
    assert.equal(h.element('refresh-provider').disabled,false);
    assert.equal(h.calls.some(call=>call[0]==='capture'),false);
  }
});

test('Vosk remains the HTML default and capture stays directly in the click', async () => {
  const html = fs.readFileSync(path.join(__dirname, 'transcribe.html'), 'utf8');
  assert.match(html, /value="vosk" selected/);
  const h = harness();
  const pending = h.element('start').handlers.click();
  assert.equal(h.calls.filter(call => call[0] === 'capture').length, 1);
  assert.equal(h.element('provider').disabled, true);
  assert.equal(h.element('language').disabled, true);
  await pending;
  const grant = h.calls.find(call => call[0] === 'fetch' && call[1].endsWith('/live-token'));
  assert.deepEqual(grant[2], {language: 'en-US', provider: 'vosk', consent: true, vocabulary_profile: 'general'});
});

test('Whisper provider is bound in token/start, verified on ready, and reset on stop', async () => {
  const h = harness({selected: 'faster-whisper'});
  await h.element('start').handlers.click();
  const socket = h.sockets[0];
  socket.onopen();
  assert.deepEqual(JSON.parse(socket.sent[0]), {
    type: 'start', token: 'synthetic-token', provider: 'faster-whisper', language: 'en-US',
  });
  socket.onmessage({data: JSON.stringify({type: 'ready', provider: 'faster-whisper', language: 'en-US',
    sample_rate: 16000, sample_format: 'pcm_s16le', channels: 1})});
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(h.calls.includes('worklet'));
  h.element('stop').handlers.click();
  assert.equal(socket.sent.at(-1), 'stop');
  const onclose = socket.onclose;
  onclose({code: 1000});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.element('provider').disabled, false);
  assert.equal(h.element('language').disabled, false);
});

test('unavailable selection stops tracks with a clear error, never silently switches provider', async () => {
  const h = harness({selected: 'faster-whisper', available: false});
  await h.element('start').handlers.click();
  assert.equal(h.sockets.length, 0);
  assert.ok(h.calls.includes('track.stop'));
  assert.match(h.element('status').textContent, /Faster-Whisper.*no está disponible/);
  assert.equal(h.element('provider').value, 'faster-whisper');
});

test('ready with a mismatched provider never starts PCM', async () => {
  const h = harness({selected: 'faster-whisper'});
  await h.element('start').handlers.click();
  h.sockets[0].onmessage({data: JSON.stringify({type: 'ready', provider: 'vosk', language: 'en-US'})});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.calls.includes('worklet'), false);
  assert.ok(h.calls.includes('track.stop'));
  assert.match(h.element('status').textContent, /autorizado es diferente/);
});

test('stop while the capture prompt is pending closes late tracks without opening a session', async () => {
  const h = harness({deferCapture: true});
  const pending = h.element('start').handlers.click();
  h.element('stop').handlers.click();
  h.resolveCapture();
  await pending;
  assert.ok(h.calls.includes('track.stop'));
  assert.equal(h.sockets.length, 0);
  assert.equal(h.calls.some(call => call[0] === 'fetch' && call[1].endsWith('/live-token')), false);
  assert.equal(h.element('provider').disabled, false);
});


test('Deepgram requires renewed cloud consent and binds provider in the authorized session', async () => {
  const html = fs.readFileSync(path.join(__dirname, 'transcribe.html'), 'utf8');
  assert.match(html, /value="deepgram"/);
  const h = harness({selected: 'vosk'});
  h.element('provider').value = 'deepgram';
  h.element('provider').handlers.change();
  assert.equal(h.element('consent').checked, false);
  assert.equal(h.element('start').disabled, true);
  assert.match(h.element('consent-description').textContent, /Deepgram.*nube/);
  assert.equal(h.element('vocabulary-profile').disabled, false);
  h.element('vocabulary-profile').value = 'ai-engineer';
  h.element('consent').checked = true;
  h.element('consent').handlers.change();
  await h.element('start').handlers.click();
  const grant = h.calls.find(call => call[0] === 'fetch' && call[1].endsWith('/live-token'));
  assert.deepEqual(grant[2], {language: 'en-US', provider: 'deepgram', consent: true, vocabulary_profile: 'ai-engineer'});
  const socket = h.sockets[0];
  socket.onopen();
  assert.deepEqual(JSON.parse(socket.sent[0]), {
    type: 'start', token: 'synthetic-token', provider: 'deepgram', language: 'en-US',
  });
  socket.onmessage({data: JSON.stringify({type: 'ready', provider: 'deepgram', language: 'en-US',
    sample_rate: 16000, sample_format: 'pcm_s16le', channels: 1})});
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(h.calls.includes('worklet'));
  socket.onmessage({data: JSON.stringify({type: 'partial', text: 'Could you explain', language: 'en-US'})});
  assert.equal(h.element('partial').textContent, 'Could you explain');
  socket.onmessage({data: JSON.stringify({type: 'final', text: 'Could you explain authentication?', language: 'en-US'})});
  assert.equal(h.element('partial').textContent, 'Escuchando…');
});


test('Vocabulary profile is visible only for Deepgram and cannot change mid-session', async () => {
  const html = fs.readFileSync(path.join(__dirname, 'transcribe.html'), 'utf8');
  assert.match(html, /value="data-analyst"/);
  assert.match(html, /value="ai-engineer"/);
  const h = harness({selected: 'vosk'});
  assert.equal(h.element('vocabulary-profile').disabled, true);
  h.element('provider').value = 'deepgram';
  h.element('provider').handlers.change();
  assert.equal(h.element('vocabulary-profile').disabled, false);
  h.element('consent').checked = true;
  await h.element('start').handlers.click();
  assert.equal(h.element('vocabulary-profile').disabled, true);
  h.element('stop').handlers.click();
  h.sockets[0].onclose({code: 1000});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.element('vocabulary-profile').disabled, false);
});

test('capture readiness waits for the worklet; PCM heartbeat is independent of animation frames', async () => {
  const h=harness({bridge:true,deferWorklet:true});
  await h.element('start').handlers.click();
  const phases=()=>h.packets.filter(p=>p.type==='capture_state').map(p=>p.phase);
  assert.deepEqual(phases(),['connecting']);
  h.sockets[0].onmessage({data:JSON.stringify({type:'ready',provider:'vosk',language:'en-US',sample_rate:16000,sample_format:'pcm_s16le',channels:1})});
  assert.deepEqual(phases(),['connecting']);
  h.resolveWorklet();await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(phases(),['connecting','active']);
  assert.equal(h.element('hide-controls').disabled,false);
  h.advance(1100);h.worklets[0].port.onmessage({data:new ArrayBuffer(3200)});
  assert.equal(h.packets.find(p=>p.type==='metrics').frames,1);
  h.contexts[0].state='suspended';h.contexts[0].onstatechange();
  assert.equal(h.packets.at(-1).type,'capture_attention');
  h.element('stop').handlers.click();
  h.sockets[0].onclose({code:1000});await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(phases(),['connecting','active','stopping','stopped']);
  const count=h.sockets[0].sent.length;
  h.worklets[0].port.onmessage({data:new ArrayBuffer(3200)});
  assert.equal(h.sockets[0].sent.length,count); // obsolete worklet cannot resume audio
  const late=harness({bridge:true,deferWorklet:true});
  await late.element('start').handlers.click();
  late.sockets[0].onmessage({data:JSON.stringify({type:'ready',provider:'vosk',language:'en-US',sample_rate:16000,sample_format:'pcm_s16le',channels:1})});
  late.element('stop').handlers.click();late.resolveWorklet();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(late.packets.some(p=>p.type==='capture_state' && p.phase==='active'),false);
});

test('capture localization updates authored copy without translating incoming content', async () => {
  let changeLanguage;
  const staticNode={textContent:'Idioma de transcripción',isConnected:true,parentElement:{tagName:'LABEL'}};
  const settingsNode={textContent:'Abrir configuración',isConnected:true,parentElement:{tagName:'BUTTON'}};
  const refreshNode={textContent:'Actualizar disponibilidad',isConnected:true,parentElement:{tagName:'BUTTON'}};
  const staticNodes=[staticNode,settingsNode,refreshNode];
  const status={dataset:{},textContent:''}, partial={dataset:{},textContent:''}, answer={dataset:{},textContent:'Fuente:'};
  const nodes=[status,partial,answer];
  const window={copilotCapture:{onUiLanguage:fn=>{changeLanguage=fn;return ()=>{};},getUiLanguage:async()=> 'es'},addEventListener(){}};
  const document={body:{},documentElement:{},createTreeWalker:()=>({index:0,nextNode(){this.currentNode=staticNodes[this.index++];return Boolean(this.currentNode);}}),
    querySelectorAll:selector=>selector==='[data-ui-copy]'?nodes.filter(n=>n.dataset.uiCopy!==undefined):[]};
  const context={window,document,NodeFilter:{SHOW_TEXT:4}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../public/ui-language.js'),'utf8'),context);
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../public/audio-lab/capture-ui.js'),'utf8'),context);
  await new Promise(resolve=>setImmediate(resolve));
  window.copilotCaptureUi.set(status,'Conectando con Deepgram Nova-3…');
  window.copilotCaptureUi.set(partial,'Esperando voz…');
  window.copilotCaptureUi.content(partial,'Escuchando…'); // spoken text identical to a UI label
  changeLanguage('en');
  assert.equal(staticNode.textContent,'Transcription language');
  assert.equal(settingsNode.textContent,'Open Settings');
  assert.equal(refreshNode.textContent,'Refresh availability');
  assert.equal(status.textContent,'Connecting to Deepgram Nova-3…');
  assert.equal(partial.textContent,'Escuchando…');assert.equal(answer.textContent,'Fuente:');
  assert.equal(document.documentElement.lang,'en');
  changeLanguage('es');assert.equal(status.textContent,'Conectando con Deepgram Nova-3…');
  assert.equal(settingsNode.textContent,'Abrir configuración');
  assert.equal(refreshNode.textContent,'Actualizar disponibilidad');
  assert.equal(window.copilotUi.translate('en','FALLO: Windows no devolvió ninguna pista de audio'),'FAILURE: Windows did not return an audio track');
});

test('generation failure relay preserves PCM and drops stopped or replaced socket results',async()=>{
  const h=harness({bridge:true});
  await h.element('start').handlers.click();
  const receive=h.sockets[0].onmessage;
  receive({data:JSON.stringify({type:'ready',provider:'vosk',language:'en-US',sample_rate:16000,sample_format:'pcm_s16le',channels:1})});
  await new Promise(resolve=>setImmediate(resolve));
  const failure={type:'generation_failed',session_id:'session-1',question_id:'session-1:conn:1',code:'timeout'};
  receive({data:JSON.stringify(failure)});
  assert.deepEqual(JSON.parse(JSON.stringify(h.packets.at(-1))),failure);
  assert.equal(h.calls.includes('track.stop'),false);assert.equal(h.calls.includes('socket.close'),false);
  const sent=h.sockets[0].sent.length;
  h.worklets[0].port.onmessage({data:new ArrayBuffer(3200)});
  assert.equal(h.sockets[0].sent.length,sent+1);
  h.element('stop').handlers.click();receive({data:JSON.stringify(failure)});
  assert.equal(h.packets.filter(packet=>packet.type==='generation_failed').length,1);
  h.sockets[0].onclose({code:1000});await new Promise(resolve=>setImmediate(resolve));
  await h.element('start').handlers.click();receive({data:JSON.stringify(failure)});
  assert.equal(h.packets.filter(packet=>packet.type==='generation_failed').length,1);
});
