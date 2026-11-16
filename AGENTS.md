# Interview Copilot — Development rules

## Product and decision authority
- Live Mode is the primary product; expanded Practice Mode is a future enhancement. Preserve the existing basic Practice workflow without expanding it implicitly.
- The project owner decides product behavior and major architecture. Ask focused questions about ambiguous requirements; present recommendations and trade-offs before unapproved changes.
- Do not replace technologies, change retrieval/document semantics or permissions, delete working modules/user data, or expand scope without approval.
- Use built-in Plan and Build modes. No custom agents, additional skills, dependencies, model downloads or services without owner approval. No project generators, Docker or vector DB services for the current scope.

## Engineering
- Give each task one small, testable responsibility, explicit exclusions, acceptance criteria, relevant automated tests and required human validation.
- Progressively adopt pragmatic backend Clean Architecture with inward dependencies; organize React/Electron by feature and responsibility. This is an approved direction, not a completed refactor or approval of every proposed abstraction.
- Keep code readable and strictly typed; use professional English docstrings for public Python APIs and meaningful contracts. Explain non-obvious decisions, not syntax. Avoid generic repositories and speculative wrappers.
- Preserve validated `audio-lab/transcribe.js`, PCM processing and Vosk/semantic behavior unless concrete evidence justifies a change. Preserve existing API contracts during migration.
- Prefer small, coherent Conventional Commits. Inspect Git state first; never overwrite or stage unrelated work. Do not commit or push without authorization.

## Security and retrieval boundaries
- Audio capture requires explicit consent and a real click **inside the capture window**. It captures **all Windows output**, not one application.
- Keep capture in a separate nonpersistent Electron session. The main Electron renderer remains sandboxed, denies media permissions and cannot call display capture.
- Relay only validated, bounded text/status/suggestion/metric events through restricted IPC; never raw audio or credentials. Do not persist Live transcripts or log private content.
- Exact Q&A takes priority and returns stored wording with source references, not a generated answer or factual certification. Semantic matches must be labeled **possible answers to review**. No sufficient evidence means no answer; LLM fallback is planned, not implemented.
- Document import does not guarantee Q&A extraction. Preserve the distinct manual-search and Live retrieval policies; see `docs/architecture.md`.
- Screen-sharing exclusion is a core Live requirement, but `setContentProtection` is best-effort. Never claim guaranteed exclusion or undetectability; validate actual Windows conferencing sessions.
- Integrated capture is Windows **development mode** only, via Vite. Packaged support requires separate authentication/origin and Windows acceptance work; do not relax CORS/WS origins to enable it.
- FastEmbed remains local and opt-in. Keep secrets, documents, databases, embeddings, models and generated/cache files out of Git and distributable source ZIPs.

## Evidence and current acceptance
- Distinguish IMPLEMENTED (code inspected), VALIDATED (execution evidence), PENDING VALIDATION, PLANNED and UNKNOWN. Mock tests do not prove hardware, Windows or screen-sharing behavior.
- The owner validated the isolated lab: Windows audio, PCM, Vosk English, question detection, source-backed exact Q&A and FastEmbed with 204 indexed questions.
- Main Live integration still needs complete Windows acceptance; complete integrated Spanish validation and conferencing exclusion are not established.
- Use `docs/live-mode.md` for the current acceptance procedure and status. Keep the working backend/database/models; do not reindex just to validate the integration. Report failing stage and message, not private transcripts.
- Maintain existing docs rather than duplicate reports: README for setup, architecture for boundaries, Live docs for current validation, roadmap for priorities.

## Checks
- `cd apps/api && python -m pytest -q`
- `cd apps/desktop && npm run test:electron && npm run test:audio && npm run lint:electron && npm run build`
- If `npm run build` is blocked by missing local native dependencies, state that limitation and require `npm install` on Windows, then rebuild.
