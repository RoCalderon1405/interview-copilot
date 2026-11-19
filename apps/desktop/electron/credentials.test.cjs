/** No Windows secrets: injected child streams protect the native management boundary. */
'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const {PassThrough}=require('node:stream');
const {createCredentials,captureGuard,parse}=require('./credentials.cjs');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {pathToFileURL}=require('node:url');
function fixture(options={}) {
  const children=[],calls=[];
  const win=new EventEmitter();win.webContents=new EventEmitter();win.destroyed=false;win.enabled=true;
  win.isDestroyed=()=>win.destroyed;
  win.getNativeWindowHandle=()=>Buffer.from([12,0,0,0,0,0,0,0]);
  win.setEnabled=v=>{calls.push(v);win.enabled=v;};win.focus=()=>{};
  win.close=()=>{win.destroyed=true;win.emit('closed');};
  const credentials=createCredentials({root:'C:/fixed-project',enabled:true,...options,spawnChild:(exe,args,config)=>{
    const child=new EventEmitter();child.stdin=new PassThrough();child.stdout=new PassThrough();child.stderr=new PassThrough();child.killed=false;child.exitCode=null;
    child.kill=()=>{child.killed=true;setImmediate(()=>{child.exitCode=1;child.emit('close',1);});};
    children.push({child,exe,args,config});return child;
  }});
  return {credentials,win,children,calls};
}
test('fixed trusted spawn, strict status schema and no raw provider output reaches callers',async()=>{
  const h=fixture();const pending=h.credentials.run('configure',h.win,'en');
  const {child,exe,args,config}=h.children[0];
  assert.match(exe,/\.venv[\\/]Scripts[\\/]python\.exe$/);
  assert.match(args[1],/apps[\\/]api[\\/]app[\\/]infrastructure[\\/]deepgram_credentials_helper\.py$/);
  assert.deepEqual(args.slice(2),['configure','12','en',String(process.pid)]);
  assert.equal(config.shell,false);assert.equal(config.env.COPILOT_DEEPGRAM_API_KEY,undefined);
  child.stdout.write('{"result":"configured","stored":true}');child.emit('close',0);
  assert.deepEqual(await pending,{result:'configured',stored:true});
  for(const raw of ['fictitious-secret','{"result":"status","stored":true,"key":"fictitious-secret"}','{"result":"unknown","stored":false}','{"result":"status","stored":"key"}'])assert.deepEqual(parse(raw),{result:'error',stored:null});
  assert.deepEqual(h.calls,[false,true]);
});
test('timeout, cancellation, output bounds and spawn errors restore interaction and release busy state',async()=>{
  for(const mode of ['timeout','cancel','overflow','error']) {
    const h=fixture({timeout:10});const result=h.credentials.run('replace',h.win);
    assert.equal((await h.credentials.run('delete',h.win)).result,'busy');
    const {child}=h.children[0];
    if(mode==='cancel')h.credentials.cancel();
    if(mode==='overflow')child.stdout.write('x'.repeat(1025));
    if(mode==='error')child.emit('error',new Error('fictitious-secret'));
    const value=await result;
    assert.equal(value.result,mode==='timeout'?'timed_out':mode==='cancel'?'cancelled':'error');
    assert.equal(h.win.enabled,true);assert.equal(h.credentials.busy,false);
    assert.deepEqual(h.calls,[false,true]);
  }
});
test('capture guard denies failed leases, coalesces pending requests and releases on close or renderer death',async()=>{
  const h=fixture();const reserve=captureGuard(h.credentials,h.win);
  const one=reserve(),two=reserve();assert.equal(h.children.length,1);
  h.children[0].child.stdout.write('{"result":"leased","stored":null}\n');
  assert.equal(await one,true);assert.equal(await two,true);
  h.win.close();assert.equal(h.children[0].child.killed,true);assert.equal(await reserve(),false);
  const rejected=fixture();const attempt=captureGuard(rejected.credentials,rejected.win)();
  rejected.children[0].child.stdout.write('{"result":"busy","stored":null}\n');
  assert.equal(await attempt,false);assert.equal(rejected.win.destroyed,false);
  const lost=fixture();const guard=captureGuard(lost.credentials,lost.win)();
  lost.children[0].child.stdout.write('{"result":"leased","stored":null}\n');await guard;
  lost.win.webContents.emit('render-process-gone');assert.equal(lost.win.destroyed,true);
});

test('both standalone lab routes authenticate the requesting frame and reserve before granting any loopback media',async()=>{
  for(const transcribe of [false,true]){
    let handler,win,reservations=0,enumerations=0,allowed=false;
    class Window extends EventEmitter {
      constructor(){super();win=this;this.webContents={mainFrame:{url:''},setWindowOpenHandler(){},on(){},getURL:()=>this.webContents.mainFrame.url};}
      isDestroyed(){return false;}
      loadURL(url){this.webContents.mainFrame.url=url;return Promise.resolve();}
      loadFile(file){return this.loadURL(pathToFileURL(file).href);}
    }
    const electron={app:{isPackaged:false,whenReady:()=>Promise.resolve(),on(){}},BrowserWindow:Window,
      session:{defaultSession:{setDisplayMediaRequestHandler:fn=>{handler=fn;}}},
      desktopCapturer:{getSources:async()=>{enumerations++;return [{id:'screen'}];}}};
    const dirname=path.resolve(__dirname,'../audio-lab');
    vm.runInNewContext(fs.readFileSync(path.join(dirname,'main.cjs'),'utf8'),{__dirname:dirname,console,
      process:{platform:'win32',argv:transcribe?['--transcribe']:[]},
      require:id=>id==='electron'?electron:id==='../electron/credentials.cjs'?{createCredentials:()=>({}),captureGuard:()=>async()=>{reservations++;return allowed;}}:require(id)});
    await new Promise(resolve=>setImmediate(resolve));
    let grant;
    await handler({frame:{url:win.webContents.mainFrame.url},userGesture:true},value=>{grant=value;});
    assert.equal(reservations,0);assert.equal(JSON.stringify(grant),'{}');
    await handler({frame:win.webContents.mainFrame,userGesture:true},value=>{grant=value;});
    assert.equal(reservations,1);assert.equal(enumerations,0);assert.equal(JSON.stringify(grant),'{}');
    allowed=true;
    await handler({frame:win.webContents.mainFrame,userGesture:true},value=>{grant=value;});
    assert.equal(enumerations,1);assert.equal(grant.audio,'loopback');
  }
});

test('preload refuses non-enumerated credential arguments before they enter IPC',async()=>{
  let bridge;const sent=[];
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'preload.cjs'),'utf8'),{
    require:()=>({contextBridge:{exposeInMainWorld:(_name,value)=>{bridge=value;}},ipcRenderer:{invoke:async(...args)=>{sent.push(args);return {result:'status',stored:false};}}}),
  });
  for(const value of ['fictitious-secret',{key:'fictitious-secret'},null,1])assert.equal((await bridge.manageDeepgramKey(value)).result,'error');
  assert.equal(sent.length,0);
  await bridge.manageDeepgramKey('status');assert.deepEqual(sent,[['copilot:deepgram-credentials','status']]);
});
