# Audio-to-Vosk lab — incremental acceptance tests

**Current status:** User-confirmed Windows audio RMS and live Vosk transcription PASS. Question detection has been user-confirmed on Windows. Document-backed exact answer display is now the active Windows acceptance test.

## Prerequisites (Windows CMD)

1. Keep your earlier source backup. The clean source ZIP does **not** include Vosk binaries or models. The original `interview-copilot(1).zip` contains both expected folders:
   - `local-data/models/vosk-model-small-en-us-0.15`
   - `local-data/models/vosk-model-small-es-0.42`
   Copy both into the same paths under the extracted clean project; do not rename them.
2. Start the local backend, with Vosk dependencies:

   ```bat
   cd apps\api
   ..\..\.venv\Scripts\python.exe -m pip install -r requirements-live.txt
   ..\..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8765
   ```

   For a first installation, create a venv and install `requirements-dev.txt` as described in the root README. If needed, set `COPILOT_MODELS_DIR` to the folder containing both model directories.
3. In a browser on the same Windows PC, visit `http://127.0.0.1:8765/live/status`. Verify `runtime_installed: true` and `languages.en-US.available: true` or `languages.es-MX.available: true`.
4. Close any old Vite/desktop development process using port 5173. Start the independent lab:

   ```bat
   cd apps\desktop
   npm install
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
- Only this lab is served by local Vite (`http://127.0.0.1:5173`), matching the backend's existing CORS and WebSocket Origin restrictions. It deliberately does **not** relax Origin checks to permit `file://`/`null`.
- An AudioWorklet resamples whichever native device rate (commonly 44.1 or 48 kHz) to PCM16 little-endian, mono, 16 kHz in 100 ms/3200-byte frames. Unit tests verify both sample-rate cases.
- Audio is sent only to `ws://127.0.0.1:8765/live/transcribe` and processed by the existing Vosk backend; no audio file is recorded or uploaded to an external service.
- The capture may include **all** output sound on the current Windows device, so use synthetic non-private speech and stop when finished. This is not production-secured or packaged.
- This lab displays detected questions and the original answer plus source only when existing backend `suggestion` events report `match_type: exact_qa`. Other questions show no exact match. No new retrieval algorithm or LLM is involved. The backend itself is unchanged.

## Troubleshooting by the first failing signal

- `FALLO: Failed to fetch` or connection issue: start the API on 127.0.0.1:8765 and verify `/live/status`.
- `Vosk (en-US/es-MX) no está disponible`: install `requirements-live.txt` and check exact model directory names.
- No audio track/RMS: rerun the known-good `npm run lab:audio` and report any difference; do not redesign capture blindly.
- RMS changes but `PCM enviado` remains zero: inspect `AudioWorklet` module loading in Electron DevTools (capture succeeded; conversion did not).
- PCM counter increases but no words appear: check the chosen language, Vosk availability, playback voice/volume and final result after one second of silence.
- `WebSocket cerrado: ...` or `speech_error`: report status and close code only; do not send sensitive transcript or audio recordings.

## Third acceptance test — question detection

Use the same `npm run lab:transcribe` command. Speak a question and allow Vosk to produce a **final** transcript; look under **Preguntas y respuestas documentadas**. Try `What is authentication?` in English and `¿Qué es la autenticación?` in Spanish, selecting the matching model. Then play `I use Python every day.`; it should remain transcript-only. The backend uses a simple EN/ES question-cue heuristic, not semantic understanding. This question-detection stage is user-confirmed PASS on Windows.

## Fourth acceptance test — original document answer and source

1. Keep FastAPI running and import the existing **non-private sample Q&A** once. From the project root in CMD:

   ```bat
   curl.exe -X POST -F "file=@samples/interview-questions.md" http://127.0.0.1:8765/documents
   ```

   HTTP 201 means imported; HTTP 409 means the identical document was already imported.
2. Run `npm run lab:transcribe` from `apps/desktop`, select English, and capture a spoken **“What is authentication?”**. Allow Vosk to finalize.
3. Confirm that **Preguntas y respuestas documentadas** displays the original sample answer beginning **“Authentication verifies who a user is.”** and cites **`interview-questions.md`**.
4. Speak **“What is Python?”** (not present in the sample). Confirm it says **“Sin coincidencia exacta en tus documentos”**, with no invented answer.
5. Stop the capture, then start again and verify the interface is reset.

Exact-match retrieval is intentionally strict. A transcription error or paraphrase may produce no match; do not change this behavior in this milestone. Preserve your private documents locally.

## Fifth acceptance test — first-utterance question reliability

The Windows test showed that Vosk sometimes delays finalizing a question and the user had to repeat it. Without changing capture or Vosk, the backend now tries an **early exact-Q&A lookup** only after it sees the same complete question candidate in four consecutive Vosk partial updates. Early lookups cannot produce a `no_evidence` card, and finalized results remain the fallback. The same question is suppressed for 120 seconds after a successful early or final suggestion. This is a heuristic, not a guarantee: if Vosk consistently misrecognizes the words, this change cannot correct the recognizer.

After installing this patch, restart FastAPI, then `npm run lab:transcribe` (the desktop code is unchanged). With the sample Q&A imported, play **one** spoken "What is authentication?" followed by silence. Verify whether one source-attributed answer appears without repeating. Also play an unrelated question and confirm it does not show an invented answer. **Real Windows validation: pending.**


## Semantic Q&A lab (optional, not yet Windows validated)

See `README.md` for the explicitly authorized model download and indexing steps.
A `semantic_qa` message is displayed as **a possible answer requiring review**;
`exact_qa` retains its verified label and priority. Unindexed or ambiguous questions
continue to show no sufficient source answer. The audio pipeline is unchanged.
