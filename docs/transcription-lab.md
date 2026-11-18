# Audio-to-Vosk lab — incremental acceptance tests

**Current status:** The owner validated this isolated Windows lab: system audio/RMS, PCM, Vosk English transcription, conversational question detection, exact Q&A with sources and local FastEmbed retrieval with 204 indexed questions. These are owner-confirmed results, not new executions or benchmarks. Spanish support exists; complete integrated Spanish validation is not established.

The active milestone is now [acceptance in the main Live window](live-mode.md), which remains pending. The staged procedures below are retained for regression isolation; they do not establish integrated acceptance or screen-sharing exclusion.

## Prerequisites (Windows CMD)

1. Preserve your working venv, database/cache and model folders. Source checkouts/ZIPs do **not** include installed Vosk binaries or model files. The expected model folders are:
   - `local-data/models/vosk-model-small-en-us-0.15`
   - `local-data/models/vosk-model-small-es-0.42`
   Reuse existing files; do not rename them. `COPILOT_MODELS_DIR` can override their parent directory. Historically these models were supplied in the owner's `interview-copilot(1).zip`; that private archive is not a public installation prerequisite. Missing models require separately approved acquisition.
2. For a first installation, follow [README setup](../README.md#windows-setup-cmd). Only if Vosk dependencies are missing and installation is approved, run from the project root:

   ```bat
   .venv\Scripts\python.exe -m pip install -r apps\api\requirements-live.txt
   ```

   Keep the already-working backend running, or start it from the project root:

   ```bat
   .venv\Scripts\python.exe -m uvicorn app.main:app --app-dir apps\api --host 127.0.0.1 --port 8765
   ```
3. In a browser on the same Windows PC, visit `http://127.0.0.1:8765/live/status`. Verify `runtime_installed: true` and `languages.en-US.available: true` or `languages.es-MX.available: true`.
4. Close any old Vite/desktop development process using port 5173. Start the independent lab:

   ```bat
    cd apps\desktop
   npm run lab:transcribe
   ```

## Acceptance test

1. Select `English` or `Español` to match the installed Vosk model.
2. Check the explicit local-processing consent box, click **Iniciar transcripción**.
3. Observe an active audio track, changing RMS during playback, and an increasing `PCM enviado` counter.
4. Play a harmless **spoken** phrase from Windows audio (e.g. `What is authentication?`), ideally leaving one second of silence afterward.
5. Confirm a recognizable *partial or final* text appears; not necessarily verbatim because small Vosk models may misrecognize words.
6. Click **Detener**, confirm the backend finishes and the audio capture stops. Re-start once to check lifecycle.

**PASS requires both** real PCM being sent and recognizable transcription in Windows. An RMS-only PASS, test-suite PASS, or an empty `final` message does **not** count.

## Architecture and security

- The original `npm run lab:audio` is unchanged. This second lab uses its validated `getDisplayMedia` call, handler and AudioContext capture path.
- This lab and the main development integration use local Vite (`http://127.0.0.1:5173`), matching the backend's CORS and WebSocket Origin restrictions. Run them separately. Do **not** relax Origin checks to permit `file://`/`null`.
- An AudioWorklet resamples whichever native device rate (commonly 44.1 or 48 kHz) to PCM16 little-endian, mono, 16 kHz in 100 ms/3200-byte frames. Unit tests verify both sample-rate cases.
- Audio is sent only to `ws://127.0.0.1:8765/live/transcribe` and processed by the existing Vosk backend; no audio file is recorded or uploaded to an external service.
- The capture may include **all** output sound on the current Windows device, so use synthetic non-private speech and stop when finished. This is not production-secured or packaged.
- Current lab/Live automatic retrieval prioritizes `exact_qa`, then optional `semantic_qa` labeled as a possible answer requiring review, with source references. Weak/ambiguous or unindexed non-exact questions may produce no evidence. Manual `/answers` uses exact/FTS instead. No LLM is involved, and document fragments are not automatic Live candidates.

## Troubleshooting by the first failing signal

- `FALLO: Failed to fetch` or connection issue: start the API on 127.0.0.1:8765 and verify `/live/status`.
- `Vosk (en-US/es-MX) no está disponible`: check runtime and exact model directory names; use the approved setup steps if installation is needed.
- No audio track/RMS: rerun the known-good `npm run lab:audio` and report any difference; do not redesign capture blindly.
- RMS changes but `PCM enviado` remains zero: inspect `AudioWorklet` module loading in Electron DevTools (capture succeeded; conversion did not).
- PCM counter increases but no words appear: check the chosen language, Vosk availability, playback voice/volume and final result after one second of silence.
- `WebSocket cerrado: ...` or `speech_error`: report status and close code only; do not send sensitive transcript or audio recordings.

## Third acceptance test — question detection

Use the same `npm run lab:transcribe` command. Speak a question and allow Vosk to produce a **final** transcript; look under **Preguntas y respuestas documentadas**. Try `What is authentication?` in English and `¿Qué es la autenticación?` in Spanish, selecting the matching model. Then play `I use Python every day.`; it should remain transcript-only. The detector uses EN/ES lexical cues, not semantic understanding. Question detection is owner-validated in the lab; this procedure does not establish complete integrated Spanish validation.

## Fourth acceptance test — original document answer and source

1. Keep FastAPI running and import the existing **non-private sample Q&A** once. From the project root in CMD:

   ```bat
   curl.exe -X POST -F "file=@samples/interview-questions.md" http://127.0.0.1:8765/documents
   ```

   HTTP 201 means imported; HTTP 409 means the identical document was already imported.
2. Run `npm run lab:transcribe` from `apps/desktop`, select English, and capture a spoken **“What is authentication?”**. Allow Vosk to finalize.
3. Confirm that **Preguntas y respuestas documentadas** displays the original sample answer beginning **“Authentication verifies who a user is.”** and cites **`interview-questions.md`**.
4. With only the synthetic sample as the relevant knowledge, speak an unrelated question absent from it. Expect **“Sin respuesta suficientemente relacionada en tus documentos”**, with no invented answer. With an existing larger database, choose a question known to lack evidence; absence from this sample alone proves nothing about other documents or semantic candidates.
5. Stop the capture, then start again and verify the interface is reset.

Exact matching is normalized and takes priority; it returns stored wording and sources, not a factual certification. Paraphrases may produce a labeled semantic candidate if indexed and sufficiently distinct; otherwise no answer. Do not change the retrieval policy just to make an acceptance example pass. Preserve private documents locally. Importing a supported format does not guarantee extracted Q&A; see [format limitations](setup.md#documents-and-retrieval).

## Fifth acceptance test — first-utterance question reliability

Historical motivation: a Windows test showed delayed Vosk finalization and repeated questions. The implemented backend tries an **early exact-Q&A lookup** after four identical question-shaped partial updates. Early lookups cannot produce a `no_evidence` card; finals still run and can use semantic retrieval. Final-question deduplication uses a 120-second TTL, while the partial tracker remembers attempted candidates within a bounded connection-local cache. These are heuristics, not guarantees, and cannot correct consistently misrecognized words.

With the known Q&A available, play **one** spoken "What is authentication?" followed by silence. Verify whether one source-attributed answer appears without repeating. Also play an unrelated question and confirm it does not show an invented answer. The lab pipeline is owner-validated, but a separate timing guarantee for the early-partial path is not established; first-utterance behavior in the main integration remains an explicit acceptance check.


## Semantic Q&A lab (optional, owner-validated in isolation)

The owner confirmed local semantic retrieval with 204 indexed questions in the lab, not complete main-window acceptance or general retrieval accuracy. See [semantic setup](setup.md#optional-local-semantic-setup) for explicit indexing and separately authorized download steps; skip them when the existing cache/index works.
A `semantic_qa` message is displayed as **a possible answer requiring review**;
`exact_qa` retains its exact-match label and priority. Without an exact match,
unindexed or ambiguous candidates may leave no sufficient source answer.
The audio pipeline is unchanged.
