# Live Mode integration — Windows acceptance test

## Current status

Live Mode is the primary product. The integration is **IMPLEMENTED / PARTIALLY VALIDATED**: complete acceptance in the main React window has not been confirmed. Task status is maintained only in the [official roadmap board](roadmap.md#official-task-board).

The owner **VALIDATED** the isolated Windows lab: system audio, PCM, Vosk English, conversational question detection, source-backed exact Q&A and FastEmbed retrieval with 204 indexed questions.

The owner subsequently confirmed these **integrated Windows cases**: system audio capture, English transcription, Electron-to-React events, conversational question detection in tested cases, and exact retrieval with document sources. These confirmations do not establish reliable detection for arbitrary continuous speech or full acceptance of DET-001 (`3bc2f05`). Integrated semantic retrieval is not established by the lab's 204-question validation alone.

**Still pending:** complete integrated Spanish validation, stop/restart lifecycle acceptance, and Teams/Zoom/Google Meet screen-sharing checks. AI-001B automatic local Ollama fallback is implemented, disabled by default and validated only with fake providers/mocked HTTP; real-provider Windows acceptance is pending. STT-001A selectable CPU Whisper is implemented; [paced synthetic latency evidence and pending human/Windows acceptance](#stt-001a--live-integration) are separate from the earlier offline evaluation.

These are owner confirmations, not new executions in this documentation task. Automated/mocked tests and status endpoints do not establish hardware or conferencing behavior.

## Prerequisites
- Use the latest already-working local `.venv`, `local-data/models` (Vosk), SQLite Q&A database and FastEmbed cache from the previous project. The patch does not move, delete or reindex these.
- FastAPI runs at `http://127.0.0.1:8765`; check `/live/status` and `/semantic/status`.
- Close the previous `npm run lab:transcribe` (Vite port 5173 and the single Vosk session).
- From `apps/desktop`, run `npm run dev`. If dependencies are absent, use the [README setup](../README.md#windows-setup-cmd) after approval.
- Use a known, non-private extracted Q&A; an imported PDF alone does not provide Live Q&A. Manual search uses exact/FTS, while automatic Live uses exact/optional semantic Q&A. Preserve the existing index; do not reindex just to test integration.

## Validation
1. In the **main** Interview Copilot window, click **Live Interview → Preparar captura Live**.
2. A separate control window opens. Choose **Vosk (default)** or configured **Faster-Whisper Small (CPU INT8)**, then **English** or **Español**, check the explicit consent and click **Iniciar transcripción** inside this window. A second click is necessary to preserve Chromium user activation. Wait for the selected engine to become ready before playing speech.
3. Play a non-private, clear question once using Windows system audio, e.g. `Could you explain authentication?`.
4. In the **main Live page**, inspect the final transcript and source-backed result. A normalized exact Q&A should show **Respuesta exacta**. Separately try a known related paraphrase with the prepared semantic index and expect **Posible respuesta semántica — revisar**; ambiguous/weak candidates may correctly abstain. Exact matching is not factual certification.
5. With generation disabled (the default), ask an unrelated question and expect **Sin respuesta suficientemente relacionada**. Test optional Ollama separately using the pending checklist below.
6. Click **Detener y cerrar captura** in the main page; verify that the second window closes and audio tracks/WebSocket stop. Reopen, consent and start again to verify lifecycle. Also test **Detener** inside the capture window: Vosk flushes its last result, while Whisper cancels unfinished/queued speech; closing the window need not flush either engine.
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

## STT-001A — runtime compatibility gate and CPU-only evaluation

Read-only checks on 2026-11-16 established:

- **VALIDATED:** existing `.venv` is CPython 3.14.7 AMD64 on Windows 11 build 26100; Vosk 0.3.45 is installed. Faster-Whisper, CTranslate2 and PyAV are not installed. No packages or models were downloaded/installed and no environment settings were changed.
- **VALIDATED:** NVIDIA reports an RTX 4050 Laptop GPU with 6141 MiB VRAM and driver 610.88, advertising CUDA driver capability 13.3. CPU is an AMD Ryzen 7 7445HS (6 cores / 12 logical processors). Driver capability is not evidence of installed CUDA runtime libraries or successful inference.
- **VALIDATED (published metadata only):** [CTranslate2](https://pypi.org/pypi/ctranslate2/json) 4.9.0 publishes `cp314-cp314-win_amd64`; [PyAV](https://pypi.org/pypi/av/json) 19.0.2 publishes `cp312-abi3-win_amd64`, compatible by tag with standard CPython 3.14. [Faster-Whisper](https://pypi.org/pypi/faster-whisper/json) 1.2.1 declares Python >=3.9 and CTranslate2 >=4,<5. This is not an installed dependency-resolution/import/inference test; no versions are selected or pinned yet.
- **BLOCKER:** `cublas64_12.dll`, `cublasLt64_12.dll` and `cudnn64_9.dll` were not found on PATH; CUDA_PATH is unset, `nvcc` is not discoverable, and the standard NVIDIA CUDA Toolkit/cuDNN directories are absent. Libraries elsewhere are **UNKNOWN**. [Faster-Whisper's GPU guidance](https://github.com/SYSTRAN/faster-whisper#gpu) requires CUDA 12 cuBLAS and cuDNN 9. CTranslate2's installation page contains differing cuDNN guidance; verify the chosen release's actual binary requirements before any approved installation. GPU execution is not validated.

**At the initial gate (`febae20`):** nothing for STT-001A was implemented. Inspection found capture click → AudioWorklet → 100 ms PCM16 mono 16 kHz frames → single-use session/language token → WebSocket → Vosk → question detection → exact/optional semantic retrieval → opt-in Ollama on final no-evidence. Vosk inference ran in a thread, but the connection loop awaited it before receiving the next frame; Faster-Whisper needed bounded reception/inference separation rather than simply replacing that call. Tokens then bound language, not a selectable provider. This historical finding is superseded by the integration below, not by the offline evaluation alone.

The initial gate above is historical evidence from `febae20`. The owner subsequently approved **CPU-only evaluation**, isolated Faster-Whisper installation and downloading Whisper Small multilingual. GPU validation remains blocked/out of scope. This approval does **not** authorize Live integration, CUDA installation, changing the existing `.venv`, or Deepgram work.

### CPU evaluation method and reproduction

Evaluation tooling lives in `tools/stt_eval/` and does not import or modify Live code. Environment, model, generated synthetic WAVs, hashes, hypotheses and machine-readable results remain under ignored `local-data/stt-evaluation/`; none belongs in source ZIPs. The original `.venv` is used only to execute the existing Vosk package, not to install dependencies. Audio is deliberately persisted **only for this synthetic offline evaluation**, not by Live capture.

- Fixed corpus: six clean questions per language (one existing synthetic baseline and five technical questions covering REST APIs, TypeScript, database indexes, race conditions/mutexes and distributed retries). New speech uses installed Windows SAPI Zira EN-US and Sabina ES-MX, default rate. No human recordings, cloud TTS, transcription uploads, or production documents.
- Robustness probes per language: the API question with deterministic additive white noise at 15 dB SNR, three seconds of silence, and 100 ms of silence. Noise is not a realistic room simulation. Each engine receives the identical hashed PCM16 mono 16 kHz file, with no resampling.
- Whisper uses Small **multilingual**, CPU `int8`, one worker, two/four inference threads, beam size 1, temperature 0, explicit `en`/`es`, no previous-text conditioning and no VAD. CUDA is masked and the actual model device is asserted to be CPU. These configurations work without a dedicated GPU; two threads are a budget sensitivity check, not a measurement on a separate low-end computer.
- Vosk uses the existing small EN-US 0.15 / ES 0.42 models, new recognizers per utterance, word timings and the existing 100 ms feed/partial/final API sequence. Its `OMP_NUM_THREADS` is set to 1; this is not a guarantee of single-threaded internals.
- One fresh child process per provider/language/thread configuration, import+model-load timing, one separately reported first utterance, then three measured passes. Model caches are not cleared: these are fresh-process/cached-disk loads, **not** first-ever cold-disk or post-reboot timings. Audio reading/hash checks happen outside recognition timing. No GPU inference occurs.
- Accuracy is corpus-weighted WER/CER using case/diacritic/punctuation/whitespace normalization, without synonym or technical-term corrections. CER includes normalized spaces. Strict tokenization can penalize spelled acronyms and English words pronounced by Spanish TTS. Exact normalized utterance rate is separate. Silence uses empty-output checks, not undefined WER.
- Latency includes Vosk recognizer creation/full PCM feeding/final flush or Whisper float conversion/**complete lazy segment iteration**. Real-time factor (RTF) is decode wall time divided by clip duration. It is **offline utterance decode cost**, not streaming endpoint delay, time-to-first-partial, Windows capture/IPC latency or final question-to-answer latency. No speech segmenter is implemented or evaluated here.
- CPU is process CPU time (all native threads) divided by wall time: 100% means one fully occupied logical core; machine-normalized utilization divides by the 12 logical CPUs. These are process averages, not system-wide CPU measurements. Windows working set is sampled every 20 ms (MiB); process-lifetime peak is also retained. RSS includes interpreter/native libraries/model and is neither model-file size nor whole-machine RAM. Monitoring overhead is included and can dominate 100 ms silence probes.
- Limits: small synthetic corpus, one machine, sequential rather than randomized provider order, existing desktop/background workloads and Balanced power plan. No human-speech accuracy, lower-end CPU, thermal/battery, long-session buffering/cancellation or integrated Live acceptance is established.

From the repository root in Windows CMD, after approval (the first commands create/install/download; skip them when reusing this evaluation):

```bat
.venv\Scripts\python.exe -m venv local-data\stt-evaluation\venv
local-data\stt-evaluation\venv\Scripts\python.exe -m pip install --only-binary=:all: -r tools\stt_eval\requirements-cpu.txt
local-data\stt-evaluation\venv\Scripts\python.exe tools\stt_eval\download_model.py
local-data\stt-evaluation\venv\Scripts\python.exe -m unittest discover -s tools\stt_eval -v
local-data\stt-evaluation\venv\Scripts\python.exe tools\stt_eval\evaluate.py prepare
local-data\stt-evaluation\venv\Scripts\python.exe tools\stt_eval\evaluate.py run
```

`prepare` uses local SAPI COM commands without changing Windows execution policy. `run` forces offline local model loading; it never downloads or falls back to a different engine/device. Do not run unrelated tests/builds concurrently with measurement. Inspect the ignored `manifest.json`, provider JSON files and `summary.json` for per-clip hashes, synthetic references/hypotheses, repeats, timing/CPU/RSS and aggregate counts. Retain the same WAVs for reruns rather than synthesizing again on a different voice version.

### CPU evaluation results — VALIDATED, synthetic/offline only

Executed 2026-11-16 on Windows 11 Pro 10.0.26100, Ryzen 7 7445HS (6 cores / 12 logical processors), approximately 15.27 GiB OS-visible RAM, Balanced power plan. About 2.39 GiB was free at the pre-run inventory; other desktop applications remained open. Timed model runs were sequential; regression tests/builds were run only afterward. The installed RTX 4050 was masked/not used; a physically GPU-less or lower-end machine was **not** tested.

Isolated runtime: Python 3.14.7, Faster-Whisper 1.2.1, CTranslate2 4.9.0, PyAV 19.0.2, NumPy 2.5.5, ONNX Runtime 1.32.0. `pip check` passed. CPU compute types reported: `float32`, `int8`, `int8_float32`. Small multilingual is pinned to `Systran/faster-whisper-small` revision `536b0662742c02347bc0e980a01041f333bce120`; `model.bin` is 483,546,902 bytes, SHA-256 `3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671`. No CUDA installation or changes to application requirements occurred. The original `.venv` package inventory/metadata hashes match the pre-evaluation inventory, and no files inside it had modification times after isolated-environment creation.

The 18 unique clips contain 68.46 seconds of audio; clean questions range from 2.095 to 5.265 seconds. Six configurations × nine clips × three repeats produced **162 warm recognitions**, plus six separate first-utterance runs. Each clean configuration below has six unique clips / 18 observations; repeated readings are not independent accuracy samples. WER/CER are percentages; latency is median / maximum **offline decode seconds**, CPU is mean percent of one logical core, and RSS is peak sampled inference MiB:

- **Vosk EN:** WER **20.34**, CER **4.62**, exact **16.67%**; latency **1.135 / 1.637 s**, median RTF **0.271**; CPU **99.2%** (8.27% of this machine), RSS **188.73 MiB**.
- **Vosk ES:** WER **15.66**, CER **4.86**, exact **33.33%**; latency **0.607 / 0.967 s**, median RTF **0.126**; CPU **99.5%** (8.29% machine), RSS **157.52 MiB**.
- **Whisper INT8, 2 threads, EN:** WER **3.39**, CER **0.27**, exact **83.33%**; latency **2.624 / 5.218 s**, median RTF **0.618**; CPU **183.5%** (15.29% machine), RSS **474.27 MiB**.
- **Whisper INT8, 2 threads, ES:** WER **3.03**, CER **0.25**, exact **83.33%**; latency **2.146 / 2.309 s**, median RTF **0.440**; CPU **197.1%** (16.43% machine), RSS **475.41 MiB**.
- **Whisper INT8, 4 threads, EN:** WER **3.39**, CER **0.27**, exact **83.33%**; latency **1.676 / 1.818 s**, median RTF **0.366**; CPU **393.7%** (32.81% machine), RSS **478.06 MiB**.
- **Whisper INT8, 4 threads, ES:** WER **3.03**, CER **0.25**, exact **83.33%**; latency **1.815 / 1.955 s**, median RTF **0.375**; CPU **394.2%** (32.85% machine), RSS **478.60 MiB**.

Technical-only WER (five clean questions/language, excluding the baseline): Vosk **21.43% EN / 17.51% ES**; Whisper **3.57% EN / 3.39% ES**, identical at two/four threads. Whisper's clean EN errors are `back-off` versus `backoff`; clean ES errors are `APIRest` versus `API REST`. Thus the remaining clean WER mostly measures token boundaries, not wrong technical content. Vosk additionally confused technical terms such as `mutex` and `TypeScript`; its acronym/compound spacing also inflates strict WER. Do not interpret this metric as semantic answer correctness or an exact-retrieval acceptance test.

**Loading and resource headroom:** Vosk import+load took **0.495 s EN / 0.532 s ES**; its first baseline recognition took **0.725 / 0.486 s**. Whisper loads were **15.560 / 1.589 s** at two threads and **1.466 / 1.284 s** at four threads (EN/ES); corresponding first-baseline decode times were **2.506 / 2.219 s** and **1.614 / 1.772 s**. The initial 15.560 s load consumed only 2.859 CPU seconds: its extra wall time is an **unattributed startup outlier**, not evidence of normal warm load or a GPU blocker. Whisper process-lifetime peak working set was **694.31–695.41 MiB**, versus Vosk **188.79 MiB EN / 157.53 MiB ES**; load can transiently use more RAM than inference. These are standalone processes, not combined backend/Ollama memory budgets.

**Robustness and tails:**

- Noisy API question (one unique clip/language, three repeats/configuration): Vosk WER **25.00% EN / 27.27% ES**; Whisper **0.00% EN / 18.18% ES** at both thread counts. Spanish Whisper joined/misheard the English acronym (`APIRES`); one noisy example does not establish general noise robustness.
- All **36 silence/short-silence recognitions** returned empty output. Without VAD, Whisper still spent median **1.49–2.34 s** decoding 100 ms of silence; passing the empty-output test does not make frame-by-frame inference viable or prove freedom from hallucinations.
- Two-thread English exceeded RTF 1 in **6/21 speech recognitions** (including the noisy clip), with worst RTF **2.095**; the noisy maximum decode was **5.906 s**. Four-thread speech RTF stayed below 1 in all measured clips (worst **0.762 EN / 0.541 ES**). Two-thread Spanish worst speech RTF was **0.689**. These small-sample maxima are not guaranteed production bounds or p95 estimates.

**Automated checks:** eight dependency-free evaluation unit tests passed, including mocked CPU-only/offline EN/ES configuration, lazy-inference timing, weighted error scoring, silence and PCM validation. All **303 backend**, **9 Electron**, **3 UI rendering** and **2 PCM** tests passed with no failures/skips. Electron syntax checks and TypeScript/Vite build passed. Existing Starlette/httpx deprecation and classic capture-script Vite bundling warnings remain. No Live code, existing Vosk model, database/index or main `.venv` file was changed.

### Recommendation — conditional go for an opt-in prototype, not a default switch

The measured technical-transcription improvement justifies a **separately approved** integration experiment with CPU Small INT8, initially four threads on this class of CPU. Keep Vosk as the default and explicit working alternative. Do **not** declare STT-001A integrated, production-ready or accepted on low-end/no-dedicated-GPU hardware from this test. Two-thread English lacks reliable real-time headroom here; four threads cost about four logical cores and ~695 MiB peak before concurrent retrieval/Ollama/desktop costs.

Before proceeding, the owner should agree on an acceptable end-of-question delay and validate non-private **human-spoken** EN/ES questions (accents, technical acronyms, fast speech and conference audio), first-start latency and actual lower-end CPU hardware. A later approved integration must avoid inference on raw 100 ms frames: use bounded speech segmentation with silence gating, a bounded receive/worker queue and explicit overload/cancellation behavior; measure endpoint delay plus decode, rather than citing offline RTF alone. Validate four-thread contention with capture and configured Ollama, memory pressure, stop/restart and provider/session binding. No such segmenter, selector or provider abstraction has been implemented in this evaluation.

**Evaluation stop point (`2f7545f`):** the evaluation was reported before Live changes. The owner subsequently authorized the integration below. No CUDA, automatic cloud fallback or Deepgram integration.

### Integration acceptance checklist

1. Verify the approved runtime imports on Windows/Python 3.14, actual CTranslate2 CPU/CUDA compute types and local-only multilingual model loading; record versions and timing, not private content. No automatic downloads.
2. Rerun the complete backend suite and desktop Electron/audio tests, Electron lint and frontend build after integration, including mocked provider authorization, EN/ES segmentation, bounded buffering and cancellation cases. Integration test evidence is recorded below; it does not replace human/Windows acceptance.
3. In the capture window, choose each provider and EN/ES before the real consent/Start click; verify Vosk remains default, unavailable selections fail clearly, and provider/language cannot be switched within the authenticated session.
4. With synthetic Windows output, measure cold/warm first-final latency, silence behavior and forced segment limits. During slow inference verify PCM continues with bounded buffering and explicit overload handling; stop, disconnect and restart without stale results or continuing capture.
5. Repeat existing exact/source-backed, semantic-review, no-evidence and configured Ollama acceptance cases for both languages/providers. Preserve Vosk partial/final contracts; do not fabricate Whisper partials or trigger generation on stop-flushed finals. Check no audio persistence or transcript logging.
6. Retain the separate conferencing-exclusion acceptance below; this task establishes no screen-sharing guarantee. Record PASS/FAIL and failing stage/message only. Deepgram remains outside STT-001A.

## STT-001A — Live integration

**IMPLEMENTED:** Vosk-default provider selector in the existing capture window; provider/language/session-bound single-use grants; per-provider availability and clear rejection without automatic fallback. The original capture click, AudioWorklet/PCM conversion, origin/session isolation and restricted Electron relay remain in place. No CUDA, new installation, model download, Deepgram or database reindex was performed. The approved isolated Python/Small multilingual model is reused via [explicit configuration](../README.md#optional-faster-whisper-live-setup-stt-001a), leaving the existing `.venv` intact.

Speech contracts/segmentation/pump live in `application/stt.py`; Vosk and CPU Whisper implementations live in infrastructure; transport retains authorization, existing event translation and the unchanged question/RAG/Ollama callback. See [architectural trade-offs](architecture.md#module-responsibilities-today). A terminable local Whisper subprocess is chosen over abandoning native thread inference; it reloads its model for each connection. Vosk's native frame algorithm/cache is moved, not rewritten; its calls are drained on teardown.

Limits: 20 ms energy analysis, RMS threshold 0.008, 200 ms pre-roll/minimum voiced duration, 500 ms end silence, 8 s maximum PCM segment. Whisper has one active / one pending segment; Vosk has 64,000 queued bytes / 20 frames. The browser retains its send-buffer bound, and the documented Uvicorn command limits WS messages/queue to 64,000 bytes / four messages. Overflow stops with `speech_overloaded` (1013), never silent audio dropping or provider switching. A forced segment cut may split words; it is transcript/documentary-only, without Ollama generation or an EOS metric. Energy gating is not robust VAD: quiet speech, noise and long natural pauses remain acceptance risks.

Whisper native startup/inference deadlines are 30 s / 10 s; stop/disconnect/error/session finish cancel work, suppress late text and terminate/drain/reap the worker before releasing the single slot. Startup is also watched for disconnect/stop. Vosk explicit stop still flushes documentary-only; Whisper stop discards unfinished/queued segments. Capture-attempt revisions also prevent late permission/worklet/token callbacks from reviving stopped or replaced capture. Native CPU inference has no RAG/LLM dependency or transcript logging/persistence.

### Executed checks and end-of-speech latency (2026-11-16)

- **VALIDATED, automated:** 339 backend tests passed, including 36 new speech cases; nine Electron, five capture-window lifecycle/selection and two PCM tests, three React rendering tests, and eight existing evaluation unit tests passed. Electron syntax and TypeScript/Vite build passed. Existing Starlette/httpx deprecation and classic-script Vite bundling warnings remain. The transient Windows pipe-cleanup warning found during development was fixed by draining/closing subprocess pipes as well as waiting for exit.
- New coverage includes immutable provider/language authorization, unsupported/unavailable selections, EN/ES CPU configuration, local-only loading, complete lazy native recognition, bounded silence/short input/hard cuts, independent byte/item backpressure, slow inference with continued PCM reception, cancellation during startup/inference, native timeout/reaping, exact/semantic priority, opt-in Ollama and no generation from forced cuts. Existing Vosk partial/final/timestamp regressions pass. Two legacy flood-style Vosk fixtures now pace input to respect the bounded receiver; their transcript/retrieval assertions are unchanged.
- **VALIDATED, actual CPU worker through paced ASGI WS transport (not physical capture/TCP):** `tools/stt_eval/live_latency.py` replayed six known synthetic questions per language (five technical + baseline), three passes: **18 EN + 18 ES** recognitions on the same Ryzen 7 7445HS / Windows 11 / Python 3.14.7 setup and pinned Small multilingual model used above. CPU INT8 uses four threads, beam 1, explicit language and word timestamps. Inputs were sent at 100 ms PCM cadence; model readiness preceded playback. No regression/build workloads were run concurrently. Only IDs/error counts/timings were saved to ignored `local-data/stt-evaluation/live-latency.json`, not transcripts/audio.
- **EN:** waveform-end-to-final median **2.474 s**, nearest-rank p95 / maximum **2.817 s**; WER **3.39%**, 15/18 normalized-exact utterances.
- **ES:** waveform-end-to-final median **2.662 s**, nearest-rank p95 / maximum **2.964 s**; WER **3.03%**, 15/18 normalized-exact utterances.
- Both synthetic p95 results fall below the initial **≤3 s** target, but Spanish has only ~36 ms observed headroom. With only 18 repeated observations/language, nearest-rank p95 equals that run's maximum; this is not a reliable population percentile or a production bound. Repeated synthetic questions are not independent human accuracy samples.
- The independent replay EOS proxy is the last WAV sample exceeding amplitude 128/32768 (~−48 dBFS); the receiver records final-arrival time concurrently with playback. Backend `end_of_speech_latency_ms` instead estimates the last energy-gated PCM receipt to decode completion, including endpoint silence/queueing/inference but excluding capture/IPC/display. Its observed range was **2.307–2.831 s EN / 2.362–2.969 s ES**. The different endpoint definitions can differ by tens of milliseconds. Forced cuts carry no misleading EOS estimate. The capture window displays the bounded backend estimate; it is not the acceptance stopwatch.
- The post-run process check found **zero remaining Whisper workers**. Model/runtime files and the working database/index were not replaced. No new hardware/conferencing guarantee follows from these tests.

To reproduce the paced probe with the already-configured paths above, from the repository root (no downloads):

```bat
.venv\Scripts\python.exe tools\stt_eval\live_latency.py
```

This probe creates an isolated temporary test database, disables generation for timing, and cleans up its own temporary data. It tests the actual native worker through the ASGI route, not an already-running backend or Electron. Nonzero exit 2 means measured p95 exceeded 3 s; provider/transport failures stop with a fixed stage/message. Keep the raw metrics out of Git/source ZIPs.

### Human EN/ES Windows acceptance — PENDING, not established

No consented human recordings or authorized remote speaker were supplied for this run. **Real technical-question accuracy and true Windows end-of-speech-to-main-window p95 ≤3 s remain unverified**, as do concurrent real Ollama load and conferencing exclusion. Do not mark STT-001A fully accepted based on the synthetic p95.

1. Restart the single existing backend with the explicit local Whisper paths and documented WS limits; use the existing database/index. Check both provider statuses, select Vosk by default, then explicitly test Whisper in EN/ES. Verify unavailable/misconfigured choices fail clearly without switching engine. Do not install/download or reindex to run acceptance.
2. Use a consented, non-private human technical recording or authorized remote speaker through **Windows output** (not merely speaking into a microphone). Test at least 20 distinct technical questions/language, including acronyms, accents, fast/quiet speech and long pauses/questions. Play each once; record misses/errors as failures rather than repeating until successful. Do not persist Live audio/transcripts or log private text.
3. Independently time audible last-word end to the final transcript appearing in the main Live window; retain language, durations, counts and failing stage/message only. Separate startup time from first/warm utterance latency. Report the full sample count and p95 method; the capture-window backend estimate omits real capture/network/IPC/display delays. Require p95 ≤3 s separately for EN/ES before accepting the target.
4. Confirm source-backed exact results, semantic-review labels, no-evidence and explicitly configured Ollama remain correctly separated. Test slow inference/CPU pressure, continuous silence/noise, rapid questions/overload and the 8 s cut limit. Recheck alongside real retrieval/Ollama workloads; synthetic Spanish headroom is too small to assume success under contention.
5. Stop during permission, model loading and active speech/inference; close either window, finish the session and restart both providers. Confirm tracks stop, the Whisper child exits, no stale final/generated card appears and Vosk still works. Repeat conferencing exclusion separately below; no guaranteed exclusion claim is made.

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
