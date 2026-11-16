# Live Mode integration — Windows acceptance test

## Current status

Live Mode is the primary product. The integration is **IMPLEMENTED / PENDING VALIDATION**: complete acceptance in the main React window has not been confirmed.

The owner **VALIDATED** the isolated Windows lab: system audio, PCM, Vosk English, conversational question detection, source-backed exact Q&A and FastEmbed retrieval with 204 indexed questions. This does not validate the integrated main window. Spanish support is implemented, but complete integrated validation is not established. Screen-sharing compatibility is also pending; LLM fallback is planned, not implemented.

These are historical owner confirmations, not results of the documentation update. Automated/mocked tests and status endpoints do not establish hardware or conferencing behavior.

## Prerequisites
- Use the latest already-working local `.venv`, `local-data/models` (Vosk), SQLite Q&A database and FastEmbed cache from the previous project. The patch does not move, delete or reindex these.
- FastAPI runs at `http://127.0.0.1:8765`; check `/live/status` and `/semantic/status`.
- Close the previous `npm run lab:transcribe` (Vite port 5173 and the single Vosk session).
- From `apps/desktop`, run `npm run dev`. If dependencies are absent, use the [README setup](../README.md#windows-setup-cmd) after approval.
- Use a known, non-private extracted Q&A; an imported PDF alone does not provide Live Q&A. Manual search uses exact/FTS, while automatic Live uses exact/optional semantic Q&A. Preserve the existing index; do not reindex just to test integration.

## Validation
1. In the **main** Interview Copilot window, click **Live Interview → Preparar captura Live**.
2. A separate control window opens. Choose **English** or **Español**, check the explicit consent and click **Iniciar transcripción** inside this window. A second click is necessary to preserve Chromium user activation.
3. Play a non-private, clear question once using Windows system audio, e.g. `Could you explain authentication?`.
4. In the **main Live page**, inspect the final transcript and source-backed result. A normalized exact Q&A should show **Respuesta exacta**. Separately try a known related paraphrase with the prepared semantic index and expect **Posible respuesta semántica — revisar**; ambiguous/weak candidates may correctly abstain. Exact matching is not factual certification.
5. Ask an unrelated question and expect **Sin respuesta suficientemente relacionada**.
6. Click **Detener y cerrar captura** in the main page; verify that the second window closes and audio tracks/WebSocket stop. Reopen, consent and start again to verify lifecycle. Also test **Detener** inside the capture window; this path requests the last Vosk result, while closing the window need not flush it.
7. Repeat with a known Spanish Q&A and the Spanish model; record EN and ES outcomes separately.

Record PASS/FAIL, Windows/Electron version, output device, tested language and failing stage/message only. Do not include private audio or transcripts. The first-utterance check requires playing the question once, not repeating until it works. Do not mark the integration VALIDATED until the owner confirms this flow.

If text appears in the second window but not the main Live page, the likely blocker is the IPC relay. If PCM stays zero, diagnose audio permission/worklet. If Vosk status is unavailable, check the models and backend port before modifying code. Real acceptance is **not yet confirmed**.

## Current limitations
- Windows developer mode only. This version does not enable packaged production capture, and capture can include every sound played by Windows.
- The main React page does not control the initial `getDisplayMedia` call; consent and Start must occur in the capture window.
- Main-process/React Live history is memory-only and bounded; closing the app discards it. The auxiliary lab DOM accumulates results until reset; it is not uniformly bounded.
- Exact answers return stored wording with sources; semantic candidates are labeled for review. Parsers normalize/limit extracted fields and IPC limits displayed answers, so unlimited verbatim reproduction is not guaranteed.
- No LLM fallback; insufficient evidence produces a no-answer state. Current automatic Live retrieval does not use document text fragments.

## Screen-sharing exclusion — manual acceptance pending

Exclusion while remaining visible locally is a core Live requirement. The main window enables Electron `setContentProtection` by default on Windows; Settings permits toggling it and always-on-top. There is no separate compact overlay today. The capture-controls window is not content-protected.

Electron uses Windows `WDA_EXCLUDEFROMCAPTURE`; support depends on Windows version and the capture API. Windows 10 before version 2004 falls back to `WDA_MONITOR` behavior, potentially a black region rather than exclusion. Neither the setting nor `isContentProtected()` proves what another participant receives. See [architecture and platform references](architecture.md#screen-sharing-exclusion).

For **Teams, Zoom and Google Meet separately**, using non-private test content and authorized participants:

1. Record Windows, Electron and conferencing client/browser versions and monitor configuration.
2. Keep Live visible locally; enable protection. Share the full screen and inspect from another participant, not only the local preview. Repeat with window sharing where available, noting the selected window.
3. Check a meeting recording where permitted. Record whether the app is excluded, blacked out or visible; mark untested modes UNKNOWN.
4. Disable protection as a comparison, then restore it. Verify local visibility, always-on-top and Live capture still behave as expected.
5. Observe the auxiliary capture-controls window separately; do not report all application windows as excluded based on the main window alone.

No conferencing compatibility has been established by this checklist. Exclusion is best-effort, not guaranteed privacy or undetectability, and never replaces explicit audio consent or compliance with interview/platform rules.
