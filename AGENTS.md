# Interview Copilot — Agent development rules

## Scope and authority
- **Live Mode** is the primary product; preserve basic Practice Mode unless expansion is approved.
- The owner controls product behavior, architecture, dependencies and scope. Explain trade-offs before material changes. Routine decisions inside an approved task need no repeated permission.
- Inspect Git branch and working tree first. Never overwrite unrelated work, delete user data, or stage, commit or push without authorization.
- No new dependencies, services, models/downloads, custom agents, generators, Docker or vector DB services without approval.

## Communication
- Explain findings, decisions and recommendations in Spanish unless the owner requests another language.
- Use short sentences, active voice, precise language and consistent terminology. Explain one idea at a time; add examples when useful and preserve necessary technical terms.
- Keep explanations as short as the task allows, without omitting important evidence, risks or limitations.
- Apply these plain-language principles as inspiration from ASD-STE100; do not claim formal ASD-STE100 compliance.

## Engineering
- Work in small, testable tasks with explicit scope, exclusions, acceptance criteria, automated checks and human validation.
- Progressively apply pragmatic backend Clean Architecture and feature-oriented React/Electron organization. Prefer a few concrete ports and cohesive modules over speculative abstractions, generic repositories or unnecessary frameworks.
- Keep external APIs, STT/audio processing, retrieval behavior and document semantics stable unless specifically approved. Native/provider concerns belong in infrastructure; compose adapters at boundaries.
- Use strict typing, readable code, professional English docstrings for public Python APIs, and comments explaining non-obvious decisions.
- Bound streaming buffers and background lifetimes; cancel or suppress obsolete results on replacement, stop, disconnect or session finish, then release resources safely.

## Test discipline
- Prefer a small number of meaningful, focused tests for changed behavior. Each case must protect a distinct contract, boundary, risk or regression; avoid redundant cases, unnecessary mocks and excessive testing infrastructure while preserving essential security and regression coverage.
- Test observable behavior rather than object identity or incidental implementation details. Do not add tests merely to increase test counts or coverage percentages.
- Prefer deterministic checks and existing evidence before real-model evaluations. Define an explicit evaluation budget, including warmups and failed attempts; do not repeat benchmarks for test-only or documentation changes.
- Run focused checks first, then necessary regressions. For documentation-only changes, run only relevant documentation checks, not full application suites. Report removed redundancy, preserved protections and actual results; mocks do not establish real-model or Windows acceptance.

## Security and product invariants
- Windows system-audio capture includes **all Windows output**. Require informed consent and a real click **inside the isolated, nonpersistent capture window**. The main Electron renderer remains sandboxed without capture permissions.
- Restrict IPC to validated, bounded events, never raw audio or credentials. Do not persist Live audio/transcripts or log private content. Keep cloud credentials server-side and out of repositories, renderer state and distributable archives.
- Provider selection is explicit: Vosk stays the local default; optional local/cloud STT must not silently switch. Cloud STT requires separate informed audio consent.
- Preserve Live retrieval order: normalized exact Q&A with source → optional semantic Q&A labeled for review → no documentary evidence. Opt-in AI suggestions remain separate, unverified and source-free. Do not implicitly change manual retrieval or indexing.
- Screen-sharing exclusion is **best effort**, never proof of invisibility. Capture is Windows development-only with restricted origins; packaged support needs separate approval and acceptance.
- Preserve working databases, documents, cached models and embeddings; never reinstall or reindex solely for validation.

## Evidence and delivery
- Distinguish **IMPLEMENTED**, **VALIDATED**, **PENDING VALIDATION**, **PLANNED** and **UNKNOWN**. Mocks are not evidence of Windows/audio/network/model or conferencing acceptance.
- Run relevant tests. Complete regression commands:
  - `cd apps/api && python -m pytest -q`
  - `cd apps/desktop && npm run test:electron && npm run test:ui && npm run test:audio && npm run lint:electron && npm run build`
- Do not install missing dependencies without approval; report blocked checks, especially native Windows builds.
- Report changed files, rationale, tests/results, risks and outstanding real-Windows checks. Never claim acceptance without evidence or disclose private transcripts.

## Documentation ownership
- `README.md`: overview/setup; `docs/architecture.md`: boundaries and design; `docs/roadmap.md`: single task board; `docs/live-mode.md`: acceptance evidence; `docs/technical-vocabulary.md`: keyterm profiles.
- Keep task status and historical test numbers out of this file; maintain them in their respective documents.
