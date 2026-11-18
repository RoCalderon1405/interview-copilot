# Roadmap — Interview Copilot

Live Mode is the primary product. This order reflects the owner's priorities, not authorization to implement every item.

## Official task board

This file is the single lightweight task board; [Live Mode](live-mode.md) holds validation evidence and known limitations, not a second task list.

**Current validation focus: STT-001B** — Deepgram Nova-3 integration is **IMPLEMENTED / PARTIALLY VALIDATED ON WINDOWS (EN)**. The owner confirmed Electron system-audio capture, progressive English transcripts and final/question relay to React; no measured EOS or first-partial latency yet, and Spanish/network/stop-restart acceptance is pending. STT-001A remains implemented but not fully accepted; keep Vosk as default. **DET-002** has an initial conservative implementation and focused tests in the current source; broader contextual behavior and real EN/ES acceptance remain pending. All provider cost, credential and metering features are planned separately; see below.

| ID | Description | Status | Commit reference |
| --- | --- | --- | --- |
| DOC-001 | Synchronize product, setup and engineering documentation | Completed | `5fa3ce8` |
| DOC-002 | Establish task tracking and reconcile Live limitations | Completed | `ec65a11` |
| ARCH-001 | Architecture assessment; analysis only, no refactor | Completed | — |
| RESEARCH-001 | Research real-time question detection; research only | Completed | — |
| DET-001 | Conservative conversational question segmentation | In progress; implemented, not fully accepted | `3bc2f05` |
| TEST-001 | Align Vosk integration tests with the partial/final timestamp contract | Completed; test-only correction, production unchanged | `63e4893` |
| DEV-001 | Simple Windows script to start the local backend | Completed; Windows CMD runtime verified | `b02378f` |
| LIVE-001 | Complete integrated Live Windows acceptance | Partially validated | `540c27d` (integration, not acceptance) |
| ARCH-002 | Incremental backend Clean Architecture plan; planning only | Completed | — |
| ARCH-003 | Extract ParsedEntry into Domain with compatible public imports | Completed; contracts, backend suite and Windows startup verified | `6b8cc0b` |
| ARCH-004 | Separate stopword policy from persistence with compatible public imports | Completed; identity, import independence and lexical regressions verified | `7464c11` |
| ARCH-005 | Decouple retrieval from concrete storage through a minimal read port | Completed; in-memory behavior, import independence and existing store compatibility verified | `9df97a2` |
| AI-001A | Independent local Ollama generation foundation, disabled by default | Completed; 96 mocked contract/compatibility cases and all 284 backend tests passed; no real model acceptance | `87bd00f` |
| AI-001B | Automatic Live fallback integration after suitable documentary retrieval fails | Completed implementation; 303 backend tests, 9 Electron, 3 UI and 2 PCM tests passed; real Ollama/Windows acceptance pending | — |
| AI-001C | Three synthetic examples per language, concise EN/ES instructions and conservative application content checks; opt-in local qwen3:1.7b A/B evaluation | Remediation implemented, NOT ACCEPTED; test cleanup: 178 focused / 463 backend passed, zero real Ollama calls, production unchanged; three known false positives documented; prior A/B quality target unmet; owner/cold/Live Windows acceptance pending (live-mode.md) | — |
| STT-001A | Selectable local Vosk/Faster-Whisper Live STT, EN/ES | Implemented; automated/native synthetic replay validated; human EN/ES Windows accuracy, real p95 ≤3 s and contention acceptance pending; GPU excluded | `febae20` (initial gate), `2f7545f` (CPU evaluation); integration commit in history |
| STT-001B | Optional Deepgram Nova-3 streaming with cloud consent and EN/ES selection | Implemented in feature branch; owner validated English partial/final + React relay, Spanish and timing/lifecycle tests pending | Pending commit |
| DET-002 | Distinguish implicit interview requests from operational instructions and ordinary speech, EN/ES | Initial conservative detector and focused tests present; broader contextual behavior and real EN/ES acceptance pending; not rerun in this documentation task | — |
| UI-001 | Professional Live desktop workspace: newest-first/in-place transcription, independent answer panel, explicit provenance/states and local/cloud labels; review window protection | Implemented; 6 UI, 9 Electron, 9 audio checks, lint and build passed; Windows visual/audio/scroll/stop-restart and conferencing exclusion acceptance pending (live-mode.md) | — |
| MET-001 | Measure live first-partial, EOS-to-final and final-to-suggestion latency (p50/p95) | Pending | — |
| CLOUD-001 | Windows-secured persistent BYOK configuration and consent/privacy UX | Planned; current Deepgram key is environment-only | — |
| COST-001 | Pre-session cost estimate and post-session provider usage/cost estimate | Planned; no billing telemetry yet | — |
| HIST-001 | Privacy-limited local session usage/cost history with retention controls | Planned; no transcript/audio persistence | — |
| AI-002 | Optional OpenAI cloud LLM provider, independent of STT, with BYOK | Planned; not implemented | — |
| STT-001C | Evaluate optional AssemblyAI cloud streaming after current acceptance | Future evaluation; not implemented | — |

**Status meaning:** Completed applies to the stated deliverable (analysis/research is not implementation); implemented means code exists, not that Windows acceptance passed. Partially validated records only confirmed cases. Pending work is not started/accepted; deferred work is not current scope. A commit alone does not close a task. `—` means no dedicated reference recorded; this update's commit is available in Git history.

**Maintenance:** each approved task must update its row when completed, including available commit references and validation limits. Record partial progress without upgrading it to full validation; keep the current-task indicator accurate. Do not create another board or copy conversation history into documentation.

<!-- STT-001B roadmap decisions, 2026-11-16 -->
## STT-001B results and agreed product direction

**Observed on Windows (2026-11-16):** Deepgram Nova-3 returned partial and final English transcripts in the Electron capture window and relayed finals/questions to React. The owner observed a small but unmeasured delay. The detector incorrectly treated some spoken test instructions as interview questions. This is **partial acceptance**, not a latency SLA or validated production release. Spanish, interruptions, restart, network failure and end-to-end latency remain unverified. A `no_evidence` documentary response is not an STT failure.

The following decisions are approved **as product direction**, not permission to implement all tasks at once:

- **Question intent (DET-002, acceptance pending):** an initial conservative implementation accepts implicit interview requests and rejects narrowly recognized operational display checks. The broader goal remains to detect requests such as "Tell me about your experience with React", "Walk me through your architecture" and "Explain dependency injection" without treating ordinary instructions, quoted examples or incomplete phrases as questions. Validate real EN/ES examples, false positives, false negatives, deduplication and abstention. Do not prompt Ollama until an utterance is complete; do not make a large new agent framework.
- **Independent provider selection:** STT: Vosk (local default), Faster-Whisper (optional local), Deepgram Nova-3 (optional cloud); evaluate AssemblyAI later, not as a new automatic fallback. LLM: existing local Ollama and a separately approved future OpenAI API adapter. Never conflate the STT choice with the LLM choice or silently switch cloud providers.
- **BYOK/security (CLOUD-001):** each user configures their own provider account and API Key. Deepgram currently reads an environment variable only; a future explicit settings feature should protect persistent secrets with Windows OS facilities (for example, Credential Manager/DPAPI), never renderer state, plaintext SQLite, logs, Git or bundled installers. Obtain provider-specific informed audio consent before sending it off-device; disabling cloud must preserve local mode.
- **Cost estimates and usage (COST-001):** before a paid session, display a price estimate based on the selected STT/LLM provider, model and planned duration, with clear assumptions and current rates. After the session, show measured STT usage (including provider-billable time when obtainable), actual reported LLM token usage when available and **estimated** monetary cost; avoid claiming access to the provider's invoice. Local API charges are zero, not necessarily zero hardware/electricity cost. Prices and free credits vary and must not be hardcoded as permanent facts.
- **Local session history (HIST-001):** opt-in/approved persistence of session metadata, provider/model, durations, usage estimates and costs. Keep audio and full Live transcripts out of persistent history by default. Define deletion, retention and privacy before implementing.
- **Real-time UX (UI-001/MET-001):** show the actual selected STT provider (not "STT local" for cloud); distinguish partial and final text. Measure time-to-first-partial, end-of-speech-to-final and final-to-suggestion separately, plus p50/p95 in repeatable real Windows tests. Optimize only after measurements.
- **Validation and release:** run EN/ES human speech, realistic Teams/Meet/Zoom system audio, network disconnect/stop/restart, Vosk and Whisper regressions, API/browser security and main-window behavior before closing STT-001B. The app is Windows development-mode only; screen-capture exclusion is best-effort and still unverified in meetings.

The existing exact Q&A > optional semantic candidate > explicit no-documentary-evidence policy stays unchanged. Local Ollama suggestions are separate, clearly marked unverified and opt-in. Future cloud LLM output must follow the same provenance rules. `AGENTS.md` remains short and limited to permanent engineering rules.

## Established baseline

- Owner-validated isolated Windows lab: system audio, PCM, Vosk English, conversational question detection, exact Q&A with sources and local FastEmbed retrieval with 204 indexed questions.
- Implemented: main Live integration, Spanish support, document management, manual search and native protection controls. The owner confirmed integrated Windows audio, English transcription, Electron-to-React events, conversational detection in tested cases and exact retrieval with sources. Complete acceptance and conferencing checks remain pending; see [current validation](live-mode.md).
- Existing basic Practice sessions/lexical feedback remain available; expanded Practice is future work.

## Ordered priorities

1. **Current:** finish STT-001B EN/ES human Windows acceptance and repeatable latency/stop/restart/network tests, then validate the existing DET-002 detector against negative and positive EN/ES examples and address remaining contextual gaps. Preserve Vosk as default and Faster-Whisper as an explicit local alternative; keep all provider changes opt-in. Restore Faster-Whisper runtime variables before comparing it; no CUDA or automatic cloud fallback. Do not reindex the document database solely for STT testing.
2. Review task-level architecture decisions within the approved pragmatic Clean Architecture direction; then refactor incrementally with clear React/Electron feature boundaries. Preserve APIs, retrieval policy, permissions and validated capture. The refactor is not completed.
3. Windows backend startup is available through [`dev-api.bat`](../dev-api.bat) (DEV-001, verified in CMD); it uses the existing venv and does not install packages or create environments.
4. AI-001A/B provide opt-in automatic local fallback only after final no-evidence, using question/language and fixed instructions without execution capabilities. AI-001C implements three fixed synthetic examples per selected language and an opt-in `qwen3:1.7b` comparison, without changing runtime settings or contracts. Its approved remediation simplifies localized instructions and adds conservative application-layer rejection for substantial prompt copying and clearly recognizable unsupported autobiographical work claims. This does not provide general fact verification, retries or replacement generation. Its scope was approved separately; it does not close or reprioritize STT/DET acceptance. Validate EN/ES quality/false positives with owner review, cold/warm latency, audio continuity, replacement and teardown before claiming real-provider acceptance. Documentary priority, default-disabled behavior and manual/Practice policies remain intact. See [AI-001C evidence](live-mode.md#ai-001c--few-shot-generation-evaluation); implementation is not full acceptance.
5. Improve Live from real user feedback. As a core Live acceptance requirement, validate screen-sharing exclusion in actual Windows Teams, Zoom and Google Meet sessions before making compatibility claims. The native protection request alone is insufficient.
6. Consider expanded Practice Mode later; do not design or implement additional exercises or AI evaluation now.

Packaged production capture remains disabled. Its bootstrap/authentication/origin design and independent Windows acceptance are separate pending work, not part of development-mode validation.

Each adopted task needs one objective, scope/exclusions, automated checks, human acceptance where applicable and small Conventional Commits. No unapproved dependencies, downloads, custom agents or changes to the working audio pipeline.
