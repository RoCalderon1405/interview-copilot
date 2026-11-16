/** One-way event bridge from the isolated, consent-driven audio window. */
'use strict';
const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('copilotCapture', {
  publish: packet => ipcRenderer.send('copilot:live-packet', packet),
});
