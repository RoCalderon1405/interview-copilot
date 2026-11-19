# Configuration and optional integrations

The [README](../README.md#windows-setup-cmd) covers the normal Windows startup. This guide keeps advanced configuration out of the project overview. Reuse working environments, databases, models and indexes. Obtain approval before installing missing dependencies or downloading models; no command in this document was executed as part of documentation maintenance.

## Local runtime and data

- Vosk expects `vosk-model-small-en-us-0.15` and `vosk-model-small-es-0.42` inside `local-data\models`. `COPILOT_MODELS_DIR` overrides their parent directory. Models are separate from pip packages and are not downloaded by the application. See the [transcription lab](transcription-lab.md).
- Documents and SQLite default to `%LOCALAPPDATA%\InterviewCopilot` on Windows. `COPILOT_DATA_DIR` overrides that root. Preserve existing overrides to avoid opening a different database. The default embedding cache is its `embedding-models` subfolder.
- The API reads process environment variables, not `.env` files. Configure them in the same terminal before starting/restarting the backend. Never put real credentials in tracked files, renderer settings or distributable archives.
- `dev-api.bat` uses the repository's existing `.venv`; it installs nothing. Stop it with Ctrl+C. If the environment is missing or startup fails, it reports the error and waits before returning a nonzero exit code.

Equivalent backend command, from the repository root:

```bat
.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir apps\api --host 127.0.0.1 --port 8765 --ws-max-size 64000 --ws-max-queue 4
```

Keep these WebSocket limits and the single-process Windows launch path. Do not start a second transcription lab/desktop on Vite port 5173 or a second backend on 8765. `/live/status` and `/semantic/status` report configuration/index availability, not real speech accuracy or remote provider authorization.

## Opaque window fallback (UI-004)

Live starts opaque. In **Live Interview / Entrevista en vivo**, open **Overlay appearance / Aspecto del overlay**, immediately below the mode/pin/capture controls. This disclosure is visible in both modes. Select **Compact mode / Modo compacto** to enable its **Compact-mode opacity / Opacidad en modo compacto** slider (80–100%). The value belongs to compact mode even when displayed disabled in expanded mode; expanded always stays opaque. Text remains opaque. **Opaque background / Fondo opaco** remains available in both modes; select it before manual resizing because translucent windows disable manual resize under Electron's Windows limitations.

After changing Electron main/preload code, close the desktop normally and restart it using the usual launch command. Vite hot reload updates React only; it does not update native IPC handlers or the existing preload. Mixed versions can display the generic presentation failure even though a fresh Electron instance switches correctly. Live now detects an older native bridge and requests a full restart instead of offering unsupported controls. Closing stops capture; do not restart without saving any separately needed work.

If transparency or custom window chrome is unreliable, close the desktop normally (this stops capture), then set the following in the terminal that launches Electron, before using your usual desktop startup command:

```bat
set "COPILOT_OPAQUE_WINDOW=1"
```

In PowerShell use `$env:COPILOT_OPAQUE_WINDOW = '1'`. This starts an opaque window with the normal native frame and disables translucent settings; compact/expanded modes still work. To re-enable transparency on the next startup, use `set "COPILOT_OPAQUE_WINDOW="` in CMD or `Remove-Item Env:COPILOT_OPAQUE_WINDOW` in PowerShell. No backend, database, model or index change is required. Mode rectangles and opacity are memory-only and reset on app exit. Native Windows transparency, scaling and drag/resize behavior remain pending acceptance.

## Optional Faster-Whisper Live setup (STT-001A)

Faster-Whisper uses an explicitly configured local **Small multilingual, CPU INT8** worker. It does not use CUDA, pull models or silently fall back to another provider. Reuse the approved isolated runtime; do not replace the working API `.venv`.

For the existing evaluation layout, from the repository root in CMD:

```bat
set "COPILOT_WHISPER_PYTHON=%CD%\local-data\stt-evaluation\venv\Scripts\python.exe"
set "COPILOT_WHISPER_MODEL_DIR=%CD%\local-data\stt-evaluation\models\small"
dev-api.bat
```

Use your actual absolute paths if they differ. Without overrides, the adapter uses the current Python interpreter and `local-data/models/faster-whisper-small`. The model must contain `model.bin`, `config.json`, `tokenizer.json` and `vocabulary.txt`; English-only models are rejected. Missing artifacts require separately approved provisioning. See the [runtime/evaluation evidence](live-mode.md#cpu-evaluation-method-and-reproduction).

Whisper produces finals, not streaming partials. Startup has a 30-second deadline; inference has a 10-second deadline. Its energy gate and bounded segments are not robust VAD. Forced cuts do not trigger Ollama. Stop cancels pending inference and reaps the worker; Vosk's explicit stop can flush a documentary-only final. See [pipeline limits and Windows acceptance](live-mode.md#stt-001a--live-integration) and [adapter boundaries](architecture.md#module-responsibilities-today).

The CPU INT8 worker uses four threads and one worker. Endpointing uses 200 ms pre-roll, at least 200 ms voiced audio, 500 ms end silence and an 8-second PCM cap. One segment can be active and one pending; overload stops capture explicitly rather than silently dropping audio. Vosk reception is bounded to 64,000 queued bytes / 20 frames. Keep the Uvicorn size/queue limits above; alternative launchers need equivalent bounds. These implementation limits are not human-speech accuracy or latency guarantees.

## Optional Deepgram Nova-3

Deepgram is cloud STT, independent of the LLM provider. Install `apps\api\requirements-deepgram.txt` into the API environment only if needed and approved. In Windows development Electron, **Settings → Deepgram API Key** supports explicit Configure, Replace and Delete actions. Entry uses an empty Windows credential dialog: paste the API Key in **Password**, never your Windows password. Cancel leaves the stored key unchanged. Delete requires confirmation and does not revoke the key at Deepgram. Management is disabled in packaged builds and browsers.

The short-lived Python helper stores a generic credential (`InterviewCopilot/Deepgram`) in Windows Credential Manager for the current user, on this computer. The key never traverses React or Electron IPC. Close **all** audio windows first, including raw-audio/transcription labs: a capture reservation remains until its window closes, even after Stop. Conflicts fail without interrupting existing capture. Timeout or cancellation can race a completed write; refresh status before retrying. A configured status is not proof of valid remote authorization.

For each new session, the backend resolves **environment first, Windows Credential Manager second**. An explicitly present but empty/invalid environment value blocks Deepgram; it never silently falls back to Windows. Settings distinguishes the stored Windows key from the backend's effective source. Backend unavailable means its state is unconfirmed, not unconfigured. Changing the stored key needs no backend restart; changing its process environment does. The backend and Electron/helper must run as the same Windows user. There is no automatic `.env` loading.

The existing environment-variable workflow remains supported as an explicit override. To enter it without writing it into a file, use PowerShell from the repository root:

```powershell
$secret = Read-Host 'Deepgram API Key' -AsSecureString
$env:COPILOT_DEEPGRAM_API_KEY = [System.Net.NetworkCredential]::new('', $secret).Password
Remove-Variable secret
.\dev-api.bat
```

Restart an already-running backend only when intended, from that configured terminal. `providers.deepgram.available=true` at `/live/status` confirms local configuration only. In the capture window, select **Deepgram Nova-3**, choose EN/ES and grant separate informed cloud-audio consent. Availability does not prove billing access or Internet connectivity. There is no automatic cloud/local fallback. Stop unnecessary cloud sessions; usage may incur charges and provider retention is outside the application's local non-recording guarantee.

After stopping the backend, remove the key from an otherwise continuing PowerShell session:

```powershell
Remove-Item Env:\COPILOT_DEEPGRAM_API_KEY -ErrorAction SilentlyContinue
```

Windows storage is not a vault against malware running as the same user or an administrator. Native input is not on the secure desktop and is not guaranteed invisible to screen sharing; Python cannot guarantee complete plaintext-memory erasure. Tokens are limited to 256 printable ASCII characters, with no whitespace. Cost/history features remain planned. See [credential boundaries](architecture.md#cloud-001--windows-credential-boundary), [credential acceptance checks](live-mode.md#cloud-001--windows-key-management) and [observed STT evidence](live-mode.md#stt-001b--initial-deepgram-windows-observation-2026-11-16).

## Documents and retrieval

Imports support XLSX, DOCX, PDF, TXT and Markdown up to 20 MB:

- XLSX recognizes EN/ES labeled question/answer columns; other rows become text fragments.
- DOCX extracts Q&A tables and paragraph fragments.
- TXT/Markdown recognizes `Q:`/`A:`, `Question:`/`Answer:` or `Pregunta:`/`Respuesta:` blocks. Other content becomes fragments; surrounding prose is not separately indexed when Q&A blocks exist.
- PDF produces fragments. Encrypted PDFs are rejected, and scanned PDFs need OCR that is not implemented.

Automatic Live uses normalized exact Q&A → optional semantic Q&A → explicit no-evidence. It does not use document fragments as automatic answers. Only then may explicitly enabled Ollama provide a separate unverified suggestion. Manual `POST /answers` uses exact Q&A followed by FTS5/lexical candidates, including excerpts; Practice retains its existing lexical assessment.

Extraction normalizes whitespace and limits fields. Sources identify stored content, not verified truth or guaranteed original formatting. Imports update entries/FTS but not embeddings. Deletion removes linked entries, vectors and Practice answers. There is no in-place document update API. Do not reindex solely to validate unrelated changes.

## Optional local semantic setup

Skip this section if the existing cache/index works. Install `apps\api\requirements-semantic.txt` only when needed and approved. The configured model is `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`; only Q&A questions are embedded, with vectors stored in SQLite.

With the backend running and approved documents imported, index pending questions using an already cached model:

```bat
curl.exe -X POST http://127.0.0.1:8765/semantic/index -H "Content-Type: application/json" -d "{\"allow_download\":false}"
```

Missing models require separate download approval before setting `allow_download` to `true`. Live never downloads or indexes automatically. Semantic candidates require review; unavailable, weak or ambiguous matches can leave no evidence.

## Optional automatic local generation (AI-001A / AI-001B)

Generation is **disabled by default**, used only after an eligible completed Live question has no documentary answer. It is not used by manual search or Practice. Configure these backend environment variables before startup:

- `COPILOT_LLM_ENABLED`: `true`/`1` enables generation; `false`/`0` disables it.
- `COPILOT_OLLAMA_MODEL`: required explicit identifier of an approved, already-installed local model. No default model, pull or cloud fallback.
- `COPILOT_LLM_TIMEOUT_SECONDS`: total service deadline, default 8 seconds, greater than 0 and at most 60. No retries; cold loading can exceed the deadline.

Ollama must already run locally at `http://127.0.0.1:11434/api/chat`. Configure its server with `OLLAMA_NO_CLOUD=1`. The application disables environment proxies, redirects and credentials and offers no tools. Known cloud model suffixes are rejected, but a separately configured server/custom alias cannot be certified by the application.

Only the current question, selected-language instructions and three fixed synthetic examples are supplied—not full transcripts, documents, audio or actual conversation history. Output is non-streaming with a 256-token budget, at most 2000 answer characters and 64 KiB HTTP response. Truncated, malformed, empty, tool-call and rejected-content responses fail closed using sanitized errors. No generated answer is persisted or logged by the application; separately operated Ollama logging is outside that guarantee.

AI-001C content checks reject substantial prompt copies and narrowly recognized unsupported autobiographical work claims. They are not fact verification: fabrication and technical errors can escape them, and valid paraphrases/hypotheticals can be rejected. **Quality acceptance is not met.** Review [known failures and false positives](live-mode.md#ai-001c--few-shot-generation-evaluation) before enabling it.

Generation runs outside PCM reception with one active request and one replaceable pending question. Newer questions, stop, disconnect and session finish cancel/suppress obsolete results. HTTP cancellation cannot prove that Ollama's internal inference stopped immediately. See [generation/lifecycle boundaries](architecture.md#permission-transport-and-privacy-boundaries).

AI-001D makes current-question failures visible beside `no_evidence` in the **main Live workspace**, not the auxiliary capture window. The interface translates fixed reasons for `disabled`, `not_configured`, `invalid_input`, `unavailable`, `timeout`, `invalid_response` and `provider_error`. Invalid startup settings remain distinct from intentional disablement and never prevent API/audio startup or enable an inference provider. No provider error text, configuration value, prompt or rejected answer is relayed. `invalid_response` covers format and content-policy rejection, not a factuality verdict; `provider_error` remains generic (including HTTP 404), not proof of a missing model. Review backend process settings and the existing local model before changing anything; the app does not load `.env` implicitly, install models, retry, increase deadlines or switch providers. Superseded/stopped/disconnected/finished work stays suppressed rather than emitting late failure events. See [evidence and Windows acceptance](live-mode.md#ai-001d--observable-generation-outcomes).

## Opt-in synthetic Ollama A/B evaluation (AI-001C)

The utility `apps/api/eval_ollama.py` is for explicitly approved synthetic evaluation, not normal startup or a documentation check. From `apps/api`, inspect options without network activity:

```bat
..\..\.venv\Scripts\python.exe eval_ollama.py --help
```

It requires `--run` before any network request and the exact existing `qwen3:1.7b` tag. No model pull, unload, settings change or file writing occurs. The default benchmark makes **144 measured inference calls plus four warmups**; do not run it for test/documentation cleanup. Agree a budget including warmups and failed attempts before any real-model check.

Both arms share current production validation; the baseline prompt is frozen before AI-001C. Case ordering is shuffled reproducibly and paired arm order counterbalanced. The 24 regression questions are no longer unseen acceptance data. JSON stdout reports successful-answer p50/p95, failures, content rejections, truncations and provider timing/token metrics. Provider durations use nanoseconds; client elapsed time uses milliseconds. `--show-answers` includes bounded rejected synthetic outputs for false-positive review; never use private Live content.

Warmup failures stop the run. Measured timeout/unavailable/provider failures stop further calls because server-side work might still be active. Exit 2 can also mean completed calls with intentional content rejection; exit 0 is not human quality acceptance. `--cold` requires one `--case`, one `--variant` (`baseline` or `fewshot`) and `--repetitions 1`; it refuses a resident model and never unloads it. Natural unload and controlled cold observations remain separate from warm results and OS-cache state. See [historical evidence and pending acceptance](live-mode.md#ai-001c--few-shot-generation-evaluation).

## Development checks

Use the existing `.venv`. For a first test setup only, `apps\api\requirements-dev.txt` requires installation approval. From `apps/api`:

```bat
..\..\.venv\Scripts\python.exe -m pytest -q
```

From `apps/desktop`:

```bat
npm run test:electron
npm run test:ui
npm run test:audio
npm run lint:electron
npm run build
```

Run focused checks before necessary regressions; do not add tests or real-model calls merely to increase coverage. Existing Starlette/httpx deprecation and Vite classic-script warnings are documented in [Live evidence](live-mode.md). Native/model checks can be blocked or skipped when approved runtimes are absent. A Vite build is not a Windows installer, and mocks do not validate audio or conferencing exclusion. See [permanent engineering rules](../AGENTS.md).
