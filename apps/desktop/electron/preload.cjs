/** Minimal and explicit native bridge for window-only controls. */
'use strict';
const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('copilotDesktop', {
  manageDeepgramKey: action => ['status','configure','replace','delete'].includes(action)
    ? ipcRenderer.invoke('copilot:deepgram-credentials', action)
    : Promise.resolve({result:'error',stored:null}),
  cancelDeepgramKey: () => ipcRenderer.invoke('copilot:deepgram-cancel'),
  manageDeepseekKey: action => ['status','configure','replace','delete'].includes(action)
    ? ipcRenderer.invoke('copilot:deepseek-credentials', action)
    : Promise.resolve({result:'error',stored:null}),
  cancelDeepseekKey: () => ipcRenderer.invoke('copilot:deepseek-cancel'),
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
  onDeepgramSettings: callback => {
    const listener = () => callback();
    ipcRenderer.on('copilot:deepgram-settings', listener);
    return () => ipcRenderer.removeListener('copilot:deepgram-settings', listener);
  },
  onLiveEvent: callback => {
    const listener = (_event, packet) => callback(packet);
    ipcRenderer.on('copilot:live-event', listener);
    return () => ipcRenderer.removeListener('copilot:live-event', listener);
  },
});
