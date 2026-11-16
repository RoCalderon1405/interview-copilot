/** Interview Copilot native window shell. System audio is deliberately NOT enabled here. */
'use strict';
const { app, BrowserWindow, ipcMain, desktopCapturer } = require('electron');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const DEV_ORIGIN = 'http://127.0.0.1:5173';
const isDev = !app.isPackaged;
const productionHref = pathToFileURL(path.join(__dirname, '../dist/index.html')).href;
let mainWindow;
let captureWindow;
const liveEvents = [];
const LIVE_EVENT_LIMIT = 80;
const CAPTURE_PATH = '/audio-lab/transcribe.html';
const CAPTURE_URL = DEV_ORIGIN + CAPTURE_PATH;
const CAPTURE_FILE = path.join(__dirname, '../dist/audio-lab/transcribe.html');

function trustedCapture(event) {
  const win = captureWindow;
  if (!win || win.isDestroyed() || event.sender !== win.webContents ||
      event.senderFrame !== win.webContents.mainFrame) return false;
  const url = event.senderFrame?.url;
  return isDev ? url === CAPTURE_URL : url === pathToFileURL(CAPTURE_FILE).href;
}
function cleanText(value, max = 3000) {
  return typeof value === 'string' ? value.slice(0, max) : '';
}
function safeLiveEvent(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  if (raw.type === 'status') return {type: 'status', text: cleanText(raw.text, 240)};
  if (raw.type === 'metrics' && Number.isFinite(raw.frames) && raw.frames >= 0)
    return {type: 'metrics', frames: Math.floor(raw.frames)};
  if (raw.type === 'partial' || raw.type === 'final')
    return {type: raw.type, text: cleanText(raw.text)};
  if (raw.type === 'error') return {type:'error', text:cleanText(raw.text, 240)};
  if (raw.type === 'suggestion') {
    const hasAnswer = raw.status === 'found' && typeof raw.answer === 'string' && raw.answer.trim();
    const matchType = ['exact_qa','semantic_qa'].includes(raw.match_type) ? raw.match_type : null;
    const source = raw.source && typeof raw.source === 'object' && !Array.isArray(raw.source)
      ? { document_name: cleanText(raw.source.document_name, 250), location: cleanText(raw.source.location, 180) } : null;
    return {
      type: 'suggestion', question: cleanText(raw.question),
      status: hasAnswer && matchType ? 'found' : 'no_evidence',
      answer: hasAnswer && matchType ? cleanText(raw.answer, 10000) : null,
      match_type: hasAnswer && matchType ? matchType : null,
      matched_question: cleanText(raw.matched_question), source,
    };
  }
  return null;
}
function emitLive(event) {
  if (event.type !== 'partial' && event.type !== 'metrics') {
    liveEvents.push(event);
    if (liveEvents.length > LIVE_EVENT_LIMIT) liveEvents.shift();
  }
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('copilot:live-event', event);
}
function openLiveCapture() {
  // Production file:// origins are intentionally not allowed by the local WS backend.
  // Only the verified Vite-origin development pipeline is enabled in this milestone.
  if (!isDev || process.platform !== 'win32') return false;
  if (captureWindow && !captureWindow.isDestroyed()) {
    captureWindow.show(); captureWindow.focus(); return true;
  }
  liveEvents.length = 0;
  captureWindow = new BrowserWindow({
    width: 680, height: 740, minWidth: 490, minHeight: 520,
    title: 'Live audio — autorización y controles',
    backgroundColor: '#0a0f19', autoHideMenuBar: true,
    webPreferences: {
      partition: 'live-capture', preload: path.join(__dirname, 'capture-preload.cjs'),
      contextIsolation: true, sandbox: true, nodeIntegration: false, webSecurity: true,
    },
  });
  const current = captureWindow;
  // Separate session: the production renderer continues to deny media permissions.
  current.webContents.session.setDisplayMediaRequestHandler(async (request, callback) => {
    try {
      if (current.isDestroyed() || request.frame !== current.webContents.mainFrame ||
          request.userGesture !== true || !trustedCapture({sender:current.webContents,senderFrame:request.frame})) {
        callback({}); return;
      }
      const sources = await desktopCapturer.getSources({types:['screen'], thumbnailSize:{width:0,height:0}});
      callback(sources.length ? {video:sources[0],audio:'loopback'} : {});
    } catch { callback({}); }
  }, {useSystemPicker:false});
  current.webContents.setWindowOpenHandler(() => ({action:'deny'}));
  current.webContents.on('will-navigate',(event,url) => {
    if (url !== (isDev ? CAPTURE_URL : pathToFileURL(CAPTURE_FILE).href)) event.preventDefault();
  });
  current.on('closed', () => {
    if (captureWindow === current) captureWindow = undefined;
    emitLive({type:'status',text:'Captura detenida.'});
  });
  if (isDev) void current.loadURL(CAPTURE_URL);
  else void current.loadFile(CAPTURE_FILE);
  emitLive({type:'status',text:'Confirma la captura en la ventana de audio.'});
  return true;
}


function trustedUrl(url) {
  try {
    const parsed = new URL(url);
    return isDev
      ? parsed.protocol === 'http:' && parsed.origin === DEV_ORIGIN && !parsed.username && !parsed.password
      : parsed.protocol === 'file:' && parsed.href.split('#')[0] === productionHref;
  } catch { return false; }
}
function trustedWindow(event) {
  const win = mainWindow;
  if (!win || win.isDestroyed() || !event || event.sender !== win.webContents || win.webContents.isDestroyed()
      || !event.senderFrame || event.senderFrame !== win.webContents.mainFrame || !trustedUrl(event.senderFrame.url)) {
    throw new Error('Untrusted IPC request rejected');
  }
  return win;
}
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1220, height: 820, minWidth: 880, minHeight: 650, title: 'Interview Copilot',
    backgroundColor: '#0a0f19', show: false, autoHideMenuBar: true,
    webPreferences: { preload: path.join(__dirname,'preload.cjs'), contextIsolation: true,
      sandbox: true, nodeIntegration: false, webSecurity: true },
  });
  const ses = mainWindow.webContents.session;
  // The production shell never requests audio/video. Do not expose media permissions here.
  ses.setPermissionCheckHandler(() => false);
  ses.setPermissionRequestHandler((_wc, _perm, callback) => callback(false));
  ses.setDisplayMediaRequestHandler((_request, callback) => callback({}));
  if (process.platform === 'win32') mainWindow.setContentProtection(true);
  mainWindow.once('ready-to-show', () => mainWindow.show());
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  mainWindow.webContents.on('will-navigate', (event, url) => { if (!trustedUrl(url)) event.preventDefault(); });
  if (isDev) void mainWindow.loadURL(DEV_ORIGIN);
  else void mainWindow.loadFile(path.join(__dirname,'../dist/index.html'));
}
app.whenReady().then(() => {
  ipcMain.handle('copilot:window-state', event => {
    const win = trustedWindow(event);
    return { available: true, protected: win.isContentProtected(), alwaysOnTop: win.isAlwaysOnTop() };
  });
  ipcMain.handle('copilot:set-protection', (event, enabled) => {
    const win = trustedWindow(event);
    if (typeof enabled !== 'boolean') return false;
    win.setContentProtection(enabled);
    return win.isContentProtected();
  });
  ipcMain.handle('copilot:set-on-top', (event, enabled) => {
    const win = trustedWindow(event);
    if (typeof enabled !== 'boolean') return false;
    win.setAlwaysOnTop(enabled);
    return win.isAlwaysOnTop();
  });
  ipcMain.handle('copilot:live-open', event => {
    trustedWindow(event);
    return openLiveCapture();
  });
  ipcMain.handle('copilot:live-close', event => {
    trustedWindow(event);
    if (captureWindow && !captureWindow.isDestroyed()) captureWindow.close();
    return true;
  });
  ipcMain.handle('copilot:live-state', event => {
    trustedWindow(event);
    return {open: Boolean(captureWindow && !captureWindow.isDestroyed()), events: [...liveEvents]};
  });
  ipcMain.on('copilot:live-packet', (event, data) => {
    if (!trustedCapture(event)) return;
    const safe = safeLiveEvent(data);
    if (!safe || (safe.type === 'suggestion' && !safe.question.trim())) return;
    emitLive(safe);
  });
  createWindow();
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
