"""Opt-in paced PCM acceptance probe of the actual Live WS/application/CPU worker.

Uses only previously approved synthetic evaluation fixtures/models. This is not
physical Windows capture or human-speech acceptance. Saves counts/timings only,
never hypotheses, detected questions, audio or documentary content.
Run with the application's Python environment; native recognition stays in the
separately configured isolated COPILOT_WHISPER_PYTHON environment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import queue
import struct
import sys
import tempfile
import threading
import time

from evaluate import DEFAULT_OUTPUT, ROOT, read_pcm, score


def main() -> None:
    """Replay EN/ES technical questions in real time and report empirical p95."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("repeats must be positive")
    sys.path.insert(0, str(ROOT / "apps/api"))
    from fastapi.testclient import TestClient
    from app.application.generation import GenerationService
    from app.main import create_app

    manifest = json.loads((DEFAULT_OUTPUT / "manifest.json").read_text(encoding="utf-8"))
    rows: list[dict] = []
    summaries: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="live-probe-", dir=DEFAULT_OUTPUT) as directory:
        app = create_app(Path(directory))
        app.state.generation = GenerationService()
        with TestClient(app) as client:
            available = client.get("/live/status").json()["providers"]["faster-whisper"]
            if not available["available"]:
                raise SystemExit("Whisper unavailable: configure the existing local runtime/model; nothing was downloaded")
            for language, locale in (("en", "en-US"), ("es", "es-MX")):
                sid = client.post("/sessions", json={"mode": "live"}).json()["id"]
                response = client.post(f"/sessions/{sid}/live-token", json={
                    "language": locale, "provider": "faster-whisper", "consent": True,
                })
                response.raise_for_status()
                token = response.json()["token"]
                with client.websocket_connect("/live/transcribe", headers={"origin": "http://localhost:5173"}) as ws:
                    ws.send_json({"type": "start", "token": token, "provider": "faster-whisper", "language": locale})
                    ready = ws.receive_json()
                    if ready.get("type") != "ready":
                        raise SystemExit("Live startup failed: " + str(ready.get("code", "unknown")))
                    items = [item for item in manifest if item["language"] == language and item["category"] == "clean"]
                    for repeat in range(args.repeats):
                        for item in items:
                            path = DEFAULT_OUTPUT / "audio" / (item["id"] + ".wav")
                            if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                                raise SystemExit("Synthetic input hash mismatch")
                            pcm = read_pcm(path)
                            samples = struct.unpack(f"<{len(pcm) // 2}h", pcm)
                            # Independent waveform endpoint proxy, not a human annotation:
                            # last sample exceeding 128/32768 amplitude (~-48 dBFS).
                            end_sample = max(index + 1 for index, value in enumerate(samples) if abs(value) > 128)
                            received: queue.Queue = queue.Queue(maxsize=1)

                            def read_final() -> None:
                                try:
                                    while True:
                                        event = ws.receive_json()
                                        arrived = time.perf_counter()
                                        if event["type"] == "error":
                                            received.put((None, event.get("code", "unknown")))
                                            return
                                        if event["type"] == "final":
                                            received.put((arrived, event))
                                            return
                                except Exception:
                                    received.put((None, "connection_closed"))

                            reader = threading.Thread(target=read_final, daemon=True)
                            reader.start()
                            started = time.perf_counter()
                            # Match the 100 ms capture cadence, including 1 s trailing silence.
                            audio = pcm + bytes(32000)
                            for offset in range(0, len(audio), 3200):
                                frame = audio[offset:offset + 3200]
                                target = started + (offset + len(frame)) / 32000
                                time.sleep(max(0, target - time.perf_counter()))
                                ws.send_bytes(frame)
                            try:
                                arrived, event = received.get(timeout=12)
                            except queue.Empty:
                                raise SystemExit("No final within the bounded probe deadline") from None
                            reader.join(timeout=1)
                            if arrived is None:
                                raise SystemExit("Live probe failed: " + str(event))
                            row = {"id": item["id"], "language": language, "repeat": repeat,
                                   "waveform_eos_to_final_ms": round((arrived - started - end_sample / 16000) * 1000, 2),
                                   "server_eos_to_emit_ms": event.get("end_of_speech_latency_ms"),
                                   **score(item["text"], event["text"])}
                            rows.append(row)
                    ws.send_text("stop")
                    try:
                        ws.receive_json()
                    except Exception:
                        pass
                client.post(f"/sessions/{sid}/finish").raise_for_status()
                selected = [row for row in rows if row["language"] == language]
                timings = sorted(row["waveform_eos_to_final_ms"] for row in selected)
                p95 = timings[math.ceil(0.95 * len(timings)) - 1]
                summaries.append({"language": language, "observations": len(timings),
                                  "p95_ms_nearest_rank": p95, "max_ms": max(timings),
                                  "wer_percent": 100 * sum(row["word_edits"] for row in selected)
                                  / sum(row["reference_words"] for row in selected),
                                  "target_3000_ms_met": p95 <= 3000})
    result = {"kind": "synthetic_paced_asgi_not_windows_capture", "summaries": summaries, "rows": rows}
    (DEFAULT_OUTPUT / "live-latency.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(summaries, indent=2))
    if not all(item["target_3000_ms_met"] for item in summaries):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
