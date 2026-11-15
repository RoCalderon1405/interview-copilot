# Interview Copilot — Agent instructions (single-agent friendly)

## Single active objective
**Validate question detection inside natural, unpunctuated interviewer speech without changing the user-validated Windows audio capture, PCM transport or model.** The user confirmed `npm run lab:audio` and `npm run lab:transcribe` work on Windows. The backend already detects EN/ES question candidates and emits `suggestion` events containing optional exact document answers and source attribution. The lab renders those fields only for trusted `exact_qa` matches. The user validated exact-answer display on Windows. Real speech sometimes includes fillers (e.g., "ah got it the question is what is authentication") that require bounded normalization. Production Live remains manual until a full user-validated flow is ready.

## How to work
1. Read `README.md` and `docs/audio-lab.md`; inspect only the relevant code.
2. Make the smallest change that answers **one** testable question.
3. Ask the user for a real Windows observation as soon as GUI/hardware evidence is necessary. Do not keep rewriting permission handlers based on mocks.
4. Report **PASS**, **FAIL**, or **NOT TESTED** separately for automated and real-Windows checks. A successful build is not proof of audio capture.
5. No second/supervisor agent is required. No global skills, plugins or MCP setup required.
6. Do not install extra dependencies, call paid models, delete private data, commit or push without approval.

## Project boundaries
- Keep React + Electron (native Windows) and Python/FastAPI (local API). No Docker or extra services.
- Preserve existing Knowledge Base, exact/textual Q&A retrieval, source attribution, Practice and backend Vosk protocol.
- Use synthetic English/Spanish audio samples only in testing, never record private calls by default.
- Electron's production renderer must remain sandboxed with context isolation and restricted IPC. The audio lab is a separate process and is NOT approved production code.
- System loopback may include the entire output device; require informed consent and a visible stop control.
- Do not promise screen-sharing invisibility. Respect interview rules and privacy.
- Prefer original, documented implementations and small independent probes over copying unchecked GitHub repositories.
- Never fabricate personal professional experience, citations, measured latency or test outcomes.

## Definition of done for current milestone
`npm run lab:transcribe` detects the question in one complete spoken interviewer turn, such as "Thanks for coming, so here's the question: when designing a REST API, how do you choose between GET, POST, PUT and PATCH?" without requiring the user to repeat it. It must show a question card even if no exact stored Q&A answer exists (honest `no_evidence` state). Preserve the context clause when extracting the question. Automated regression tests and a fresh real-Windows observation are required. No fuzzy match or LLM. Do not change audio capture, Vosk, backend retrieval or production Live.

## Testing
- API: `cd apps/api && python -m pytest -q` (Vosk model tests require an optional local runtime).
- Desktop source checks: `cd apps/desktop && npm run build && npm run test:electron && npm run lint:electron`.
- Original audio lab **real Windows**: `cd apps/desktop && npm run lab:audio` — user-reported PASS.
- Transcription lab: `npm run test:audio` (resampling) and `npm run lab:transcribe` (audio, transcription, simple questions and exact answers: user-confirmed PASS; natural contextual speech detection: pending Windows test).
- Backend models must be installed locally at `local-data/models` or `COPILOT_MODELS_DIR` before testing Vosk. Never download models without consent.

## Reporting (Spanish, concise)
**Estado · Cambios · Verificación automatizada · Prueba Windows · Siguiente acción.** No more than five short points. Keep detailed artifacts in files when necessary.
