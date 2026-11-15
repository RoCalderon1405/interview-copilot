/** Interview Copilot native window shell. System audio is deliberately NOT enabled here. */
'use strict';
const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const DEV_ORIGIN = 'http://127.0.0.1:5173';
const isDev = !app.isPackaged;
const productionHref = pathToFileURL(path.join(__dirname, '../dist/index.html')).href;
let mainWindow;

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
  createWindow();
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
