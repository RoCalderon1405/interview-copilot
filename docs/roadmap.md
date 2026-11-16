# Roadmap — Interview Copilot

Live Mode is the primary product. This order reflects the owner's priorities, not authorization to implement every item.

## Official task board

This file is the single lightweight task board; [Live Mode](live-mode.md) holds validation evidence and known limitations, not a second task list.

**Current task: DEV-001**, completed in this update: `dev-api.bat` was verified in Windows CMD from an unrelated working directory, including loopback startup, missing-venv errors and backend exit-code propagation. **DET-001** remains implemented but not fully accepted; this task does not expand its scope.

| ID | Description | Status | Commit reference |
| --- | --- | --- | --- |
| DOC-001 | Synchronize product, setup and engineering documentation | Completed | `5fa3ce8` |
| DOC-002 | Establish task tracking and reconcile Live limitations | Completed | `ec65a11` |
| ARCH-001 | Architecture assessment; analysis only, no refactor | Completed | — |
| RESEARCH-001 | Research real-time question detection; research only | Completed | — |
| DET-001 | Conservative conversational question segmentation | In progress; implemented, not fully accepted | `3bc2f05` |
| TEST-001 | Align Vosk integration tests with the partial/final timestamp contract | Completed; test-only correction, production unchanged | — |
| DEV-001 | Simple Windows script to start the local backend | Completed; Windows CMD runtime verified | — |
| LIVE-001 | Complete integrated Live Windows acceptance | Partially validated | `540c27d` (integration, not acceptance) |
| ARCH-002 | Architecture follow-up; scope requires owner definition/approval | Pending | — |
| ARCH-003 | Architecture follow-up; scope requires owner definition/approval | Pending | — |
| ARCH-004 | Architecture follow-up; scope requires owner definition/approval | Pending | — |
| AI-001 | Decide and implement an approved LLM fallback | Pending; not implemented | — |
| DET-002 | Further contextual detection beyond DET-001; scope requires approval | Deferred | — |

**Status meaning:** Completed applies to the stated deliverable (analysis/research is not implementation); implemented means code exists, not that Windows acceptance passed. Partially validated records only confirmed cases. Pending work is not started/accepted; deferred work is not current scope. A commit alone does not close a task. `—` means no dedicated reference recorded; this update's commit is available in Git history.

**Maintenance:** each approved task must update its row when completed, including available commit references and validation limits. Record partial progress without upgrading it to full validation; keep the current-task indicator accurate. Do not create another board or copy conversation history into documentation.

## Established baseline

- Owner-validated isolated Windows lab: system audio, PCM, Vosk English, conversational question detection, exact Q&A with sources and local FastEmbed retrieval with 204 indexed questions.
- Implemented: main Live integration, Spanish support, document management, manual search and native protection controls. The owner confirmed integrated Windows audio, English transcription, Electron-to-React events, conversational detection in tested cases and exact retrieval with sources. Complete acceptance and conferencing checks remain pending; see [current validation](live-mode.md).
- Existing basic Practice sessions/lexical feedback remain available; expanded Practice is future work.

## Ordered priorities

1. **Current:** complete main Live Windows acceptance using the existing backend, database and cache. Test one spoken question, main-window transcript/source-backed result, abstention and stop/restart. Track EN and ES separately; do not infer Spanish validation from English.
2. Review task-level architecture decisions within the approved pragmatic Clean Architecture direction; then refactor incrementally with clear React/Electron feature boundaries. Preserve APIs, retrieval policy, permissions and validated capture. The refactor is not completed.
3. Windows backend startup is available through [`dev-api.bat`](../dev-api.bat) (DEV-001, verified in CMD); it uses the existing venv and does not install packages or create environments.
4. Define and approve LLM fallback provider, context/privacy boundaries, trigger behavior and evaluation before implementation. No fallback is currently available.
5. Improve Live from real user feedback. As a core Live acceptance requirement, validate screen-sharing exclusion in actual Windows Teams, Zoom and Google Meet sessions before making compatibility claims. The native protection request alone is insufficient.
6. Consider expanded Practice Mode later; do not design or implement additional exercises or AI evaluation now.

Packaged production capture remains disabled. Its bootstrap/authentication/origin design and independent Windows acceptance are separate pending work, not part of development-mode validation.

Each adopted task needs one objective, scope/exclusions, automated checks, human acceptance where applicable and small Conventional Commits. No unapproved dependencies, downloads, custom agents or changes to the working audio pipeline.
