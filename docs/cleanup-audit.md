# Cleanup audit

> Historical snapshot audit, not the current feature-status report. The retained notes below describe an earlier cleanup of supplied ZIPs. Subsequent owner validation established isolated Windows audio, PCM, Vosk English, question detection and exact/semantic retrieval. Main Live integration is implemented but complete Windows acceptance remains pending; see [current status](live-mode.md) and [architecture](architecture.md).

Input: `desktop.zip`, `api.zip`, `interview-copilot(1).zip` (uploaded source snapshots). Originals were not modified.

## Kept
- FastAPI, all backend parsing/storage/retrieval/Vosk modules and API tests.
- React Knowledge Base / Practice / manual Live, native Electron window settings.
- Example documents and synthetic audio/retrieval fixtures.
- A focused Electron smoke test suite for trusted IPC, window security and origin checks.

## Removed from the delivered code tree
- Both `.opencode/agents/` configs, project-specific `.opencode` skill, `opencode.jsonc` and previous agent prompts.
- Stale reports, long debug histories, old permission experiment plans, generated Chromium/pytest/mypy/Vite caches and compiled output.
- Old isolated `capture-manager`, capture popup, preload, AudioWorklet and controller plus obsolete tests that only verified this now-removed path.
- Redundant `apps/api/package-lock.json` (Python-only service).
- Model binaries, local user databases/documents, temporary Chromium profiles and npm/Python dependencies are excluded from this source distribution **but have not been deleted from the user's original computer or ZIP files**.

## Caveats
- No Git history was rewritten or destroyed. The supplied source ZIP did not contain `.git`; if a local Git repo exists, keep its backups and review a diff before replacing files.
- Automated test totals at the time of this cleanup were **not comparable** to old 201-pass runs, because the nonworking capture branch and its tests were intentionally removed. This note supplies no current test totals.
- At the time of this audit, the independent lab had not yet been validated against real Windows hardware. That historical limitation was superseded by the owner's subsequent lab confirmations; it must not be read as the current lab status or as proof of integrated acceptance.
