/** Minimal and explicit native bridge for window-only controls. */
'use strict';
const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('copilotDesktop', {
  getWindowState: () => ipcRenderer.invoke('copilot:window-state'),
  setContentProtection: enabled => ipcRenderer.invoke('copilot:set-protection', enabled),
  setAlwaysOnTop: enabled => ipcRenderer.invoke('copilot:set-on-top', enabled),
});
