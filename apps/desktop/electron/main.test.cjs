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
function boot({packaged=false, platform='win32'}={}) {
  const handles = new Map();
  const windows=[];
  class Contents extends EventEmitter {
    constructor(){super();this.mainFrame={url:''};this.session={setPermissionCheckHandler:fn=>{this.check=fn;},setPermissionRequestHandler:fn=>{this.request=fn;},setDisplayMediaRequestHandler:fn=>{this.display=fn;}};this.destroyed=false;}
    isDestroyed(){return this.destroyed;}
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
    show(){}
    static getAllWindows(){return windows;}
  }
  const electron={app:{isPackaged:packaged,whenReady:()=>Promise.resolve(),on(){},quit(){}},BrowserWindow:Window,ipcMain:{handle:(name,fn)=>handles.set(name,fn)}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'main.cjs'),'utf8'),{__dirname,URL,process:{platform},require:id=>id==='electron'?electron:require(id)}, {filename:'main.cjs'});
  return new Promise(resolve=>setImmediate(()=>resolve({handles,window:windows[0]})));
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
