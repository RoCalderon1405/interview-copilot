import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export default defineConfig({
  plugins: [react()],
  server: { host: '127.0.0.1', port: 5173, strictPort: true },
  base: './',
  build: { rollupOptions: { input: {
    main: resolve(fileURLToPath(new URL('.', import.meta.url)), 'index.html'),
    capture: resolve(fileURLToPath(new URL('.', import.meta.url)), 'audio-lab/transcribe.html'),
  } } },
});
