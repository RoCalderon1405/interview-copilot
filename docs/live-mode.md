# Live Mode integration — Windows acceptance test

## Current status

Live Mode is the primary product. The integration is **IMPLEMENTED / PARTIALLY VALIDATED**: complete acceptance in the main React window has not been confirmed. Task status is maintained only in the [official roadmap board](roadmap.md#official-task-board).

The owner **VALIDATED** the isolated Windows lab: system audio, PCM, Vosk English, conversational question detection, source-backed exact Q&A and FastEmbed retrieval with 204 indexed questions.

The owner subsequently confirmed these **integrated Windows cases**: system audio capture, English transcription, Electron-to-React events, conversational question detection in tested cases, and exact retrieval with document sources. These confirmations do not establish reliable detection for arbitrary continuous speech or full acceptance of DET-001 (`3bc2f05`). Integrated semantic retrieval is not established by the lab's 204-question validation alone.

**Still pending:** complete integrated Spanish validation, stop/restart lifecycle acceptance, and Teams/Zoom/Google Meet screen-sharing checks. AI-001B automatic local Ollama fallback is implemented, disabled by default and validated only with fake providers/mocked HTTP; real-provider Windows acceptance is pending.

These are owner confirmations, not new executions in this documentation task. Automated/mocked tests and status endpoints do not establish hardware or conferencing behavior.

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
5. With generation disabled (the default), ask an unrelated question and expect **Sin respuesta suficientemente relacionada**. Test optional Ollama separately using the pending checklist below.
6. Click **Detener y cerrar captura** in the main page; verify that the second window closes and audio tracks/WebSocket stop. Reopen, consent and start again to verify lifecycle. Also test **Detener** inside the capture window; this path requests the last Vosk result, while closing the window need not flush it.
7. Repeat with a known Spanish Q&A and the Spanish model; record EN and ES outcomes separately.

Record PASS/FAIL, Windows/Electron version, output device, tested language and failing stage/message only. Do not include private audio or transcripts. The first-utterance check requires playing the question once, not repeating until it works. Do not mark the integration VALIDATED until the owner confirms this flow.

If text appears in the second window but not the main Live page, investigate the IPC relay. If PCM stays zero, diagnose audio permission/worklet. If Vosk status is unavailable, check the models and backend port before modifying code. These are regression-isolation checks; the owner has confirmed the integrated cases above, but **complete acceptance remains pending**.

## Current limitations
- Windows developer mode only. This version does not enable packaged production capture, and capture can include every sound played by Windows.
- The main React page does not control the initial `getDisplayMedia` call; consent and Start must occur in the capture window.
- Main-process/React Live history is memory-only and bounded; closing the app discards it. The auxiliary lab DOM accumulates results until reset; it is not uniformly bounded.
- Exact answers return stored wording with sources; semantic candidates are labeled for review. Parsers normalize/limit extracted fields and IPC limits displayed answers, so unlimited verbatim reproduction is not guaranteed.
- Optional local Ollama fallback runs only after final no-evidence, with explicit enabled/model configuration. Disabled, unavailable or failed generation preserves no-answer. Generated suggestions are unverified, separately labeled and have no documentary source. Automatic Live retrieval still does not use document text fragments. The capture/lab window shows documentary results; generated cards are displayed in the main React Live page.
- DET-001 recognizes marked transitions/enumerations and some consecutive questions, not arbitrary question boundaries. Unpunctuated questions can remain combined, be missed without recognized markers, or include explanations/spoken answers. For example, `one what is TypeScript TypeScript adds types to JavaScript two what is authentication authentication verifies identity` yields two candidates that still include their spoken answers. This prevents exact matching to the bare questions; semantic retrieval may recover but is not guaranteed. This trailing-answer limitation predates DET-001.
- Vosk errors such as `two` becoming `to` can hide an enumeration. No unrestricted word correction is implemented. Relevant context must not be removed merely to force an exact match.
- Detection remains heuristic: conversational statements, reported/quoted speech and subordinate interrogatives can cause false positives or omissions. Existing guards reduce risk, not eliminate it. Partial detection is unchanged by DET-001: stable repeated candidates can trigger exact-only early answers; semantic lookup waits for finals.

### Automatic Ollama fallback — manual acceptance pending (AI-001B)

Use only synthetic questions and an approved already-installed local model; no installation/download or reindex is needed. See [configuration and limits](../README.md#optional-automatic-local-generation-ai-001a--ai-001b). Configure the separately operated Ollama server with `OLLAMA_NO_CLOUD=1`. Preserve the existing database and model caches.

1. Start with fallback disabled; confirm the no-evidence behavior and working audio. Enable/model-configure the backend explicitly and restart it; do not infer enablement from `.env` alone.
2. Test exact Q&A and an accepted semantic candidate: stored wording/source remain unchanged, with no Ollama calls. Unknown partials never generate; an eligible final without documentary evidence produces **Sugerencia generada por IA — revisar**, provider/model and no documentary source in the main window.
3. Repeat in EN/ES. Review natural B2 English/natural Spanish, practical examples, uncertainty and absence of invented personal experience. Measure cold/warm latency and timeout frequency; record timing/status only, not private text.
4. During slow generation, confirm PCM/frame metrics and transcription continue. Ask newer eligible questions rapidly; only the latest pending generation should survive, correctly associated with its question. A newer documentary question also invalidates older generation.
5. Test timeout and unavailable Ollama: no fabricated response, capture stays active and the no-evidence card remains. Stop inside the capture window, close it, disconnect and finish the session while generation is pending; no late generated result should appear. Restart capture and check for stale/miscorrelated cards. Stop-flushed finals remain documentary-only.
6. Verify generation remains memory-only in application handling and that Ollama is independently configured for local operation/logging. Client cancellation does not prove that the server stopped inference instantly. Known detector limitations below still apply: only its detected candidate is sent, but it may include trailing spoken explanation; no additional context is attached.

Record PASS/FAIL, versions, local model, language, timings and failing stage/message only. These checks are **PENDING**, not established by automated tests. No new conferencing-exclusion claim follows from fallback integration.

### Backend event-contract validation (TEST-001)

The two previously observed EN/ES Vosk failures were incorrect test expectations, not production timestamp defects. Early exact suggestions explicitly carry `from_partial: true` and `last_word_end_seconds: None`. The `final` transcript still carries Vosk word timing even when deduplication suppresses an identical final suggestion. A suggestion originating from a final carries that final's timestamp. No production behavior or timestamps were changed.

TEST-001 reproduced both failures, then aligned `test_real_vosk_pipeline_partial_final_source_and_no_audio_persistence` with this contract. The test requires a correctly recognized final with positive, audio-duration-bounded timing, one source-backed exact suggestion, correct partial/final event ordering and the existing non-persistence checks. Deterministic transport tests also verify null early timing, final timing preservation and propagation to final-origin suggestions.

Automated results on 2026-11-16 using synthetic fixtures and the existing local Vosk models:
- `tests/test_live.py`: **117 passed, 0 failed, 0 skipped** (previously 115 passed, 2 failed).
- Full backend suite: **158 passed, 0 failed, 0 skipped** (previously 156 passed, 2 failed). Totals overlap; do not add them.
- One existing Starlette/httpx deprecation warning remains; no dependency changes were made.

These tests do not replace real Windows capture, complete Spanish integration or stop/restart acceptance. DET-001 and screen-sharing exclusion are not fully validated by this result.

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
