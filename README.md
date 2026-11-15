# Interview Copilot — cleaned development baseline

**Current status:** document retrieval and Practice are retained; Live supports manual text questions. Windows system-output capture has been **user-validated in the isolated RMS lab**. The separate **Vosk transcription lab** has also passed a real Windows speech test, confirmed by the user. Question detection has passed the user’s real Windows test; exact-Q&A answer display has passed on real Windows. Current focus: optional semantic Q&A retrieval from a local multilingual embedding model (Windows validation pending). Automatic Windows capture is **not enabled in production Live**.

This is a cleanup of the user's uploaded source, not a new finished release. No two-agent OpenCode setup, historical debug logs, model binaries or Electron test profiles are included.

## Tech stack
- React + TypeScript + Electron (Windows desktop)
- Python + FastAPI, SQLite/FTS5 (local document index and exact/lexical answers)
- Optional backend Vosk STT (already supports synthetic PCM/WebSocket tests)
- **No Docker, Chroma, LLM, auto voice capture or packaged installer yet.**
- Optional: FastEmbed multilingual embeddings stored alongside Q&A in SQLite; no vector server.

## Quick start — CMD on Windows

Backend (terminal 1):

```bat
cd apps\api
py -3 -m venv ..\..\.venv
..\..\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
..\..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8765 --reload
```

Frontend (terminal 2):

```bat
cd apps\desktop
npm install
npm run dev
```

The backend `/health` and `Knowledge Base` should work. Import `samples/interview-questions.md` for a document-backed manual query. Practice remains available.

## Verified first experiment: Windows audio

From `apps/desktop` (after `npm install`):

```bat
npm run lab:audio
```

Tick explicit consent, click **Iniciar prueba**, play a harmless sound in Windows, and inspect the live RMS meter. **This lab does not call the backend, transmit audio or save recordings.** The user has confirmed the live RMS meter detects Windows playback. See [audio-lab instructions](docs/audio-lab.md).

## Next experiment: Windows audio → local Vosk transcription

Start the backend and install the optional `requirements-live.txt` dependencies. Restore the **two Vosk model folders** from your original backup ZIP into `local-data/models/` (outside the distributed source archive). Start the backend on 127.0.0.1:8765 as above, and check `http://127.0.0.1:8765/live/status` shows `available: true` for your language.

Close any other Vite instance running on port 5173, then launch the *separate* transcription lab:

```bat
cd apps\desktop
npm run lab:transcribe
```

Select English or Spanish, accept explicit consent, start capture, and play **non-private synthetic speech**. The lab shows the audio track, RMS meter, PCM frame count, partial/final Vosk text, and original Q&A answers with sources; semantic results, when indexed, are explicitly labeled as suggestions. Click **Detener** when finished. It streams audio only to the local FastAPI process and does not write recordings; The backend looks up exact Q&A matches when it detects a question, and the lab displays the original answer with its document source when available. See [transcription lab](docs/transcription-lab.md).

**Status: audio capture, Vosk speech recognition, and question detection user-confirmed PASS on Windows; document answer display has been user-confirmed PASS; early exact-answer detection from stable partials still needs real Windows validation.** This is a dev-only lab, not production Live.

## Tests

```bat
cd apps\api
..\..\.venv\Scripts\python.exe -m pytest -q
```

```bat
cd apps\desktop
npm run test:electron
npm run test:audio
npm run lint:electron
npm run build
```

Backend Vosk is optional (`apps/api/requirements-live.txt`) and model data stays outside Git. The original RMS audio lab was validated by the user on Windows. The Vosk transcription lab and question detection have been validated with real Windows playback.

## Included and excluded

Included: application source, tests for currently retained modules, synthetic fixtures, concise docs, sample knowledge document and a standalone audio lab.

Excluded: `.opencode` agents/skills, `opencode.jsonc`, previous instruction prompts, 115 KB of failed-capture logs, old isolated broker/IPC implementation and its tests, Python/mypy/pytest caches, Electron Chromium user profiles, dev build output, Vosk model binaries, personal/local data, `node_modules` and any `.git` directory.

**The old captured permissions design and test count must not be represented as current functionality.** Keep the original three ZIPs as a rollback source. The excluded Vosk models and user documents may still be needed on your PC: do not delete their original copies.

## Privacy and product limitations

The local API is for development. It listens on localhost and restricts browser origins, but has no production authentication/bootstrap yet. Do not expose it to external networks.

Electron capture exclusion via `setContentProtection` is best effort and not guaranteed in screen-sharing tools. Get consent for live audio and follow interview policies. Live LLM generation remains future work; semantic candidates are available only when an optional local index is prepared and are not verified exact matches.

## Previously validated acceptance test — exact document-backed answer

Import `samples/interview-questions.md` using `curl.exe -X POST -F "file=@samples/interview-questions.md" http://127.0.0.1:8765/documents` from the project root (HTTP 409 means already imported). Start the API and `npm run lab:transcribe`, say “What is authentication?”, and verify the **original answer and filename** appear. Say “What is Python?” and verify the honest **Sin coincidencia exacta** state. The existing backend supplies answers/sources; this update only renders them. Nothing is added to production Live until Windows verification. See `docs/transcription-lab.md`.


## Current experiment: optional semantic search for stored Q&A (Windows NOT TESTED)

This patch does not change Electron capture, PCM, Vosk or question detection.
Index only the *questions* from imported Q&A documents (their original answers and source stay in SQLite).

From project root, with `.venv` already created (run these commands **once**):

```bat
.venv\Scripts\python.exe -m pip install -r apps\api\requirements-semantic.txt
```

Restart FastAPI after installing dependencies. Ensure your Q&A document is already imported.
**The next command explicitly authorizes the first local model download** (~220 MB model before dependency/cache overhead); it does not send your interview documents to an LLM provider. From CMD:

```bat
curl.exe -X POST http://127.0.0.1:8765/semantic/index -H "Content-Type: application/json" -d "{\"allow_download\":true}"
```

Check `http://127.0.0.1:8765/semantic/status` and verify `indexed` equals `questions`.
Then start `npm run lab:transcribe` and ask one question from the imported document **in different words**. It should display a labeled **possible semantic answer** with original question and provenance, not claim certainty. Also test an unrelated question; it should not show a fabricated answer.

The model is `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (English and Spanish), run locally through FastEmbed. FastEmbed is an **optional** dependency. The model is only downloaded with `allow_download: true`. During live queries, cached model files are used with `local_files_only=True`, and only vectorized questions are stored in SQLite. After importing a new Q&A document, call `/semantic/index` again with `{}` to index missing entries without downloading.

No Chroma server or background indexing. Similarity threshold and runner-up margin are conservative starting values, **not validated accuracy metrics**; if the test returns no result, capture the question and expected document title (no private audio) for calibration. Exact matches still take priority, while partial transcriptions intentionally use exact-only lookup. Deleting a document removes its associated vector rows.
