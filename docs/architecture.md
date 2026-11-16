# Architecture — Live integration (Windows development)

```text
Main Electron window (React, no media permissions)
    ├── Live page: start/stop capture window
    ├── Live page: transcript + Q&A cards with source
    ├── Knowledge Base / Practice / manual query
    └── restricted preload bridge (open/close/status/events)

Second Electron window (separate, nonpersistent session)
    ├── direct user click + explicit consent
    ├── validated standalone getDisplayMedia loopback path
    ├── AudioWorklet → mono PCM16 @16kHz
    ├── authenticated local WebSocket → FastAPI/Vosk
    └── validated text/status/suggestion IPC → main window

FastAPI localhost:8765
    ├── local Vosk EN/ES STT via /live/transcribe
    ├── heuristic conversational question extraction
    ├── exact Q&A → semantic FastEmbed fallback in SQLite
    └── answer + provenance, or explicit no-evidence
```

Main Electron session explicitly denies display/microphone capture. Second partition allows only a gesture-initiated request from its own main frame; no global blanket grant. The second window captures **all Windows output**. Its frontend currently uses the validated Vite development origin (`127.0.0.1:5173`) and is not approved for packaged file:// production use.

Privacy: no recordings stored; the API processes PCM only on localhost. UI events are text-only, sanitized and bounded in memory. Backups/models/database remain user-controlled and are excluded from source ZIPs. Do not claim capture-window exclusion from screenshots or invisibility.
