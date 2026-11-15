# Architecture — minimal baseline

```
Windows desktop (Electron + React)
  ├─ Knowledge Base / manual Live / Practice UI
  └─ local HTTP 127.0.0.1:8765 → FastAPI
                                      ├─ file parsers (XLSX/DOCX/PDF/TXT/MD)
                                      ├─ SQLite + FTS5, answers with sources
                                      ├─ Practice session/keyword report
                                      └─ optional Vosk WS STT (synthetic tested)

Independent Electron audio lab (no API or audio persistence):
  getDisplayMedia() → AudioContext → RMS meter
```

The previous isolated capture broker was removed because it had no demonstrated Windows end-to-end pass, despite extensive headless tests. Keep this lab independent until real hardware validates capture. Don't build more abstractions around a missing signal.

Security: the production Electron renderer retains context isolation, sandbox, restricted IPC, navigation and popup denial; local API remains development-only without production authentication. Audio lab requires explicit consent and has no network connection.
