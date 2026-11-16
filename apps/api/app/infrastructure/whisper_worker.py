"""Private CPU-only worker entry point; stdout is bounded protocol, never a log.

This standalone script runs in a trusted isolated Python environment. It has no
FastAPI, database, retrieval or LLM imports. Audio exists only in pipe/memory.
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import sys
from pathlib import Path
from typing import BinaryIO

MAX_PCM = 256000
MAX_TEXT = 3000


def read_exact(stream: BinaryIO, size: int) -> bytes:
    """Read a bounded binary message; EOF never triggers a partial recognition."""
    data = bytearray()
    while len(data) < size:
        block = stream.read(size - len(data))
        if not block:
            raise EOFError
        data.extend(block)
    return bytes(data)


def send(payload: dict[str, object]) -> None:
    """Send one UTF-8 JSON protocol line, not inherited application output."""
    sys.stdout.buffer.write(json.dumps(payload, ensure_ascii=True).encode("ascii") + b"\n")
    sys.stdout.buffer.flush()


def main() -> None:
    """Load only a local model and serve one fixed-language recognition stream."""
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["OMP_NUM_THREADS"] = "4"
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--model", type=Path)
    parser.add_argument("--language", choices=("en", "es"))
    args = parser.parse_args()
    try:
        import ctranslate2
        import numpy as np
        from faster_whisper import WhisperModel

        if "int8" not in ctranslate2.get_supported_compute_types("cpu"):
            raise RuntimeError
        if args.check:
            send({"type": "ready"})
            return
        if args.model is None or not args.model.is_dir() or args.language is None:
            raise RuntimeError
        model = WhisperModel(str(args.model.resolve()), device="cpu", compute_type="int8",
                             cpu_threads=4, num_workers=1, local_files_only=True)
        if model.model.device != "cpu" or not model.model.is_multilingual:
            raise RuntimeError
        send({"type": "ready"})
        while True:
            size = struct.unpack("<I", read_exact(sys.stdin.buffer, 4))[0]
            if not 0 < size <= MAX_PCM or size % 2:
                raise RuntimeError
            pcm = read_exact(sys.stdin.buffer, size)
            audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
            segments, _ = model.transcribe(audio, language=args.language, beam_size=1,
                                          temperature=0, condition_on_previous_text=False,
                                          vad_filter=False, word_timestamps=True)
            texts: list[str] = []
            end: float | None = None
            length = 0
            for segment in segments:
                text = segment.text.strip()
                length += len(text) + 1
                if length > MAX_TEXT:
                    raise RuntimeError
                texts.append(text)
                if segment.words:
                    end = float(segment.words[-1].end)
            send({"type": "final", "text": " ".join(texts).strip(), "end": end})
    except EOFError:
        return
    except Exception:
        # Never serialize native exceptions, PCM, paths or recognized text as errors.
        send({"type": "error"})
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
