/** Minimal and explicit native bridge for window-only controls. */
'use strict';
const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('copilotDesktop', {
  getWindowState: () => ipcRenderer.invoke('copilot:window-state'),
  setLiveMode: mode => ipcRenderer.invoke('copilot:set-live-mode', mode),
  setLiveOpacity: opacity => ipcRenderer.invoke('copilot:set-live-opacity', opacity),
  minimizeWindow: () => ipcRenderer.invoke('copilot:window-minimize'),
  closeWindow: () => ipcRenderer.invoke('copilot:window-close'),
  setContentProtection: enabled => ipcRenderer.invoke('copilot:set-protection', enabled),
  setAlwaysOnTop: enabled => ipcRenderer.invoke('copilot:set-on-top', enabled),
  openLiveCapture: () => ipcRenderer.invoke('copilot:live-open'),
  closeLiveCapture: () => ipcRenderer.invoke('copilot:live-close'),
  getLiveState: () => ipcRenderer.invoke('copilot:live-state'),
  setUiLanguage: language => ipcRenderer.invoke('copilot:ui-language', language),
  onLiveEvent: callback => {
    const listener = (_event, packet) => callback(packet);
    ipcRenderer.on('copilot:live-event', listener);
    return () => ipcRenderer.removeListener('copilot:live-event', listener);
  },
});
