# Windows audio lab — first real acceptance test

**Current status:** The owner validated this isolated Windows system-audio test. PCM, Vosk English, question detection and exact/semantic retrieval were subsequently validated in the [transcription lab](transcription-lab.md). Complete [main Live acceptance](live-mode.md), integrated Spanish validation and conferencing exclusion remain pending. The procedure below is retained to isolate regressions, not as the current product milestone.

## Goal
Prove actual audio capture before integrating FastAPI, STT or retrieval.

## Scope
- Electron 39 `setDisplayMediaRequestHandler`, `getDisplayMedia`, `AudioContext` and an RMS meter.
- App asks for explicit consent. It uses the first available screen as the video source needed by the system audio loopback request.
- Video is neither displayed nor saved. The loopback may capture ALL audio output from Windows (not just one meeting app).
- The lab has no network calls, raw audio logging, files, backend or API keys.

## Test on Windows (CMD)
1. Confirm the main Interview Copilot app is closed; do not share private audio.
2. `cd apps\desktop`; if dependencies are missing, follow [README setup](../README.md#windows-setup-cmd) with approval first.
3. `npm run lab:audio`.
4. Check the consent checkbox and click **Iniciar prueba**.
5. Play a nonsensitive sound in Windows using the speakers/headphones you normally use.
6. Confirm `Pista: live` and that RMS becomes > 0 while sound plays, then returns near zero at silence.
7. Click **Detener**, verify track resources stop and the meter resets.

**PASS** only if steps 6–7 are witnessed. **FAIL** if capture denies permission, no track is produced, meter stays zero or capture cannot be stopped. Preserve the actual `FALLO: ...` error text (without private data).

## If it fails
- Do not add more mocks or permission brokers yet. Note Windows version, output device, Electron error name and whether a track was created.
- If a regression is confirmed, discuss evidence and alternatives with the owner before replacing capture or starting a native WASAPI proof of concept.

## Subsequent slices and current priority
The independent audio-to-Vosk lab can be launched with `npm run lab:transcribe`; its English pipeline and retrieval are owner-validated. The product now reuses that path in the main Live interface, which requires its own Windows acceptance. Lab success does not prove integrated operation or screen-sharing exclusion. Do not rewrite the working audio path without concrete evidence and approval.
