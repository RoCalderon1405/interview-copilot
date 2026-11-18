/** One-way event bridge from the isolated, consent-driven audio window. */
'use strict';
const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('copilotCapture', {
  publish: packet => ipcRenderer.send('copilot:live-packet', packet),
  getUiLanguage: () => ipcRenderer.invoke('copilot:capture-language'),
  hideControls: () => ipcRenderer.invoke('copilot:capture-hide'),
  onUiLanguage: callback => {
    const listener = (_event, language) => { if (language === 'en' || language === 'es') callback(language); };
    ipcRenderer.on('copilot:ui-language', listener);
    return () => ipcRenderer.removeListener('copilot:ui-language', listener);
  },
});
