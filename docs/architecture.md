# Architecture — current system and incremental direction

Live Mode is the primary product. The integrated flow below is implemented for Windows development, but complete acceptance is pending. The owner validated audio, PCM, Vosk English, question detection and exact/semantic retrieval in the isolated lab, not the full main-window integration. See [current acceptance status](live-mode.md).

## Current implementation

```text
Main Electron window (React, no media permissions)
    ├── Live page: start/stop capture window
    ├── Live page: transcript + Q&A cards with source
    ├── Knowledge Base / Practice / manual query
    └── restricted preload bridge (open/close/status/events)

Second Electron window (separate, nonpersistent session)
    ├── direct user click + explicit consent
    ├── reused standalone getDisplayMedia loopback path
    ├── AudioWorklet → mono PCM16 @16kHz
    ├── single-use-token local WebSocket → FastAPI/Vosk
    └── validated text/status/suggestion IPC → main window

FastAPI localhost:8765
    ├── local Vosk EN/ES STT via /live/transcribe
    ├── heuristic conversational question extraction
    ├── exact Q&A → optional semantic FastEmbed candidates in SQLite
    └── answer + provenance, or explicit no-evidence
```

### Module responsibilities today

- `apps/api/app/main.py`: application composition, HTTP schemas/routes, upload handling and origin/host restrictions.
- `live.py`: token lifecycle, single active transcription slot, Vosk cache, heuristic EN/ES detector, deduplication, WebSocket protocol and retrieval coordination. Stable repeated partials permit early exact lookup; finals permit exact/semantic lookup.
- `domain/knowledge.py`: framework-independent frozen `ParsedEntry` dataclass, shared by parsing and persistence (ARCH-003).
- `domain/text.py`: the existing mutable `STOPWORDS` set, shared directly by persistence and retrieval (ARCH-004). Both legacy module imports reference this same object; its content is unchanged. `textnorm.py` remains unchanged and pure.
- `application/ports.py`: `RetrievalReader`, a structural Protocol exposing only `find_exact_qa` and `find_matches` (ARCH-005). It preserves existing dictionary rows and requires no framework or concrete storage implementation.
- `parsers.py`: format-specific extraction into Q&A or text fragments, with source locations and resource limits. Re-exports the same Domain `ParsedEntry` class for compatibility.
- `store.py`: local document files, SQLite schema, entries, FTS5, vectors and Live/Practice session persistence. Imports `ParsedEntry` directly from Domain, not from the document parsers.
- `retrieval.py`: exact and manual lexical retrieval, Live retrieval policy, plus existing lexical Practice assessment/reporting. Storage type dependencies use `RetrievalReader`; this module no longer imports `KnowledgeStore`.
- `semantic.py`: optional local FastEmbed model, explicit incremental indexing, similarity/margin abstention and stored-answer candidates.
- `apps/desktop/src/App.tsx`: shell, pages, UI state and coordination; `api.ts`/`types.ts`: HTTP client and TypeScript contracts.
- `electron/main.cjs`: windows, permissions, protection, sender validation, IPC sanitization and bounded event history. Preloads expose narrow bridges.
- `audio-lab/transcribe.js` and `pcm-processor.js`: consent-driven capture, Web Audio lifecycle, PCM conversion, local HTTP/WS and lab display. The integration reuses these files rather than a rewritten capture engine.

ARCH-003 extracts only the shared record, preserving its five fields, constructor, equality and immutability. Domain uses only the standard library; persistence no longer loads PDF/Office libraries through its entry type. Parsing algorithms, storage, retrieval and Live behavior are unchanged. This is the first small extraction, not a fully layered Clean Architecture backend or a feature-separated desktop.

ARCH-004 moved stopwords out of persistence without changing filtering behavior. ARCH-005 replaces retrieval's concrete storage type dependency with the application read port; `KnowledgeStore` implements it structurally without inheritance, wrappers or SQL changes. Existing functions, dictionaries, exact/lexical/semantic priorities, scores, thresholds and Practice feedback remain unchanged. Other modules still use concrete adapters; application/infrastructure separation is not complete.

### Documents, retrieval and consistency

See [README document limitations](../README.md#documents-and-retrieval) for extraction by format. A supported import is not a promise of Q&A extraction: PDF fragments, for example, are not Live answer candidates.

- Manual `POST /answers`: normalized exact Q&A first, then FTS5 candidates with lexical scoring for similar Q&A/excerpts. The manual Live text box uses this same endpoint, not semantic Live retrieval.
- Automatic Live: normalized exact Q&A first, then optional semantic Q&A; otherwise `no_evidence`. Semantic is a possible stored answer to review, not verified truth. No LLM generates answers.
- Import stores original files, extracted entries and FTS rows. Extraction normalizes whitespace and limits field length; main-window IPC additionally limits answer length. Do not promise byte-for-byte original formatting or unlimited answers.
- Embeddings cover Q&A questions only. Indexing is explicit; new imports remain pending until indexed. Model download requires `allow_download: true`; Live never downloads or indexes automatically.
- Deletion removes entries/FTS/vectors and linked Practice answers. No in-place document update API exists. Filesystem and SQLite changes are not one atomic transaction; concurrent deletion/indexing guarantees need further tests before claiming them.

### Permission, transport and privacy boundaries

Main Electron session explicitly denies display/microphone capture. The separate nonpersistent `live-capture` partition permits a display request only from its trusted main frame with a user gesture. Consent is checked in the capture UI and required for the backend token request. Capture includes **all Windows output**, not one app. Video is required by the loopback request but is not displayed or recorded.

The capture page uses Vite `http://127.0.0.1:5173`; PCM16 mono at 16 kHz goes directly to `ws://127.0.0.1:8765/live/transcribe`. Tokens are ephemeral, single-use and sent in the start message. WS validates Origin/Host independently of HTTP CORS. HTTP allows development origins and requests without Origin; these controls do not authenticate other local processes. Packaged capture is disabled pending separate bootstrap/authentication/origin validation; do not allow `file://`/`null` origins as a shortcut.

IPC checks the window/frame/URL and allowlists bounded text/status/suggestion/metric fields; raw audio and credentials are not relayed. Live transcripts and audio are not persisted. Main-process history is capped at 80 events, and React also bounds its history; the auxiliary lab DOM currently accumulates results until reset. SQLite persists documents, vectors and session metadata; basic Practice also persists submitted answers.

### Screen-sharing exclusion

The main window calls `setContentProtection(true)` on Windows and exposes a Settings toggle plus always-on-top. There is no separate compact overlay window today; capture controls are not content-protected.

[Electron content protection](https://www.electronjs.org/docs/latest/api/browser-window#winsetcontentprotectionenable) uses Windows `SetWindowDisplayAffinity` with `WDA_EXCLUDEFROMCAPTURE`. [Microsoft documents](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowdisplayaffinity) support from Windows 10 version 2004; older versions fall back to `WDA_MONITOR` behavior. Protection depends on supported capture APIs and desktop composition; it is not a security/DRM guarantee. The reported protection flag is not evidence of remote exclusion.

Exclusion while remaining visible locally is a core Live requirement. Teams, Zoom and Google Meet compatibility remains pending real Windows sessions, separately by client/browser version and capture mode. It does not guarantee undetectability, hide the process or replace audio consent. See [manual validation](live-mode.md#screen-sharing-exclusion--manual-acceptance-pending).

## Approved direction — incremental refactoring

Progressively separate backend responsibilities into:

```text
domain/          Pure entities, normalization and business policies
application/     Document, retrieval, indexing and Live use cases; required ports
infrastructure/  SQLite/files, document parsers, Vosk and FastEmbed adapters
presentation/    FastAPI HTTP/WS routes and transport schemas
bootstrap        Configuration and dependency composition
```

Dependencies point inward: domain imports no frameworks/adapters; application depends on domain and only the ports it needs; infrastructure implements those contracts; presentation translates transport to use cases. Composition wires concrete adapters. Keep the `app.main:app` entry point and existing HTTP/WS contracts during migration.

For desktop, progressively separate `src/app`, `src/features/{live,knowledge,practice,settings}` and genuinely shared HTTP/bridge/UI modules. Electron should separate window lifecycle, permission/protection policies, IPC validation/handlers and preloads. Business coordination should not be embedded in JSX or platform handlers. Do not mechanically reproduce backend layers in React.

Exact filenames and extraction order still need task-level approval. Prefer a few cohesive modules, hooks/reducers and concrete required ports over generic repositories, a DI framework, global state dependency or an interface for every class. Preserve the lab and existing Practice behavior; LLM providers and expanded Practice are future work, not current adapters.

Validate main Live first, then extract one responsibility per task with contract/regression tests and Windows acceptance where audio, IPC, lifecycle or protection is affected. Separate behavior fixes from moves. See [roadmap](roadmap.md) and [engineering rules](../AGENTS.md).
