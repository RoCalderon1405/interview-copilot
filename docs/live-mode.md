# Live Mode integration — Windows acceptance test

## Prerequisites
- Use the latest already-working local `.venv`, `local-data/models` (Vosk), SQLite Q&A database and FastEmbed cache from the previous project. The patch does not move, delete or reindex these.
- FastAPI runs at `http://127.0.0.1:8765`; check `/live/status` and `/semantic/status`.
- Close the previous `npm run lab:transcribe` (Vite port 5173 and the single Vosk session).
- From `apps/desktop`, run `npm run dev`. No new dependencies were added; if npm packages are absent, run `npm install` first.

## Validation
1. In the **main** Interview Copilot window, click **Live Interview → Preparar captura Live**.
2. A separate control window opens. Choose **English** or **Español**, check the explicit consent and click **Iniciar transcripción** inside this window. A second click is necessary to preserve Chromium user activation.
3. Play a non-private, clear question once using Windows system audio, e.g. `Could you explain authentication?`.
4. In the **main Live page**, inspect the final transcript and a source-backed semantic suggestion labeled **Posible respuesta semántica**. A direct Q&A should show **Respuesta exacta**.
5. Ask an unrelated question and expect **Sin respuesta suficientemente relacionada**.
6. Click **Detener y cerrar captura** in the main page; the second window closes, releasing the tracks and WebSocket.

If text appears in the second window but not the main Live page, the likely blocker is the IPC relay. If PCM stays zero, diagnose audio permission/worklet. If Vosk status is unavailable, check the models and backend port before modifying code. Real acceptance is **not yet confirmed**.

## Current limitations
- Windows developer mode only. This version does not enable packaged production capture, and capture can include every sound played by Windows.
- The main React page does not control the initial `getDisplayMedia` call; consent and Start must occur in the capture window.
- Live history is memory-only and bounded; closing the app discards it.
- No LLM fallback yet; only original Q&A sources or a clearly labeled no-answer state.
