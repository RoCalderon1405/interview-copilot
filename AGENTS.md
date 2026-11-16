# Interview Copilot — Development rules

## Current milestone
Integrate the user-validated audio → Vosk → conversational-question detection → exact/semantic retrieval flow into the **main Live Mode**. Keep the pipeline small and test it on Windows. No LLM fallback yet.

## Validated by the user (Windows)
- Windows system audio loopback, PCM 16 kHz, Vosk EN speech transcription: PASS in the isolated lab.
- Conversational questions, exact Q&A with source, semantic matching using a fully indexed 204-question SQLite index: PASS in the isolated lab.
- Production-style React Live Mode integration: **NOT YET TESTED ON WINDOWS**.

## Rules
1. Make small vertical slices with a real-world acceptance test; automated tests alone do not establish Windows functionality.
2. Preserve the working `audio-lab/transcribe.js` capture and Vosk/semantic backend. Don't rewrite them without evidence.
3. Live capture requires a click and explicit consent **inside the capture window**. It captures **all Windows output**, not an individual application.
4. Isolate capture in its own nonpersistent Electron session. Main React renderer stays sandboxed, denies media permissions and cannot call display capture.
5. Capture window only sends strictly validated text/status/suggestion events to main; do not relay raw audio/credentials via IPC, persist transcripts or log private content.
6. Exact Q&A responses remain original and source-backed. Semantic matches are labeled **possible answers to review**. No match means no answer, not a hallucination.
7. No new agents, project generators, Docker, vector DB services, or unrelated changes. Maintain simple documentation; avoid generated/cache files in Git.
8. FastEmbed model download must remain opt-in and local. Models, documents, secrets, session DB and embeddings remain outside distributable ZIPs and Git.
9. Current integrated capture is for Windows **development mode**, via the Vite local origin. Packaged production support requires separate auth/CORS validation and an independent acceptance test.

## Current acceptance test
- Keep the already working FastAPI/Vosk process running at 127.0.0.1:8765 and the existing indexed SQLite database.
- Stop the old `lab:transcribe` process first to free port 5173.
- `cd apps/desktop && npm run dev`; open **Live Interview → Preparar captura Live**.
- In the separate capture-controls window choose language, consent and press **Iniciar transcripción**.
- Read a technical question from Windows system audio once; in the **main Live page**, verify transcript and source-backed answer (exact or labeled semantic), then stop.
- Windows remains **NOT TESTED** until the user confirms this exact flow. Report failures with stage and message, not private transcript.

## Checks
- `cd apps/api && python -m pytest -q`
- `cd apps/desktop && npm run test:electron && npm run test:audio && npm run lint:electron && npm run build`
- If `npm run build` is blocked by missing local native dependencies, state that limitation and require `npm install` on Windows, then rebuild.
