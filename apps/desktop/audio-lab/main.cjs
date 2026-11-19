/** Standalone Windows loopback experiment: NO FastAPI/Vosk/RAG. */
'use strict';
const {app,BrowserWindow,desktopCapturer,session} = require('electron');
const path = require('node:path');
const {createCredentials,captureGuard}=require('../electron/credentials.cjs');
const credentials=createCredentials({root:path.resolve(__dirname,'../../..'),enabled:!app.isPackaged && process.platform==='win32'});
let win;
app.whenReady().then(() => {
  win = new BrowserWindow({width:630,height:510,title:'Windows Audio Lab',
    webPreferences:{contextIsolation:true,sandbox:true,nodeIntegration:false,webSecurity:true}});
  const reserveCapture=captureGuard(credentials,win);
  const trustedPage=process.argv.includes('--transcribe')
    ? 'http://127.0.0.1:5173/audio-lab/transcribe.html' : require('node:url').pathToFileURL(path.join(__dirname,'index.html')).href;
  // The only application page is a local, fixed file. No remote pages or popups.
  win.webContents.setWindowOpenHandler(() => ({action:'deny'}));
  win.webContents.on('will-navigate',(event,url) => {if(url !== win.webContents.getURL())event.preventDefault();});
  session.defaultSession.setDisplayMediaRequestHandler(async (request,callback) => {
    try {
      if (app.isPackaged || process.platform!=='win32' || !win || win.isDestroyed() ||
          request.frame !== win.webContents.mainFrame || request.frame.url!==trustedPage || request.userGesture !== true) {
        callback({});return;
      }
      if(!await reserveCapture() || win.isDestroyed()){callback({});return;}
      const sources=await desktopCapturer.getSources({types:['screen'],thumbnailSize:{width:0,height:0}});
      if (!sources.length){callback({});return;}
      // Loopback captures the entire Windows output. The renderer asks only after opt-in.
      callback({video:sources[0],audio:'loopback'});
    } catch(error){console.error('[audio-lab:handler]',error?.name ?? 'Error');callback({});}
  },{useSystemPicker:false});
  if (process.argv.includes('--transcribe')) {
    // Use the already trusted development origin: it matches the API's explicit CORS
    // and WebSocket Origin allowlists. Never widen the backend to file:// / null origins.
    void win.loadURL('http://127.0.0.1:5173/audio-lab/transcribe.html');
  } else {
    void win.loadFile(path.join(__dirname,'index.html'));
  }
});
app.on('window-all-closed',()=>app.quit());
