# Roadmap — Interview Copilot

Live Mode is the primary product. This order reflects the owner's priorities, not authorization to implement every item.

## Official task board

This file is the single lightweight task board; [Live Mode](live-mode.md) holds validation evidence and known limitations, not a second task list.

**Current task: STT-001A**, blocked at the runtime compatibility gate; no implementation or environment changes. Windows/Python 3.14 wheels exist, but Faster-Whisper/CTranslate2/PyAV are absent and required CUDA 12 cuBLAS/cuDNN 9 DLLs are not discoverable. See [compatibility evidence and resumption checks](live-mode.md#stt-001a--runtime-compatibility-gate-blocked). Owner approval is required before installing dependencies/models or choosing CPU-only validation. AI-001B remains implemented, disabled by default, with real Ollama/Windows acceptance pending. **DET-001** remains implemented but not fully accepted. AI-001C has not started and still requires scope definition and approval.

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
| AI-001C | Follow-up generation work | Pending scope definition and owner approval; no implementation authorized | — |
| STT-001A | Selectable local Vosk/Faster-Whisper Live STT, EN/ES | Blocked at compatibility gate; pipeline inspected, no implementation; runtime/model installation requires approval | — |
| STT-001B | Deepgram Nova-3 STT | Approved future task; not started, excluded from STT-001A | — |
| DET-002 | Further contextual detection beyond DET-001; scope requires approval | Deferred | — |

**Status meaning:** Completed applies to the stated deliverable (analysis/research is not implementation); implemented means code exists, not that Windows acceptance passed. Partially validated records only confirmed cases. Pending work is not started/accepted; deferred work is not current scope. A commit alone does not close a task. `—` means no dedicated reference recorded; this update's commit is available in Git history.

**Maintenance:** each approved task must update its row when completed, including available commit references and validation limits. Record partial progress without upgrading it to full validation; keep the current-task indicator accurate. Do not create another board or copy conversation history into documentation.

## Established baseline

- Owner-validated isolated Windows lab: system audio, PCM, Vosk English, conversational question detection, exact Q&A with sources and local FastEmbed retrieval with 204 indexed questions.
- Implemented: main Live integration, Spanish support, document management, manual search and native protection controls. The owner confirmed integrated Windows audio, English transcription, Electron-to-React events, conversational detection in tested cases and exact retrieval with sources. Complete acceptance and conferencing checks remain pending; see [current validation](live-mode.md).
- Existing basic Practice sessions/lexical feedback remain available; expanded Practice is future work.

## Ordered priorities

1. **Current:** resolve STT-001A's runtime compatibility gate with owner approval before implementation. Preserve Vosk as default/fallback; no automatic cloud fallback or Deepgram implementation. Main Live Windows acceptance remains pending using the existing backend, database and cache: one spoken question, main-window transcript/source-backed result, abstention and stop/restart, with EN/ES tracked separately.
2. Review task-level architecture decisions within the approved pragmatic Clean Architecture direction; then refactor incrementally with clear React/Electron feature boundaries. Preserve APIs, retrieval policy, permissions and validated capture. The refactor is not completed.
3. Windows backend startup is available through [`dev-api.bat`](../dev-api.bat) (DEV-001, verified in CMD); it uses the existing venv and does not install packages or create environments.
4. AI-001A/B provide opt-in automatic local fallback only after final no-evidence, using question/language and fixed instructions without execution capabilities. Validate an approved existing local model on Windows for EN/ES quality, cold/warm latency, audio continuity, replacement and teardown before claiming real-provider acceptance. Documentary priority, default-disabled behavior and manual/Practice policies remain intact. AI-001C has no approved scope and is not started.
5. Improve Live from real user feedback. As a core Live acceptance requirement, validate screen-sharing exclusion in actual Windows Teams, Zoom and Google Meet sessions before making compatibility claims. The native protection request alone is insufficient.
6. Consider expanded Practice Mode later; do not design or implement additional exercises or AI evaluation now.

Packaged production capture remains disabled. Its bootstrap/authentication/origin design and independent Windows acceptance are separate pending work, not part of development-mode validation.

Each adopted task needs one objective, scope/exclusions, automated checks, human acceptance where applicable and small Conventional Commits. No unapproved dependencies, downloads, custom agents or changes to the working audio pipeline.
