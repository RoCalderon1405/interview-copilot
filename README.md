# Interview Copilot

Interview Copilot is a local Windows desktop application for AI-assisted technical interviews. **Live Mode is the primary product:** explicitly authorized system audio → English/Spanish Vosk transcription → conversational question detection → document-backed answers with sources. Screen-sharing exclusion while remaining visible locally is a core requirement, not a guaranteed capability.

Expanded Practice Mode is a future enhancement. The existing basic Practice page provides document questions, lexical keyword feedback and session reports; it is not an AI interview evaluator. Automatic local Ollama fallback is implemented for final Live questions/instructions, **disabled by default and pending real-Ollama/Windows acceptance**.

## Current status and stack

Electron 39, React/TypeScript, Python/FastAPI, Vosk EN/ES, SQLite/FTS5, optional local multilingual FastEmbed and opt-in local Ollama fallback. No vector DB service is implemented.

- **VALIDATED by the owner in the isolated Windows lab:** system audio, PCM streaming, Vosk English transcription, conversational question detection, source-backed exact Q&A and local semantic retrieval with 204 indexed questions. This is validation history, not a benchmark or a bundled database.
- **IMPLEMENTED / PENDING VALIDATION:** main React Live integration using an isolated capture-controls window. Complete Windows acceptance is still pending.
- **IMPLEMENTED / PENDING VALIDATION:** Spanish transcription support; complete integrated validation is not established.
- **IMPLEMENTED / PENDING VALIDATION:** native content-protection controls; compatibility with Teams, Zoom and Google Meet is unverified.
- **IMPLEMENTED / PENDING VALIDATION:** automatic local Ollama fallback, verified with fake providers/mocked HTTP only; real EN/ES quality, latency and concurrent audio acceptance remain pending.
- **PLANNED:** packaged production capture, currently disabled intentionally.

See [Live acceptance and limitations](docs/live-mode.md), [current architecture and target direction](docs/architecture.md), [priorities](docs/roadmap.md) and [engineering rules](AGENTS.md). Clean Architecture is the approved incremental backend direction, not a completed refactor; desktop boundaries will be feature-based.

## Windows setup (CMD)

Use Python and Node.js/npm available on your machine. **Existing users:** preserve the working `.venv`, database, documents and model caches; do not reinstall or reindex merely to test Live. Source checkouts/ZIPs do not include private data, dependencies or models.

For a first setup only, after approving dependency installation, run from the project root:

```bat
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r apps\api\requirements-live.txt
cd apps\desktop
npm install
```

Vosk model files are separate from pip installation and are never downloaded by the app. Place existing models under `local-data\models\vosk-model-small-en-us-0.15` and `local-data\models\vosk-model-small-es-0.42`, or set `COPILOT_MODELS_DIR` to their parent directory. Obtain missing models only with explicit approval; see [lab setup](docs/transcription-lab.md).

The Windows database and imported documents default to `%LOCALAPPDATA%\InterviewCopilot`; the FastEmbed cache is its `embedding-models` subfolder. `COPILOT_DATA_DIR` overrides the data root. Preserve an existing override to keep using the same database. The API reads environment variables; it does **not** automatically load `.env`.

Start the backend by double-clicking [`dev-api.bat`](dev-api.bat) in the repository root, or run its quoted full path from any CMD working directory. It uses the existing `.venv`, installs nothing and preserves backend console output. Stop with Ctrl+C. On a missing venv or backend failure, the script displays an error and waits for a key before returning a nonzero exit code (the backend's code when available).

The equivalent manual command, **from the project root**, remains:

```bat
.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir apps\api --host 127.0.0.1 --port 8765
```

Check `http://127.0.0.1:8765/health`, `/live/status` and `/semantic/status`. Availability/index counts do not prove successful transcription or semantic accuracy. Do not start a second backend if the working process is already running. Stop the old `npm run lab:transcribe` before starting desktop; both use Vite port 5173 and the backend allows one transcription connection.

Start desktop in a **second** terminal, from the project root:

```bat
cd apps\desktop
npm run dev
```

If `node_modules` is missing, run `npm install` with approval before `npm run dev`.

Open **Live Interview → Preparar captura Live** in the main window. In the new isolated capture window choose English/Español, check consent and click **Iniciar transcripción**. Return to the main Live page to view real-time transcript and source-backed exact/semantic suggestions. Use **Detener y cerrar captura** to stop the capture; the independent lab remains available via `npm run lab:transcribe` if you need to isolate failures.

See [exact Windows acceptance steps](docs/live-mode.md).

## Documents and retrieval

Knowledge Base supports upload, list and delete for PDF, DOCX, XLSX, UTF-8 TXT and Markdown (20 MB upload limit). Import does **not** guarantee usable Q&A:

- PDF extracts page text into fragments; encrypted PDFs are rejected and scanned PDFs require OCR, which is not implemented.
- DOCX extracts paragraph fragments and Q&A from tables with recognized question/answer headers.
- XLSX recognizes EN/ES question/answer columns; rows without a recognized header are treated as text fragments.
- TXT/Markdown recognizes `Q:`/`A:`, `Question:`/`Answer:` or `Pregunta:`/`Respuesta:` blocks; otherwise it creates fragments. When Q&A blocks exist, surrounding prose is not separately indexed.

Manual text queries (`POST /answers`, including the manual box on the Live page) use normalized exact Q&A first, then SQLite FTS5 with lexical scoring for similar Q&A or excerpts. Automatic Live retrieval uses **exact Q&A first, then optional semantic Q&A**; it does not search document fragments. Semantic candidates include sources and require review, not factual verification. If neither returns a suitable suggestion, only explicitly enabled/configured Ollama may generate a separate unverified suggestion. Disabled, unavailable or failed generation preserves the existing no-evidence result. Missing/unavailable semantic retrieval can also yield no evidence; no semantic policy is changed.

Imported wording is not LLM-rewritten, but extraction normalizes whitespace and limits field length; the main-window IPC also limits displayed answer length. Exact means normalized question matching, not a certification that the document is correct or that formatting is preserved.

Import updates entries and FTS, but does not automatically generate embeddings. Deletion removes associated entries, FTS rows and vectors; it also removes linked Practice answers. There is no in-place document update endpoint. Changed content must be imported separately (and the old document deleted if desired); new Q&A needs explicit semantic indexing.

### Optional local semantic setup

Skip this if the existing index/cache works. After approving installation, from the project root:

```bat
.venv\Scripts\python.exe -m pip install -r apps\api\requirements-semantic.txt
```

Import approved documents through Knowledge Base first. With the backend running, index missing Q&A using an already cached model (no download):

```bat
curl.exe -X POST http://127.0.0.1:8765/semantic/index -H "Content-Type: application/json" -d "{\"allow_download\":false}"
```

Only after explicit approval to download the local FastEmbed model, use:

```bat
curl.exe -X POST http://127.0.0.1:8765/semantic/index -H "Content-Type: application/json" -d "{\"allow_download\":true}"
```

The configured model is `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`. Only extracted Q&A questions receive embeddings; vectors stay in SQLite. Indexing is incremental and separate from capture. Live never downloads models or indexes automatically.

## Optional automatic local generation (AI-001A / AI-001B)

**IMPLEMENTED in Live, disabled by default; not used by Practice or manual search.** FastAPI composes one `GenerationService` with `app.bootstrap.create_generation_service()` without network I/O. After a deduplicated final question/instruction has no exact or accepted semantic suggestion, Live schedules `service.generate(question, language)` with `en-US` or `es-MX`. Never generates from partials or after a documentary answer. There is no new public endpoint. The backend does not auto-load `.env`; set the variables before starting/restarting it. Invalid optional configuration disables fallback without preventing API/capture startup.

- `COPILOT_LLM_ENABLED`: defaults to `false`; only `true`/`1` enables the factory (`false`/`0` disables it).
- `COPILOT_OLLAMA_MODEL`: required explicit identifier of an approved, already installed **local** model; no default, installation, model pull or cloud fallback.
- `COPILOT_LLM_TIMEOUT_SECONDS`: total service deadline, default **8 seconds**, configurable above 0 and at most 60; no retries. Cold model loading can exceed this deadline.
- Fixed `http://127.0.0.1:11434/api/chat`, without environment proxies, credentials, redirects, tools or remote URL configuration. Ollama must be operated locally; configure its server with `OLLAMA_NO_CLOUD=1` to disable cloud features. Known cloud model suffixes are rejected, but the application cannot certify what a separately configured Ollama server or custom alias does.
- Only the current question (3–3000 characters), language-specific fixed instructions and generation settings leave the service. No history, documents, transcripts, audio or credentials are supplied. The application does not persist or log prompts/answers; separately operated Ollama/server logging is outside this guarantee.
- Non-streaming output: 256-token budget, at most 2000 answer characters and 64 KiB HTTP response. Empty, malformed, oversized, tool-call or token-truncated responses fail closed. `GenerationError.code` identifies disabled/configuration/input/provider/timeout/response failures; no fabricated answer replaces errors, and caller cancellation propagates.
- Results carry `kind="ai_generated"`, configured provider/model and `source=None`: an **unverified suggestion**, never documentary evidence. Fixed instructions prefer 3–5 natural, professional sentences in B2 English or natural Spanish, practical examples, uncertainty and no invented personal experience. User text stays in a separate user message. Instructions are defense-in-depth, not a guarantee of model compliance; no execution capabilities are provided.

Generation runs outside the PCM/Vosk reception loop: one active request per Live connection/session and one replaceable latest pending question, never an accumulating queue. A newer final question invalidates older work even if it has a documentary answer. Stop, disconnect, errors and session finish cancel/suppress pending results; the final recognizer flush on stop remains documentary-only. Cancellation is client-side/best-effort for Ollama's internal inference; the application waits for request cleanup before starting the next call.

The additive `generated_suggestion` event includes `kind`, `session_id`, unique connection-scoped `question_id`, original detected `question`, `language`, `answer`, `provider`, `model` and `source:null`; it never uses documentary `status`/`match_type`. Final documentary suggestion events also carry correlation IDs. The existing capture relay forwards generated events (not after stop begins); Electron validates bounded fields and trusted senders, strips extras and keeps the 80-event history limit. React displays **“Sugerencia generada por IA — revisar”**, provider/model and “Sin respaldo documental”, separately from documentary cards. Content is rendered as text, not HTML. On generation failure, the no-evidence card remains and audio continues.

Mocked tests validate contracts, not real model quality, latency or Windows operation. No Ollama installation/model download was performed for these tasks. Follow the [pending Ollama/Windows acceptance checklist](docs/live-mode.md#automatic-ollama-fallback--manual-acceptance-pending-ai-001b) with an approved existing local model; preserve the database/cache without reindexing. Existing capture and conferencing-exclusion acceptance is still required; packaged capture remains disabled.

## Screen-sharing and privacy

Settings exposes content protection and always-on-top for the main window. On Windows, Electron requests `WDA_EXCLUDEFROMCAPTURE` via `setContentProtection`; this is best-effort, not proof of remote exclusion or undetectability. The capture-controls window is not currently protected. Validate Teams, Zoom and Google Meet separately from a remote participant and recording; see [the manual checklist](docs/live-mode.md#screen-sharing-exclusion--manual-acceptance-pending).

The main renderer is sandboxed and denies media permissions. The separate nonpersistent capture session requires consent and a click; loopback may include sounds from **all Windows applications**. PCM is processed on localhost and no recordings or Live transcripts are persisted by the application. Local HTTP origin restrictions are not authentication against other local processes; packaged production support needs separate security work. Respect organizational policies and participants' consent.

## Tests

Run each block from the project root (separate terminals or return to the root between blocks):

```bat
cd apps\desktop
npm run test:electron
npm run test:ui
npm run test:audio
npm run lint:electron
npm run build
```

```bat
cd apps\api
..\..\.venv\Scripts\python.exe -m pytest -q
```

For a first test setup, install `apps\api\requirements-dev.txt` into the existing venv only after approval. Tests do not establish real Windows audio or screen-sharing compatibility; optional Vosk tests can skip if runtime/models are absent. `npm run build` checks TypeScript and builds Vite assets; it does not produce a Windows installer. If local native dependencies block the build, report the limitation, run `npm install` on Windows with approval and rebuild.

Keep `node_modules`, `.venv`, private documents, credentials, local databases, embeddings, models, recordings and caches out of Git and distributable source ZIPs. Synthetic test fixtures are not user recordings.
