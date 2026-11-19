/** Native shell contract tests; no real Windows media/audio is asserted. */
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { EventEmitter } = require('node:events');
const { pathToFileURL } = require('node:url');
const DEV = 'http://127.0.0.1:5173';
const DIST = pathToFileURL(path.join(__dirname, '../dist/index.html')).href;
function boot({packaged=false, platform='win32', trayFails=false, opaqueWindow=false, transparentFails=false,
  backgroundFails=false, captureAllowed=true, workArea={x:0,y:0,width:1920,height:1080}}={}) {
  const handles = new Map();
  const listeners = new Map();
  const windows=[];
  const trays=[];
  const timers=new Set();
  let now=0;
  const credentialCalls=[];
  const credentials={busy:false,run:async(action,_win,language)=>{credentialCalls.push({action,language});return {result:'status',stored:false};},cancel:()=>credentialCalls.push({action:'cancel'})};
  class Contents extends EventEmitter {
    constructor(){super();this.mainFrame={url:''};this.sent=[];this.session={setPermissionCheckHandler:fn=>{this.check=fn;},setPermissionRequestHandler:fn=>{this.request=fn;},setDisplayMediaRequestHandler:fn=>{this.display=fn;}};this.destroyed=false;}
    isDestroyed(){return this.destroyed;}
    send(channel,data){this.sent.push({channel,data});}
    setWindowOpenHandler(fn){this.windowOpen=fn;}
    navigate(url){let denied=false;this.emit('will-navigate',{preventDefault:()=>denied=true},url);return denied;}
  }
  class Window extends EventEmitter {
    constructor(options){super();if(options.transparent && transparentFails)throw new Error('transparent unavailable');this.options=options;this.webContents=new Contents();this.protected=false;this.top=false;this.destroyed=false;this.bounds={x:100,y:100,width:options.width,height:options.height};windows.push(this);}
    loadURL(url){this.webContents.mainFrame.url=url;return Promise.resolve();}
    loadFile(file){this.webContents.mainFrame.url=pathToFileURL(file).href;return Promise.resolve();}
    setContentProtection(v){this.protected=v;}
    isContentProtected(){return this.protected;}
    setAlwaysOnTop(v){this.top=v;}
    isAlwaysOnTop(){return this.top;}
    isDestroyed(){return this.destroyed;}
    show(){this.visible=true;}
    focus(){}
    showInactive(){this.visible=true;}
    hide(){this.visible=false;}
    isMinimized(){return Boolean(this.minimized);}
    minimize(){this.minimized=true;}
    restore(){this.minimized=false;}
    getNormalBounds(){return {...this.bounds};}
    setBounds(bounds){this.bounds={...bounds};}
    setMinimumSize(width,height){this.minimum=[width,height];}
    isMaximized(){return Boolean(this.maximized);}
    maximize(){this.maximized=true;}
    unmaximize(){this.maximized=false;}
    setResizable(value){this.resizable=value;}
    setBackgroundColor(value){if(backgroundFails && value==='#00000000')throw new Error('alpha failed');this.background=value;}
    setSkipTaskbar(value){this.skipTaskbar=value;}
    close(){this.emit('close');this.destroyed=true;this.emit('closed');}
    static getAllWindows(){return windows;}
  }
  class RecoveryTray extends EventEmitter {
    constructor(){super();if(trayFails)throw new Error('tray unavailable');trays.push(this);}
    setToolTip(value){this.tooltip=value;}
    setContextMenu(value){this.menu=value;}
    destroy(){this.destroyed=true;}
  }
  const electron={app:{isPackaged:packaged,whenReady:()=>Promise.resolve(),on(){},quit(){}},BrowserWindow:Window,screen:{getDisplayMatching:()=>({workArea})},Tray:RecoveryTray,Menu:{buildFromTemplate:items=>items},nativeImage:{createFromBitmap:()=>({isEmpty:()=>false})},desktopCapturer:{getSources:async()=>[{id:'screen:1:0'}]},ipcMain:{handle:(name,fn)=>handles.set(name,fn),on:(name,fn)=>listeners.set(name,fn)}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'main.cjs'),'utf8'),{__dirname,URL,Buffer,Date:{now:()=>now},setInterval:fn=>{timers.add(fn);return {fn,unref(){}};},clearInterval:timer=>timers.delete(timer.fn),process:{platform,env:opaqueWindow?{COPILOT_OPAQUE_WINDOW:'1'}:{}},require:id=>id==='electron'?electron:id==='./credentials.cjs'?{createCredentials:()=>credentials,captureGuard:()=>async()=>captureAllowed}:require(id)}, {filename:'main.cjs'});
  return new Promise(resolve=>setImmediate(()=>resolve({handles,listeners,windows,trays,timers,credentials,credentialCalls,window:windows[0],advance:ms=>{now+=ms;for(const fn of timers)fn();}})));
}
const e=win=>({sender:win.webContents,senderFrame:win.webContents.mainFrame});
const invoke=(h,name,...args)=>h.handles.get('copilot:'+name)(e(h.window),...args);
test('default native shell denies media in renderer and protects screen on Windows',async()=>{
 const h=await boot();assert.equal(invoke(h,'window-state').available,true);
 assert.equal(h.window.protected,true);
 assert.equal(h.window.webContents.check(),false);
 h.window.webContents.request(null,'media',ok=>assert.equal(ok,false));
 h.window.webContents.display({},result=>assert.deepEqual(JSON.stringify(result),'{}'));
});
test('sandboxed window and IPC setters',async()=>{
 const h=await boot();let p=h.window.options.webPreferences;
 assert.equal(p.contextIsolation,true);assert.equal(p.sandbox,true);assert.equal(p.nodeIntegration,false);assert.equal(p.webSecurity,true);
 assert.equal(invoke(h,'set-protection',false),false);
 assert.equal(invoke(h,'set-on-top',true),true);
 for(const invalid of [1,'yes',undefined]) assert.equal(invoke(h,'set-on-top',invalid),false);
});
test('reject untrusted IPC, popup and navigation',async()=>{
 const h=await boot();let c=h.window.webContents;
 assert.equal(c.windowOpen().action,'deny');
 assert.equal(c.navigate('https://evil.example'),true);
 assert.equal(c.navigate(DEV+'/app'),false);
 c.mainFrame.url='blob:'+DEV+'/unsafe';
 assert.throws(()=>invoke(h,'window-state'),/Untrusted IPC/);
 c.mainFrame.url=DEV;
 assert.throws(()=>h.handles.get('copilot:window-state')({sender:{},senderFrame:c.mainFrame}),/Untrusted IPC/);
});
test('production allows only packaged entry URL',async()=>{
 const h=await boot({packaged:true});
 assert.equal(h.window.webContents.mainFrame.url,DIST);
 assert.equal(h.window.webContents.navigate(DIST+'#/settings'),false);
 assert.equal(h.window.webContents.navigate('file:///unsafe.html'),true);
});
test('Linux does not enable Windows capture protection automatically',async()=>{
 const h=await boot({platform:'linux'});
 assert.equal(h.window.protected,false);
});

test('Live layouts restore per-mode geometry without replacing windows, capture, protection or pin state',async()=>{
  const h=await boot();invoke(h,'live-open');const c=h.windows[1];
  const publish=h.listeners.get('copilot:live-packet');
  publish(e(c),{type:'capture_state',attempt:1,phase:'connecting'});
  publish(e(c),{type:'capture_state',attempt:1,phase:'active'});
  h.listeners.get('copilot:live-packet')(e(c),{type:'final',text:'Synthetic transcript'});
  const history=JSON.stringify(invoke(h,'live-state'));
  invoke(h,'set-on-top',true);
  h.window.bounds={x:500,y:180,width:1100,height:760};
  assert.equal(invoke(h,'set-live-mode','compact').mode,'compact');
  assert.deepEqual(JSON.parse(JSON.stringify(h.window.bounds)),{x:500,y:180,width:520,height:700});
  h.window.bounds={x:700,y:250,width:460,height:600};
  invoke(h,'set-live-mode','compact'); // idempotent requests do not reset user geometry
  assert.equal(h.window.bounds.width,460);
  invoke(h,'set-live-mode','expanded');
  assert.deepEqual(JSON.parse(JSON.stringify(h.window.bounds)),{x:500,y:180,width:1100,height:760});
  invoke(h,'set-live-mode','compact');
  assert.deepEqual(JSON.parse(JSON.stringify(h.window.bounds)),{x:700,y:250,width:460,height:600});
  assert.equal(h.windows.length,2);assert.equal(c.isDestroyed(),false);
  assert.equal(c.visible,false);assert.equal(h.window.skipTaskbar,true);
  assert.equal(h.trays.length,1);assert.equal(h.timers.size,1);
  assert.equal(h.window.protected,true);assert.equal(h.window.top,true);
  assert.equal(JSON.stringify(invoke(h,'live-state')),history);
  invoke(h,'window-minimize');assert.equal(h.window.minimized,true);
  invoke(h,'window-close');assert.equal(c.isDestroyed(),true);
});

test('overlay IPC bounds alpha/layout, supplies opaque fallbacks and keeps native access trusted',async()=>{
  const h=await boot();
  assert.equal(h.window.options.transparent,true);assert.equal(h.window.options.frame,false);
  assert.equal(invoke(h,'set-live-opacity',0.9),false); // other pages/expanded are opaque
  for(const mode of [null,{},'minimized'])assert.equal(invoke(h,'set-live-mode',mode),false);
  invoke(h,'set-live-mode','compact');
  for(const alpha of [null,'0.9',NaN,Infinity,0.79,1.01])assert.equal(invoke(h,'set-live-opacity',alpha),false);
  assert.equal(invoke(h,'set-live-opacity',0.8).backgroundOpacity,0.8);
  assert.equal(h.window.background,'#00000000');assert.equal(h.window.resizable,false);
  invoke(h,'set-live-mode','expanded');assert.equal(h.window.background,'#0a0f19');assert.equal(h.window.resizable,true);
  invoke(h,'set-live-mode','compact');assert.equal(h.window.background,'#00000000');
  invoke(h,'set-live-opacity',1);assert.equal(h.window.background,'#0a0f19');assert.equal(h.window.resizable,true);
  for(const method of ['set-live-mode','set-live-opacity','window-minimize','window-close']) {
    assert.throws(()=>h.handles.get('copilot:'+method)({sender:{},senderFrame:h.window.webContents.mainFrame},'compact'),/Untrusted/);
  }
  for(const options of [{opaqueWindow:true},{transparentFails:true},{backgroundFails:true}]) {
    const fallback=await boot(options);invoke(fallback,'set-live-mode','compact');
    if(options.backgroundFails)invoke(fallback,'set-live-opacity',0.9);
    const state=invoke(fallback,'window-state');
    assert.equal(state.transparencyAvailable,false);assert.equal(state.backgroundOpacity,1);
    assert.equal(invoke(fallback,'set-live-opacity',0.9),false);
    assert.equal(fallback.window.background,'#0a0f19');
  }
  const small=await boot({workArea:{x:0,y:0,width:800,height:540}});
  small.window.bounds={x:2000,y:2000,width:1200,height:820};
  invoke(small,'set-live-mode','compact');
  assert.ok(small.window.bounds.x+small.window.bounds.width<=800);
  assert.ok(small.window.bounds.y+small.window.bounds.height<=540);
});

test('capture runs only in an isolated session, and media requires main-frame user gesture',async()=>{
 const h=await boot();
 assert.equal(invoke(h,'live-open'),true);
 assert.equal(h.windows.length,2);
 const capture=h.windows[1];
 assert.equal(capture.options.webPreferences.partition,'live-capture');
  assert.equal(capture.options.webPreferences.sandbox,true);
  assert.equal(capture.protected,false); // Main-window protection is not inherited by the auxiliary window.
 assert.equal(capture.webContents.mainFrame.url,DEV+'/audio-lab/transcribe.html');
 assert.equal(h.window.webContents.check(),false);
 const media=capture.webContents.display;
 const run=async request=>{let result;await media(request,data=>{result=data;});return result;};
 assert.equal(JSON.stringify(await run({frame:capture.webContents.mainFrame,userGesture:false})),'{}');
 assert.equal(JSON.stringify(await run({frame:{url:DEV+'/audio-lab/transcribe.html'},userGesture:true})),'{}');
 const granted=await run({frame:capture.webContents.mainFrame,userGesture:true});
 assert.equal(granted.video.id,'screen:1:0');
 assert.equal(granted.audio,'loopback');
 assert.equal(invoke(h,'live-open'),true);
 assert.equal(h.windows.length,2);
});
test('reject capture event spoofing and sanitize accepted packets',async()=>{
 const h=await boot();invoke(h,'live-open');const c=h.windows[1];
 const publish=h.listeners.get('copilot:live-packet');
 publish(e(h.window),{type:'suggestion',question:'spoofed',answer:'x',status:'found',match_type:'exact_qa'});
 assert.equal(invoke(h,'live-state').events.length,1); // capture opened status only
 publish(e(c),{type:'suggestion',question:'what is auth',answer:'A'.repeat(12000),status:'found',match_type:'semantic_qa',source:{document_name:'document',location:'line 2'},matched_question:'what is authentication'});
 const state=invoke(h,'live-state');
 assert.equal(state.events.length,2);
 assert.equal(state.events[1].answer.length,10000);
 assert.equal(state.events[1].match_type,'semantic_qa');
 assert.equal(h.window.webContents.sent.at(-1).data.type,'suggestion');
 publish(e(c),{type:'custom',question:'x'});
 assert.equal(invoke(h,'live-state').events.length,2);
 assert.equal(invoke(h,'live-close'),true);
 assert.equal(invoke(h,'live-state').open,false);
 assert.equal(invoke(h,'live-state').events.at(-1).text,'Captura detenida.');
});
test('packaged renderer cannot open Vite-origin capture window',async()=>{
 const h=await boot({packaged:true});
 assert.equal(invoke(h,'live-open'),false);
 assert.equal(h.windows.length,1);
});

test('only confirmed capture hides both taskbar buttons; tray restores workspace and existing controls',async()=>{
  const h=await boot();invoke(h,'live-open');const c=h.windows[1];
  const publish=(win,packet)=>h.listeners.get('copilot:live-packet')(e(win),packet);
  publish(h.window,{type:'capture_state',attempt:1,phase:'connecting'});
  publish(c,{type:'capture_state',attempt:1,phase:'active'}); // no matching attempt
  assert.equal(h.trays.length,0);
  publish(c,{type:'capture_state',attempt:1,phase:'connecting'});
  publish(c,{type:'status',text:'Vosk listo. Reproduce una frase en Windows.'});
  assert.notEqual(h.window.skipTaskbar,true);
  publish(c,{type:'capture_state',attempt:1,phase:'active'});
  assert.equal(c.options.webPreferences.backgroundThrottling,false);
  assert.equal(h.window.skipTaskbar,true);assert.equal(c.skipTaskbar,true);
  assert.equal(h.window.visible,true);assert.equal(c.visible,false);
  h.window.minimized=true;h.trays[0].emit('click');
  assert.equal(h.window.minimized,false);assert.equal(h.window.visible,true);
  c.minimized=true;h.trays[0].menu[1].click();
  assert.equal(c.visible,true);assert.equal(c.minimized,false);assert.equal(h.windows.length,2);
  assert.equal(h.handles.get('copilot:capture-hide')(e(c)),true);
  assert.equal(c.visible,false);
  assert.equal(invoke(h,'ui-language','en'),true);
  assert.equal(h.trays[0].menu[0].label,'Restore workspace');
  assert.equal(h.handles.get('copilot:capture-language')(e(c)),'en');
  assert.equal(invoke(h,'ui-language','fr'),false);
  assert.throws(()=>h.handles.get('copilot:capture-language')(e(h.window)),/Untrusted/);
  assert.equal(h.handles.get('copilot:capture-hide')(e(h.window)),false);
  publish(c,{type:'capture_state',attempt:1,phase:'stopping'});
  assert.equal(h.window.skipTaskbar,false);assert.equal(c.skipTaskbar,false);
  assert.equal(h.trays[0].destroyed,true);assert.equal(h.timers.size,0);
  publish(c,{type:'capture_state',attempt:1,phase:'active'});
  assert.equal(h.trays.length,1); // late ready cannot rehide after stop
  publish(c,{type:'capture_state',attempt:1,phase:'stopped'});
  assert.equal(c.visible,true);
});

test('stalled PCM or suspended audio reveals controls and prevents rehide until a new attempt',async()=>{
  const h=await boot();invoke(h,'live-open');const c=h.windows[1];
  const publish=packet=>h.listeners.get('copilot:live-packet')(e(c),packet);
  const phase=(attempt,value)=>publish({type:'capture_state',attempt,phase:value});
  phase(1,'connecting');phase(1,'active');
  h.advance(4000);publish({type:'metrics',frames:40});h.advance(4000);
  assert.equal(c.visible,false); // increasing PCM keeps the watchdog alive
  publish({type:'metrics',frames:40});h.advance(4000); // repeated count is not progress
  assert.equal(c.visible,true);assert.equal(h.window.skipTaskbar,false);assert.equal(h.timers.size,0);
  assert.equal(h.handles.get('copilot:capture-hide')(e(c)),false);
  phase(1,'active');assert.equal(c.visible,true);
  phase(1,'stopped');phase(2,'connecting');phase(2,'active');
  assert.equal(c.visible,false);
  publish({type:'capture_attention',attempt:1});assert.equal(c.visible,false);
  publish({type:'capture_attention',attempt:2});assert.equal(c.visible,true);
  assert.equal(h.window.skipTaskbar,false);
});

test('tray failure and capture crash/close preserve normal recovery and release native lifetimes',async()=>{
  const unavailable=await boot({trayFails:true});invoke(unavailable,'live-open');const first=unavailable.windows[1];
  const send=(h,c,phase)=>h.listeners.get('copilot:live-packet')(e(c),{type:'capture_state',attempt:1,phase});
  send(unavailable,first,'connecting');send(unavailable,first,'active');
  assert.equal(unavailable.window.skipTaskbar,false);assert.equal(first.visible,true);
  assert.equal(unavailable.timers.size,0);
  for (const ending of ['error','crash','close-main']) {
    const h=await boot();invoke(h,'live-open');const c=h.windows[1];
    send(h,c,'connecting');send(h,c,'active');
    if(ending==='error')send(h,c,'error');
    else if(ending==='crash')c.webContents.emit('render-process-gone');
    else h.window.close();
    assert.equal(h.timers.size,0);assert.equal(h.trays[0].destroyed,true);
    if(ending==='close-main')assert.equal(c.isDestroyed(),true);
    else {assert.equal(c.visible,true);assert.equal(h.window.skipTaskbar,false);}
  }
});

const generated = () => ({type:'generated_suggestion',kind:'ai_generated',session_id:'abc-123',
  question_id:'abc-123:conn:1',question:'Explain caching?',language:'en-US',answer:'Practical answer.',
  provider:'ollama',model:'local',source:null});
test('generation failure IPC allows only safe codes/correlation and strips private details',async()=>{
  const h=await boot();invoke(h,'live-open');const c=h.windows[1];
  const publish=h.listeners.get('copilot:live-packet');
  const failure={type:'generation_failed',session_id:'abc-123',question_id:'abc-123:conn:1',code:'timeout'};
  const initial=invoke(h,'live-state').events.length;
  publish(e(h.window),failure);
  publish({...e(c),senderFrame:{url:c.webContents.mainFrame.url}},failure);
  for(const patch of [{code:'PRIVATE EXCEPTION'},{code:{}},{session_id:''},{session_id:'x'.repeat(81)},
    {session_id:'bad/id'},{question_id:'other:1'},{question_id:'abc-123:bad/id'},
    {question_id:'abc-123:'+'x'.repeat(153)},{answer:'REJECTED CONTENT'},
    {source:{document_name:'fake'}},{kind:'ai_generated'},{match_type:'exact_qa'},{status:'found'}]) {
    publish(e(c),{...failure,...patch});
  }
  assert.equal(invoke(h,'live-state').events.length,initial);
  for(const code of ['disabled','not_configured','invalid_input','unavailable','timeout','invalid_response','provider_error']) {
    publish(e(c),{...failure,code,message:'PRIVATE',prompt:'PRIVATE',credentials:'PRIVATE',question:'PRIVATE'});
    assert.deepEqual(JSON.parse(JSON.stringify(invoke(h,'live-state').events.at(-1))),{...failure,code});
    assert.deepEqual(JSON.parse(JSON.stringify(h.window.webContents.sent.at(-1).data)),{...failure,code});
  }
});
test('generated event is allowlisted, bounded and cannot carry documentary provenance',async()=>{
  const h=await boot();invoke(h,'live-open');const c=h.windows[1];
  const publish=h.listeners.get('copilot:live-packet');
  const initial=invoke(h,'live-state').events.length;
  publish(e(h.window),generated()); // wrong window
  publish({...e(c),senderFrame:{url:c.webContents.mainFrame.url}},generated()); // subframe
  for(const patch of [{source:{document_name:'fake'}},{kind:'exact_qa'},{match_type:'exact_qa'},
    {status:'found'},{provider:'cloud'},{model:''},{question:''},{answer:''},{answer:'x'.repeat(2001)},
    {question:'x'.repeat(3001)},{session_id:''},{question_id:'other:1'},{language:'fr-FR'}]) {
    publish(e(c),{...generated(),...patch});
  }
  assert.equal(invoke(h,'live-state').events.length,initial);
  publish(e(c),{...generated(),type:'suggestion',status:'found',match_type:'exact_qa'});
  assert.equal(invoke(h,'live-state').events.length,initial);
  publish(e(c),{...generated(),audio:'secret',credentials:'secret'});
  const accepted=invoke(h,'live-state').events.at(-1);
  assert.deepEqual(JSON.parse(JSON.stringify(accepted)),generated());
  assert.equal(accepted.source,null);
  assert.equal(h.window.webContents.sent.at(-1).data.type,'generated_suggestion');
  for(let i=0;i<100;i++) publish(e(c),generated());
  assert.equal(invoke(h,'live-state').events.length,80);
});

test('credential IPC authenticates the frame, allowlists actions and excludes capture preparation',async()=>{
  const h=await boot();
  const handler=h.handles.get('copilot:deepgram-credentials');
  assert.throws(()=>handler({sender:{},senderFrame:h.window.webContents.mainFrame},'delete'),/Untrusted IPC/);
  assert.throws(()=>handler({...e(h.window),senderFrame:{url:DEV}},'delete'),/Untrusted IPC/);
  assert.equal((await invoke(h,'deepgram-credentials',{key:'fictitious'})).result,'error');
  assert.equal(h.credentialCalls.length,0);
  assert.equal((await invoke(h,'deepgram-credentials','status')).stored,false);
  h.credentials.busy=true;assert.equal(invoke(h,'live-open'),false);h.credentials.busy=false;
  invoke(h,'live-open');
  assert.equal((await invoke(h,'deepgram-credentials','delete')).result,'busy');
  assert.equal(h.credentialCalls.length,1);
});

test('native capture denies media before enumeration when credential editing holds the guard',async()=>{
  const h=await boot({captureAllowed:false});invoke(h,'live-open');const win=h.windows[1];
  let granted;
  await win.webContents.display({frame:win.webContents.mainFrame,userGesture:true},value=>{granted=value;});
  assert.equal(JSON.stringify(granted),'{}');
});
