"""Apply the approved STT-001B documentation update to the local repository.

Run from the repository root on branch feature/stt-deepgram. The script changes
only the existing docs and does not touch program code, credentials or Git state.
It is idempotent and refuses incompatible document versions.
"""

from pathlib import Path
import re
import sys

ROOT = Path.cwd()
MARKER = '<!-- STT-001B roadmap decisions, 2026-11-16 -->'
ROADMAP = ROOT / 'docs' / 'roadmap.md'
ARCH = ROOT / 'docs' / 'architecture.md'
LIVE = ROOT / 'docs' / 'live-mode.md'

ROADMAP_SECTION = '''<!-- STT-001B roadmap decisions, 2026-11-16 -->
## STT-001B results and agreed product direction

**Observed on Windows (2026-11-16):** Deepgram Nova-3 returned partial and final English transcripts in the Electron capture window and relayed finals/questions to React. The owner observed a small but unmeasured delay. The detector incorrectly treated some spoken test instructions as interview questions. This is **partial acceptance**, not a latency SLA or validated production release. Spanish, interruptions, restart, network failure and end-to-end latency remain unverified. A `no_evidence` documentary response is not an STT failure.

The following decisions are approved **as product direction**, not permission to implement all tasks at once:

- **Question intent (DET-002, next behavior task):** detect both explicit questions and implicit interview requests such as "Tell me about your experience with React", "Walk me through your architecture" and "Explain dependency injection" even without a question mark. Avoid treating operational instructions to the assistant, quoted examples, incomplete phrases or ordinary statements as questions. Test real EN/ES examples, false positives, false negatives, deduplication and abstention. Do not prompt Ollama until an utterance is complete; do not make a large new agent framework.
- **Independent provider selection:** STT: Vosk (local default), Faster-Whisper (optional local), Deepgram Nova-3 (optional cloud); evaluate AssemblyAI later, not as a new automatic fallback. LLM: existing local Ollama and a separately approved future OpenAI API adapter. Never conflate the STT choice with the LLM choice or silently switch cloud providers.
- **BYOK/security (CLOUD-001):** each user configures their own provider account and API Key. Deepgram currently reads an environment variable only; a future explicit settings feature should protect persistent secrets with Windows OS facilities (for example, Credential Manager/DPAPI), never renderer state, plaintext SQLite, logs, Git or bundled installers. Obtain provider-specific informed audio consent before sending it off-device; disabling cloud must preserve local mode.
- **Cost estimates and usage (COST-001):** before a paid session, display a price estimate based on the selected STT/LLM provider, model and planned duration, with clear assumptions and current rates. After the session, show measured STT usage (including provider-billable time when obtainable), actual reported LLM token usage when available and **estimated** monetary cost; avoid claiming access to the provider's invoice. Local API charges are zero, not necessarily zero hardware/electricity cost. Prices and free credits vary and must not be hardcoded as permanent facts.
- **Local session history (HIST-001):** opt-in/approved persistence of session metadata, provider/model, durations, usage estimates and costs. Keep audio and full Live transcripts out of persistent history by default. Define deletion, retention and privacy before implementing.
- **Real-time UX (UI-001/MET-001):** show the actual selected STT provider (not "STT local" for cloud); distinguish partial and final text. Measure time-to-first-partial, end-of-speech-to-final and final-to-suggestion separately, plus p50/p95 in repeatable real Windows tests. Optimize only after measurements.
- **Validation and release:** run EN/ES human speech, realistic Teams/Meet/Zoom system audio, network disconnect/stop/restart, Vosk and Whisper regressions, API/browser security and main-window behavior before closing STT-001B. The app is Windows development-mode only; screen-capture exclusion is best-effort and still unverified in meetings.

The existing exact Q&A > optional semantic candidate > explicit no-documentary-evidence policy stays unchanged. Local Ollama suggestions are separate, clearly marked unverified and opt-in. Future cloud LLM output must follow the same provenance rules. `AGENTS.md` remains short and limited to permanent engineering rules.

'''

ARCH_SECTION = '''<!-- STT-001B architecture addition, 2026-11-16 -->
## Deepgram Nova-3 streaming extension (STT-001B)

The selectable Deepgram provider is an **optional cloud infrastructure adapter** behind the application-owned STT contracts. The capture window still sends PCM16 mono/16 kHz to the authorized FastAPI WebSocket on loopback. Only FastAPI opens a TLS WebSocket to Deepgram; React/Electron do not receive an API Key or contact Deepgram directly. The local defaults and Vosk/Faster-Whisper adapters remain available. A selected provider is bound to the single-use Live grant; no automatic switching or fallback is permitted.

Deepgram interim transcripts (`is_final=false`) are emitted as **replaceable partial UI text**. Segment finals (`is_final=true`) must be accumulated; a completed utterance (`speech_final=true`) is the boundary for question extraction, RAG and optional LLM generation. Neither an interim hypothesis nor a segment final alone authorizes an AI suggestion. Existing bounded PCM flow, send serialization, question deduplication, connection cancellation and stop/cleanup policies must be preserved.

Deepgram currently obtains its key from `COPILOT_DEEPGRAM_API_KEY` in the backend process environment. Availability checks only establish local configuration, not remote authorization, billing status or Internet reachability. The user must separately select cloud STT and explicitly consent to off-device audio transmission. Provider-side processing and retention depend on Deepgram's own terms/settings; a project promise of no **local** audio recording is not a promise of no remote processing. Cloud use may incur costs.

Windows English system-audio capture, interim/final transcripts and React relay have been observed by the owner; this does not yet validate end-to-end latency, Spanish, realistic conferencing, connectivity failure recovery or production packaging. See [Live Mode observations](live-mode.md) and [roadmap tasks](roadmap.md).

### Planned provider, credential and metering boundaries (not implemented)

Keep STT selection independent from LLM selection. Cloud providers require BYOK, explicit privacy consent and OS-backed secret storage on Windows when persistent settings are implemented. Introduce usage counters only with validated provider billing semantics, showing estimated session costs rather than claiming exact invoiced amounts. A local history may persist limited session metadata after explicit approval; raw audio and full Live transcripts remain nonpersistent by default. Do not add a universal provider framework, provider-specific billing database or extra cloud services before their respective tasks are approved.

'''

LIVE_SECTION = '''<!-- STT-001B real Windows observation, 2026-11-16 -->
## STT-001B — initial Deepgram Windows observation (2026-11-16)

**PARTIALLY VALIDATED by the owner:** `/live/status` returned `providers.deepgram.available=true`, while Vosk was available and Faster-Whisper was unavailable because its separate runtime/model environment variables were absent at that startup. The actual Electron capture window connected to Deepgram Nova-3 in English; the owner observed progressively appearing text with a small, unmeasured delay, correctly transcribed several spoken English interview questions and confirmed results in the React main window. Some spoken instructions (e.g. "Tell me if text appears before you're finished speaking") were incorrectly classified as questions. This motivates DET-002, not a claim that cloud STT failed.

**NOT YET VALIDATED:** end-of-speech timing and time to first partial, p50/p95 over repeatable sessions, English question precision/recall, Spanish human audio, provider stop/restart and failure cases, original Vosk/Faster-Whisper regression, cloud costs/metering, actual conference behavior and packaged production use. The UI still contained the inaccurate cloud label "STT local · Live". No complete Windows acceptance is claimed. Further work is tracked exclusively in the [roadmap](roadmap.md), not a separate task list here.

'''


def update_roadmap(content: str) -> str:
    if MARKER in content:
        return content
    current = re.compile(r'^\*\*Current task: STT-001A\*\*.*$', re.MULTILINE)
    if len(current.findall(content)) != 1:
        raise ValueError('Expected one STT-001A current task heading in docs/roadmap.md')
    content = current.sub('**Current validation focus: STT-001B** — Deepgram Nova-3 integration is **IMPLEMENTED / PARTIALLY VALIDATED ON WINDOWS (EN)**. The owner confirmed Electron system-audio capture, progressive English transcripts and final/question relay to React; no measured EOS or first-partial latency yet, and Spanish/network/stop-restart acceptance is pending. STT-001A remains implemented but not fully accepted; keep Vosk as default. **DET-002** (implicit interview requests vs ordinary instructions) is the next approved behavior task. All provider cost, credential and metering features are planned separately; see below.', content)
    old = '| STT-001B | Deepgram Nova-3 STT | Approved future task; not started, excluded from STT-001A | — |'
    new = '| STT-001B | Optional Deepgram Nova-3 streaming with cloud consent and EN/ES selection | Implemented in feature branch; owner validated English partial/final + React relay, Spanish and timing/lifecycle tests pending | Pending commit |'
    if content.count(old) != 1:
        raise ValueError('STT-001B row differs from expected baseline')
    content = content.replace(old,new)
    old = '| DET-002 | Further contextual detection beyond DET-001; scope requires approval | Deferred | — |'
    new = '''| DET-002 | Distinguish implicit interview requests from operational instructions and ordinary speech, EN/ES | Approved next behavior task; not yet implemented | — |
| UI-001 | Label selected cloud/local STT accurately and clearly render interim/final | Pending | — |
| MET-001 | Measure live first-partial, EOS-to-final and final-to-suggestion latency (p50/p95) | Pending | — |
| CLOUD-001 | Windows-secured persistent BYOK configuration and consent/privacy UX | Planned; current Deepgram key is environment-only | — |
| COST-001 | Pre-session cost estimate and post-session provider usage/cost estimate | Planned; no billing telemetry yet | — |
| HIST-001 | Privacy-limited local session usage/cost history with retention controls | Planned; no transcript/audio persistence | — |
| AI-002 | Optional OpenAI cloud LLM provider, independent of STT, with BYOK | Planned; not implemented | — |
| STT-001C | Evaluate optional AssemblyAI cloud streaming after current acceptance | Future evaluation; not implemented | — |'''
    if content.count(old) != 1:
        raise ValueError('DET-002 row differs from expected baseline')
    content = content.replace(old,new)
    content = content.replace('## Established baseline', ROADMAP_SECTION+'## Established baseline', 1)
    old = ('1. **Current:** perform STT-001A human EN/ES Windows acceptance and measure actual end-of-speech-to-main-window p95 ≤3 s, including accuracy, CPU contention and stop/restart. Integration is implemented, not fully accepted; retain Vosk as default and explicit alternative. No CUDA, automatic cloud fallback or Deepgram implementation. Use the existing backend, database and cache without reindexing; validate source-backed results and abstention separately by language/provider.')
    new = ('1. **Current:** finish STT-001B EN/ES human Windows acceptance and repeatable latency/stop/restart/network tests, then address DET-002 contextual question intent with negative and positive EN/ES examples. Preserve Vosk as default and Faster-Whisper as an explicit local alternative; keep all provider changes opt-in. Restore Faster-Whisper runtime variables before comparing it; no CUDA or automatic cloud fallback. Do not reindex the document database solely for STT testing.')
    if content.count(old) != 1:
        raise ValueError('Priority 1 differs from expected baseline')
    content = content.replace(old,new)
    return content


def insert_before_heading(content: str, marker: str, heading: str, section: str) -> str:
    if marker in content:
        return content
    if content.count(heading) != 1:
        raise ValueError('Could not find exactly one heading: '+heading)
    return content.replace(heading, section+heading, 1)


def main() -> int:
    if not all(p.exists() for p in (ROADMAP, ARCH, LIVE)):
        print('ERROR: run from the interview-copilot repository root (docs/ missing).', file=sys.stderr)
        return 2
    # Read and validate all inputs before changing any file.
    originals = {p:p.read_bytes() for p in (ROADMAP, ARCH, LIVE)}
    sources = {p:originals[p].decode('utf-8').replace('\r\n', '\n') for p in (ROADMAP, ARCH, LIVE)}
    updates = {
        ROADMAP: update_roadmap(sources[ROADMAP]),
        ARCH: insert_before_heading(sources[ARCH], '<!-- STT-001B architecture addition, 2026-11-16 -->', '## Current implementation', ARCH_SECTION),
        LIVE: insert_before_heading(sources[LIVE], '<!-- STT-001B real Windows observation, 2026-11-16 -->', '## Current status', LIVE_SECTION),
    }
    for path, content in updates.items():
        if content != sources[path]:
            line_ending = '\r\n' if b'\r\n' in originals[path] else '\n'
            path.write_bytes(content.replace('\n', line_ending).encode('utf-8'))
            print('Updated', path.relative_to(ROOT))
        else:
            print('Already updated', path.relative_to(ROOT))
    print('Done. Inspect: git diff --check && git diff -- docs')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
