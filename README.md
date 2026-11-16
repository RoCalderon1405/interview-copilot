# Interview Copilot — local Windows development

**Current focus:** The user has verified loopback audio, Vosk speech recognition, question detection, original Q&A and semantic search in the standalone audio lab. This release integrates that pipeline into the **main React Live Interview page**, using an isolated consent-based capture window. **The new integration still needs a real Windows acceptance test.**

## Stack
Electron 39 + React/TypeScript; FastAPI + Vosk EN/ES; SQLite Q&A documents; optional local FastEmbed multilingual embeddings. No Docker, multi-agent configuration or LLM fallback.

## Start on Windows
Keep the existing `.venv`, `local-data/models` and SQLite database/cache from the previous user-validated version. These private/local files are **not included** in this source ZIP.

Start backend in a CMD terminal (from project root):

```bat
.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir apps\api --host 127.0.0.1 --port 8765
```

Check `http://127.0.0.1:8765/live/status` and `http://127.0.0.1:8765/semantic/status`. If your Vosk models or semantic index are missing, use the existing instructions in `docs/transcription-lab.md`; importing/indexing is a separate opt-in step. If your old `npm run lab:transcribe` is running, stop it first.

Start desktop in a **second** terminal:

```bat
cd apps\desktop
npm run dev
```

If `node_modules` is missing, run `npm install` before `npm run dev`.

Open **Live Interview → Preparar captura Live** in the main window. In the new isolated capture window choose English/Español, check consent and click **Iniciar transcripción**. Return to the main Live page to view real-time transcript and source-backed exact/semantic suggestions. Use **Detener y cerrar captura** to stop the capture; the independent lab remains available via `npm run lab:transcribe` if you need to isolate failures.

See [exact Windows acceptance steps](docs/live-mode.md).

## Validated vs pending
- ✅ Windows loopback audio, PCM, Vosk transcription — standalone laboratory (user-verified).
- ✅ Conversational question detection and exact/semantic retrieval — standalone laboratory (user-verified; 204/204 question index).
- 🧪 Main React Live Mode integration — code and mock tests passed, **Windows not yet tested**.
- ⏭️ LLM fallback — not implemented.
- 🚫 Production packaged capture — intentionally disabled pending a separate authenticated bootstrap and audio/origin tests.

## Tests

```bat
cd apps\desktop
npm run test:electron
npm run test:audio
npm run lint:electron
npm run build
```

```bat
cd apps\api
..\..\.venv\Scripts\python.exe -m pytest -q
```

Source ZIPs exclude `node_modules`, `.venv`, Vosk models, caches, local database, recordings, credentials and any personal documents. The main window remains sandboxed with media permissions denied. All system audio capture requires explicit consent from the second window and may include sounds from unrelated apps. `setContentProtection` is best-effort, not a guarantee of screen-share invisibility. Respect your organization's policies and participants' consent.
