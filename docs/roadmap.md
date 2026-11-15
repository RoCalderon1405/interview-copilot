# Roadmap — one active milestone

**DONE (user-reported):** `npm run lab:audio` detects live Windows playback on the RMS meter.

**DONE (user-reported):** `npm run lab:transcribe` sends Windows PCM16 to FastAPI/Vosk and displays recognizable speech.

**DONE (user-reported):** spoken English questions are detected separately from statements on real Windows playback.

**DONE (user-reported):** exact Q&A response and source display for spoken "what is authentication".

**ACTIVE / awaiting real Windows verification:** return exact Q&A matches from a stable Vosk partial, so the same question does not need repeating just because Vosk has not finalized it yet.

Only after this focused stable-partial acceptance test is verified on real Windows:
1. Integrate the user-validated audio/transcription/question pipeline into Live with consent and stop controls.
2. Add paraphrase retrieval and optional LLM fallback with clear labeling/opt-in.

**DEFERRED:** Spanish/English full UI localization, document preview/download, Practice evaluation improvements, overlay polish, distribution. Docker, new development agents, complex capture brokers and skill installation are not part of the current scope.

### Latest targeted improvement — early exact Q&A

The Windows observation showed Vosk sometimes recognized the same question only after repeated speech. The backend now accepts a question-shaped *partial* only after four identical updates. It queries existing exact Q&A once, emits only verified exact answers before the Vosk final, and suppresses the duplicate final card. Non-matching partials remain invisible as suggestions; ordinary final questions still show `no_evidence`. The repeat-dedupe window is 120 seconds. **Windows validation is pending.** No audio, model, RAG or GUI changes.
