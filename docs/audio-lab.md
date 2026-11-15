# Windows audio lab — first real acceptance test

## Goal
Prove actual audio capture before integrating FastAPI, STT or retrieval.

## Scope
- Electron 39 `setDisplayMediaRequestHandler`, `getDisplayMedia`, `AudioContext` and an RMS meter.
- App asks for explicit consent. It uses the first available screen as the video source needed by the system audio loopback request.
- Video is neither displayed nor saved. The loopback may capture ALL audio output from Windows (not just one meeting app).
- The lab has no network calls, raw audio logging, files, backend or API keys.

## Test on Windows (CMD)
1. Confirm the main Interview Copilot app is closed; do not share private audio.
2. `cd apps\desktop && npm install` (first run only).
3. `npm run lab:audio`.
4. Check the consent checkbox and click **Iniciar prueba**.
5. Play a nonsensitive sound in Windows using the speakers/headphones you normally use.
6. Confirm `Pista: live` and that RMS becomes > 0 while sound plays, then returns near zero at silence.
7. Click **Detener**, verify track resources stop and the meter resets.

**PASS** only if steps 6–7 are witnessed. **FAIL** if capture denies permission, no track is produced, meter stays zero or capture cannot be stopped. Preserve the actual `FALLO: ...` error text (without private data).

## If it fails
- Do not add more mocks or permission brokers yet. Note Windows version, output device, Electron error name and whether a track was created.
- Compare a working, license-compatible reference implementation only after this result; if Chromium loopback remains broken, isolate an alternative native WASAPI proof of concept.

## Next slice after PASS
The user confirmed the RMS capture test works on Windows. The **independent** audio-to-Vosk lab is now in `transcription-lab.md` and can be launched with `npm run lab:transcribe`. The original `npm run lab:audio` has not changed. Do not claim audio-to-text PASS until the real Windows test is witnessed.
