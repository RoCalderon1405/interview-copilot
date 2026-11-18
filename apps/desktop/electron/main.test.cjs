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
function boot({packaged=false, platform='win32', trayFails=false}={}) {
  const handles = new Map();
  const listeners = new Map();
  const windows=[];
  const trays=[];
  const timers=new Set();
  let now=0;
  class Contents extends EventEmitter {
    constructor(){super();this.mainFrame={url:''};this.sent=[];this.session={setPermissionCheckHandler:fn=>{this.check=fn;},setPermissionRequestHandler:fn=>{this.request=fn;},setDisplayMediaRequestHandler:fn=>{this.display=fn;}};this.destroyed=false;}
    isDestroyed(){return this.destroyed;}
    send(channel,data){this.sent.push({channel,data});}
    setWindowOpenHandler(fn){this.windowOpen=fn;}
    navigate(url){let denied=false;this.emit('will-navigate',{preventDefault:()=>denied=true},url);return denied;}
  }
  class Window extends EventEmitter {
    constructor(options){super();this.options=options;this.webContents=new Contents();this.protected=false;this.top=false;this.destroyed=false;windows.push(this);}
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
    restore(){this.minimized=false;}
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
  const electron={app:{isPackaged:packaged,whenReady:()=>Promise.resolve(),on(){},quit(){}},BrowserWindow:Window,Tray:RecoveryTray,Menu:{buildFromTemplate:items=>items},nativeImage:{createFromBitmap:()=>({isEmpty:()=>false})},desktopCapturer:{getSources:async()=>[{id:'screen:1:0'}]},ipcMain:{handle:(name,fn)=>handles.set(name,fn),on:(name,fn)=>listeners.set(name,fn)}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'main.cjs'),'utf8'),{__dirname,URL,Buffer,Date:{now:()=>now},setInterval:fn=>{timers.add(fn);return {fn,unref(){}};},clearInterval:timer=>timers.delete(timer.fn),process:{platform},require:id=>id==='electron'?electron:require(id)}, {filename:'main.cjs'});
  return new Promise(resolve=>setImmediate(()=>resolve({handles,listeners,windows,trays,timers,window:windows[0],advance:ms=>{now+=ms;for(const fn of timers)fn();}})));
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
