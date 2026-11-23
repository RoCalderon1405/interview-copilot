/** Interview Copilot native window shell. System audio is deliberately NOT enabled here. */
'use strict';
const { app, BrowserWindow, ipcMain, desktopCapturer, Tray, Menu, nativeImage, screen } = require('electron');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const {createCredentials,captureGuard}=require('./credentials.cjs');
const DEV_ORIGIN = 'http://127.0.0.1:5173';
const isDev = !app.isPackaged;
const credentials=createCredentials({root:path.resolve(__dirname,'../../..'),enabled:isDev && process.platform==='win32'});
const productionHref = pathToFileURL(path.join(__dirname, '../dist/index.html')).href;
let mainWindow;
let captureWindow;
let recoveryTray;
let uiLanguage = 'es';
let capturePhase = 'idle';
let captureAttempt = 0;
let quitting = false;
let hideAllowed = true;
let continuityTimer;
let lastPcmAt = 0;
let lastPcmFrames = 0;
let liveMode = 'expanded';
let liveOpacity = 1;
let transparencyAvailable = process.platform === 'win32' && process.env?.COPILOT_OPAQUE_WINDOW !== '1';
let customFrame = transparencyAvailable;
const modeBounds = {expanded:null, compact:null};
let expandedMaximized = false;

function windowState(win) {
  return {available:true, protected:win.isContentProtected(), alwaysOnTop:win.isAlwaysOnTop(),
    mode:liveMode, backgroundOpacity:liveOpacity, transparencyAvailable, customFrame};
}
function applyLiveBackground(win) {
  const translucent = transparencyAvailable && liveMode === 'compact' && liveOpacity < 1;
  try {
    // Electron documents transparent-window resize limitations. Never fade text with setOpacity.
    win.setResizable(!translucent);
    win.setBackgroundColor(translucent ? '#00000000' : '#0a0f19');
  } catch {
    transparencyAvailable = false; liveOpacity = 1;
    win.setBackgroundColor('#0a0f19');
    win.setResizable(true);
  }
}
function setLiveMode(win, mode) {
  if (!['compact','expanded'].includes(mode)) return false;
  if (mode === liveMode) return windowState(win);
  modeBounds[liveMode] = win.getNormalBounds();
  if (liveMode === 'expanded') expandedMaximized = win.isMaximized();
  if (win.isMaximized()) win.unmaximize();
  const previous = modeBounds[liveMode];
  const target = modeBounds[mode] ?? {...previous, width:520, height:700};
  const area = screen.getDisplayMatching(target).workArea;
  const minWidth = Math.min(mode === 'compact' ? 420 : 880, area.width);
  const minHeight = Math.min(mode === 'compact' ? 400 : 650, area.height);
  const width = Math.min(area.width, Math.max(minWidth,target.width));
  const height = Math.min(area.height, Math.max(minHeight,target.height));
  win.setMinimumSize(minWidth,minHeight);
  win.setBounds({width,height,x:Math.max(area.x,Math.min(target.x,area.x+area.width-width)),
    y:Math.max(area.y,Math.min(target.y,area.y+area.height-height))});
  liveMode = mode;
  applyLiveBackground(win);
  if (mode === 'expanded' && expandedMaximized) win.maximize();
  return windowState(win);
}

function revealCaptureSafety() {
  hideAllowed = false;
  restoreTaskbar(true);
  emitLive({type:'error', text:'Continuidad de audio sin confirmar. Controles restaurados; revisa o detén la captura.'});
}

function restoreWindow(win, focus = true) {
  if (!win || win.isDestroyed()) return;
  if (win.isMinimized()) win.restore();
  if (focus) { win.show(); win.focus(); }
  else win.showInactive();
}
function updateRecoveryMenu() {
  if (!recoveryTray) return;
  const es = uiLanguage === 'es';
  recoveryTray.setToolTip('Interview Copilot — ' + (es ? 'captura activa' : 'capture active'));
  recoveryTray.setContextMenu(Menu.buildFromTemplate([
    {label: es ? 'Restaurar workspace' : 'Restore workspace', click: () => restoreWindow(mainWindow)},
    {label: es ? 'Mostrar controles de audio' : 'Show audio controls', click: () => restoreWindow(captureWindow)},
    {label: es ? 'Detener y cerrar captura' : 'Stop and close capture', click: () => captureWindow?.close()},
  ]));
}
function restoreTaskbar(showControls = false) {
  if (continuityTimer) clearInterval(continuityTimer);
  continuityTimer = undefined;
  for (const win of [mainWindow, captureWindow]) {
    if (win && !win.isDestroyed()) win.setSkipTaskbar(false);
  }
  recoveryTray?.destroy();
  recoveryTray = undefined;
  if (showControls && !quitting) restoreWindow(captureWindow, false);
}
function activateCapturePresentation() {
  if (process.platform !== 'win32' || !captureWindow || captureWindow.isDestroyed()) return;
  try {
    if (!recoveryTray) {
      // A small native BGRA waveform icon; no downloaded assets or native dependencies.
      const pixels = Buffer.alloc(16 * 16 * 4);
      for (let x = 2; x < 14; x++) {
        const height = [2, 4, 6, 3][Math.floor(x / 2) % 4];
        for (let y = 8 - height; y < 8 + height; y++) {
          const i = (y * 16 + x) * 4;
          pixels[i] = 245; pixels[i + 1] = 190; pixels[i + 2] = 110; pixels[i + 3] = 255;
        }
      }
      const icon = nativeImage.createFromBitmap(pixels, {width:16, height:16});
      if (icon.isEmpty()) throw new Error('Empty recovery icon');
      recoveryTray = new Tray(icon);
      recoveryTray.on('click', () => restoreWindow(mainWindow));
      updateRecoveryMenu();
    }
    mainWindow.setSkipTaskbar(true);
    captureWindow.setSkipTaskbar(true);
    if (hideAllowed) { captureWindow.hide(); restoreWindow(mainWindow); }
    if (!continuityTimer && hideAllowed) {
      lastPcmAt = Date.now(); lastPcmFrames = 0;
      continuityTimer = setInterval(() => {
        if (Date.now() - lastPcmAt > 6000) revealCaptureSafety();
      }, 2000);
      continuityTimer.unref();
    }
  } catch {
    // Never remove the normal recovery path if the native tray cannot be created.
    hideAllowed = false;
    restoreTaskbar(true);
  }
}

function acceptCapturePhase(raw) {
  if (!raw || raw.type !== 'capture_state' || !Number.isSafeInteger(raw.attempt) || raw.attempt < 1 ||
      !['connecting','active','stopping','stopped','error'].includes(raw.phase)) return;
  if (raw.attempt < captureAttempt) return;
  if (raw.attempt > captureAttempt) {
    if (raw.phase !== 'connecting') return;
    captureAttempt = raw.attempt;
    hideAllowed = true;
  } else {
    const transitions = {connecting:['active','stopping','stopped','error'], active:['stopping','stopped','error'], stopping:['stopped','error']};
    if (!transitions[capturePhase]?.includes(raw.phase)) return;
  }
  capturePhase = raw.phase;
  if (raw.phase === 'active') activateCapturePresentation();
  else restoreTaskbar(raw.phase === 'stopped' || raw.phase === 'error');
}
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
  if (raw.type === 'generation_failed') {
    if (!['disabled','not_configured','invalid_input','unavailable','timeout','invalid_response','provider_error'].includes(raw.code) ||
        typeof raw.session_id !== 'string' || !/^[a-zA-Z0-9-]{1,80}$/.test(raw.session_id) ||
        typeof raw.question_id !== 'string' || raw.question_id.length > 160 ||
        !raw.question_id.startsWith(raw.session_id + ':') || !/^[a-zA-Z0-9:-]+$/.test(raw.question_id) ||
        raw.kind != null || raw.answer != null || raw.source != null || raw.match_type != null || raw.status != null) return null;
    // Never relay error messages, provider payloads or rejected content.
    return {type:'generation_failed', session_id:raw.session_id, question_id:raw.question_id, code:raw.code};
  }
  if (raw.type === 'generated_suggestion') {
    const bounded = (value, max) => typeof value === 'string' && value.trim().length > 0 && value.length <= max;
    if (raw.kind !== 'ai_generated' || raw.source !== null || raw.provider !== 'ollama' ||
        raw.match_type != null || raw.status != null || !['en-US','es-MX'].includes(raw.language) ||
        !bounded(raw.question,3000) || !bounded(raw.answer,2000) || !bounded(raw.model,200) ||
        !bounded(raw.session_id,80) || !/^[a-zA-Z0-9-]+$/.test(raw.session_id) ||
        !bounded(raw.question_id,160) || !raw.question_id.startsWith(raw.session_id + ':') ||
        !/^[a-zA-Z0-9:-]+$/.test(raw.question_id)) return null;
    return {type:'generated_suggestion',kind:'ai_generated',source:null,provider:'ollama',
      model:raw.model,session_id:raw.session_id,question_id:raw.question_id,
      question:raw.question,language:raw.language,answer:raw.answer};
  }
  if (raw.type === 'suggestion') {
    if (raw.kind === 'ai_generated' || raw.provider != null || raw.model != null) return null;
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
      ...(typeof raw.session_id === 'string' && typeof raw.question_id === 'string'
        ? {session_id:cleanText(raw.session_id,80),question_id:cleanText(raw.question_id,160)} : {}),
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
  if (!isDev || process.platform !== 'win32' || credentials.busy) return false;
  if (captureWindow && !captureWindow.isDestroyed()) {
    restoreWindow(captureWindow); return true;
  }
  liveEvents.length = 0;
  captureWindow = new BrowserWindow({
    width: 560, height: 720, minWidth: 490, minHeight: 520,
    title: 'Live audio — autorización y controles',
    backgroundColor: '#0a0f19', autoHideMenuBar: true,
    webPreferences: {
      partition: 'live-capture', preload: path.join(__dirname, 'capture-preload.cjs'),
      contextIsolation: true, sandbox: true, nodeIntegration: false, webSecurity: true,
      backgroundThrottling: false,
    },
  });
  const current = captureWindow;
  const reserveCapture=captureGuard(credentials,current);
  capturePhase = 'idle'; captureAttempt = 0; hideAllowed = true;
  // Separate session: the production renderer continues to deny media permissions.
  current.webContents.session.setDisplayMediaRequestHandler(async (request, callback) => {
    try {
      if (current.isDestroyed() || request.frame !== current.webContents.mainFrame ||
          request.userGesture !== true || !trustedCapture({sender:current.webContents,senderFrame:request.frame})) {
        callback({}); return;
      }
      if (!await reserveCapture() || current.isDestroyed()) {callback({});return;}
      const sources = await desktopCapturer.getSources({types:['screen'], thumbnailSize:{width:0,height:0}});
      callback(sources.length ? {video:sources[0],audio:'loopback'} : {});
    } catch { callback({}); }
  }, {useSystemPicker:false});
  current.webContents.setWindowOpenHandler(() => ({action:'deny'}));
  current.webContents.on('will-navigate',(event,url) => {
    if (url !== (isDev ? CAPTURE_URL : pathToFileURL(CAPTURE_FILE).href)) event.preventDefault();
  });
  current.on('closed', () => {
    restoreTaskbar();
    capturePhase = 'stopped';
    if (captureWindow === current) captureWindow = undefined;
    emitLive({type:'status',text:'Captura detenida.'});
  });
  current.webContents.on('render-process-gone', () => {
    capturePhase = 'error';
    restoreTaskbar(true);
    emitLive({type:'error', text:'La ventana de audio dejó de responder. Cierra y prepara la captura de nuevo.'});
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
  const options = {
    width: 1220, height: 820, minWidth: 880, minHeight: 650, title: 'Interview Copilot',
    backgroundColor: '#0a0f19', show: false, autoHideMenuBar: true,
    webPreferences: { preload: path.join(__dirname,'preload.cjs'), contextIsolation: true,
      sandbox: true, nodeIntegration: false, webSecurity: true },
  };
  try {
    mainWindow = new BrowserWindow({...options, ...(transparencyAvailable
      ? {transparent:true, frame:false} : {})});
  } catch {
    transparencyAvailable = false; customFrame = false;
    mainWindow = new BrowserWindow(options);
  }
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
  mainWindow.on('close', () => {
    // A hidden capture window must not keep the application/audio alive on its own.
    quitting = true;
    credentials.cancel();
    restoreTaskbar();
    if (captureWindow && !captureWindow.isDestroyed()) captureWindow.close();
  });
}
app.whenReady().then(() => {
  ipcMain.handle('copilot:deepgram-credentials', (event, action) => {
    const win=trustedWindow(event);
    if(!['status','configure','replace','delete'].includes(action))return {result:'error',stored:null};
    if(action!=='status' && captureWindow && !captureWindow.isDestroyed())return {result:'busy',stored:null};
    return credentials.run(action,win,uiLanguage);
  });
  ipcMain.handle('copilot:deepgram-cancel',event=>{trustedWindow(event);credentials.cancel();return true;});
  ipcMain.handle('copilot:window-state', event => {
    const win = trustedWindow(event);
    return windowState(win);
  });
  ipcMain.handle('copilot:set-live-mode', (event, mode) => setLiveMode(trustedWindow(event),mode));
  ipcMain.handle('copilot:set-live-opacity', (event, opacity) => {
    const win = trustedWindow(event);
    if (typeof opacity !== 'number' || !Number.isFinite(opacity) || opacity < 0.8 || opacity > 1 ||
        (opacity !== 1 && (!transparencyAvailable || liveMode !== 'compact'))) return false;
    liveOpacity = opacity;
    applyLiveBackground(win);
    return windowState(win);
  });
  ipcMain.handle('copilot:window-minimize', event => { trustedWindow(event).minimize(); return true; });
  ipcMain.handle('copilot:window-close', event => { trustedWindow(event).close(); return true; });
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
  ipcMain.handle('copilot:ui-language', (event, language) => {
    trustedWindow(event);
    if (!['en','es'].includes(language)) return false;
    uiLanguage = language;
    if (captureWindow && !captureWindow.isDestroyed()) captureWindow.webContents.send('copilot:ui-language', language);
    updateRecoveryMenu();
    return true;
  });
  ipcMain.handle('copilot:capture-language', event => {
    if (!trustedCapture(event)) throw new Error('Untrusted IPC request rejected');
    return uiLanguage;
  });
  ipcMain.handle('copilot:capture-hide', event => {
    if (!trustedCapture(event) || capturePhase !== 'active' || !hideAllowed || !recoveryTray) return false;
    captureWindow.hide();
    return true;
  });
  ipcMain.handle('copilot:capture-settings', event => {
    if (!trustedCapture(event) || !['idle','stopped','error'].includes(capturePhase) ||
        !mainWindow || mainWindow.isDestroyed()) return false;
    // Credential editing already requires all capture windows to be closed.
    captureWindow.close();
    setLiveMode(mainWindow, 'expanded');
    restoreWindow(mainWindow);
    mainWindow.webContents.send('copilot:deepgram-settings');
    return true;
  });
  ipcMain.on('copilot:live-packet', (event, data) => {
    if (!trustedCapture(event)) return;
    if (data?.type === 'capture_state') { acceptCapturePhase(data); return; }
    if (data?.type === 'capture_attention') {
      if (data.attempt === captureAttempt && capturePhase === 'active') revealCaptureSafety();
      return;
    }
    const safe = safeLiveEvent(data);
    if (!safe || (safe.type === 'suggestion' && !safe.question.trim())) return;
    if (safe.type === 'metrics' && safe.frames > lastPcmFrames) {
      lastPcmFrames = safe.frames; lastPcmAt = Date.now();
    }
    emitLive(safe);
  });
  createWindow();
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});
app.on('before-quit', () => { quitting = true; credentials.cancel(); restoreTaskbar(); });
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
