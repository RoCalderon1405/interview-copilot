"""Opt-in, CPU-only evaluation of synthetic audio; never imports Live code.

Use an isolated environment for Faster-Whisper. Vosk runs read-only in its
existing environment in a separate process. All generated audio/results stay
under ignored local-data. No model download occurs in this evaluation runner.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import random
import shutil
import statistics
import subprocess
import sys
import threading
import time
import unicodedata
import wave
from array import array
from collections.abc import Callable, Sequence
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "local-data" / "stt-evaluation"
CORPUS = Path(__file__).with_name("corpus.json")


def normalize(text: str) -> str:
    """Normalize case, diacritics, punctuation and whitespace for acoustic scoring."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return " ".join("".join(
        char if char.isalnum() else " "
        for char in decomposed if not unicodedata.combining(char)
    ).split())


def edit_distance(reference: Sequence[Any], hypothesis: Sequence[Any]) -> int:
    """Return Levenshtein edits with bounded row storage."""
    previous = list(range(len(hypothesis) + 1))
    for i, expected in enumerate(reference, 1):
        current = [i]
        for j, actual in enumerate(hypothesis, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (expected != actual)))
        previous = current
    return previous[-1]


def score(reference: str, hypothesis: str) -> dict[str, int | bool]:
    """Return additive counts, permitting corpus-weighted WER/CER aggregation."""
    expected, actual = normalize(reference), normalize(hypothesis)
    return {"word_edits": edit_distance(expected.split(), actual.split()),
            "reference_words": len(expected.split()),
            "character_edits": edit_distance(expected, actual),
            "reference_characters": len(expected), "exact": expected == actual}


def read_pcm(path: Path) -> bytes:
    """Validate evaluation input without converting or silently resampling audio."""
    with wave.open(str(path), "rb") as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate(),
                source.getcomptype()) != (1, 2, 16000, "NONE"):
            raise ValueError("Evaluation requires uncompressed PCM16 mono at 16 kHz")
        return source.readframes(source.getnframes())


def write_pcm(path: Path, pcm: bytes) -> None:
    """Write synthetic evaluation audio only, outside the production capture path."""
    with wave.open(str(path), "wb") as target:
        target.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        target.writeframes(pcm)


def prepare(output: Path) -> None:
    """Create reproducible, non-private Windows SAPI fixtures and robustness probes."""
    audio = output / "audio"
    audio.mkdir(parents=True, exist_ok=True)
    items = json.loads(CORPUS.read_text(encoding="utf-8"))
    # Invoke our reviewed local COM commands inline; do not change Windows'
    # persistent PowerShell script execution policy.
    synthesis = Path(__file__).with_name("synthesize.ps1").read_text(encoding="utf-8")
    quoted_corpus = str(CORPUS).replace("'", "''")
    quoted_audio = str(audio).replace("'", "''")
    command = f"& {{ {synthesis} }} -Corpus '{quoted_corpus}' -OutputDirectory '{quoted_audio}'"
    subprocess.run(["powershell.exe", "-NoProfile", "-Command", command], check=True)
    for item in items:
        if "fixture" in item:
            shutil.copyfile(ROOT / "apps/api/tests/fixtures/live_audio" / item["fixture"],
                            audio / (item["id"] + ".wav"))
        item["category"] = "clean"
    for language in ("en", "es"):
        for name, pcm in (("silence", bytes(3 * 32000)), ("short-silence", bytes(3200))):
            key = f"{language}-{name}"
            write_pcm(audio / f"{key}.wav", pcm)
            items.append({"id": key, "language": language, "text": "", "category": name})
        # Deterministic additive white noise at 15 dB SNR (not a real room recording).
        base = next(item for item in items if item["id"] == f"{language}-api")
        samples = array("h", read_pcm(audio / (base["id"] + ".wav")))
        rms = math.sqrt(sum(value * value for value in samples) / len(samples))
        rng = random.Random(1)
        noisy = array("h", (max(-32768, min(32767, round(
            value + rng.gauss(0, rms / (10 ** (15 / 20)))))) for value in samples))
        key = f"{language}-noise"
        write_pcm(audio / f"{key}.wav", noisy.tobytes())
        items.append({"id": key, "language": language, "text": base["text"], "category": "noise-15db"})
    for item in items:
        path = audio / (item["id"] + ".wav")
        item["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        item["duration_seconds"] = len(read_pcm(path)) / 32000
    (output / "manifest.json").write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")


class MemoryCounters(ctypes.Structure):
    """Windows PROCESS_MEMORY_COUNTERS layout, including process-lifetime peak RSS."""
    _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                *[(name, ctypes.c_size_t) for name in (
                    "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                    "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                    "PagefileUsage", "PeakPagefileUsage")]]


def memory_mib() -> tuple[float, float]:
    """Read current and lifetime-peak working set for this Windows process."""
    if sys.platform != "win32":
        raise RuntimeError("Memory instrumentation in this harness requires Windows")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(MemoryCounters), ctypes.c_ulong]
    counters = MemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return counters.WorkingSetSize / 2**20, counters.PeakWorkingSetSize / 2**20


def measure(operation: Callable[[], Any]) -> tuple[Any, dict[str, float]]:
    """Measure wall/process CPU and sampled RSS; CPU includes native worker threads."""
    readings = [memory_mib()[0]]
    stopped = threading.Event()

    def sample() -> None:
        while not stopped.wait(0.02):
            readings.append(memory_mib()[0])

    monitor = threading.Thread(target=sample, daemon=True)
    monitor.start()
    cpu_start, start = time.process_time(), time.perf_counter()
    try:
        result = operation()
    finally:
        wall, cpu = time.perf_counter() - start, time.process_time() - cpu_start
        stopped.set()
        monitor.join()
    current, lifetime = memory_mib()
    readings.append(current)
    return result, {"wall_seconds": wall, "cpu_seconds": cpu,
                    "cpu_percent_one_core": 100 * cpu / wall,
                    "cpu_percent_machine": 100 * cpu / wall / (os.cpu_count() or 1),
                    "rss_peak_sampled_mib": max(readings), "rss_after_mib": current,
                    "rss_lifetime_peak_mib": lifetime}


def worker(args: argparse.Namespace) -> None:
    """Run one provider/language/config in a fresh, explicitly CPU-only process."""
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["OMP_NUM_THREADS"] = str(args.threads)
    items = [item for item in json.loads((args.output / "manifest.json").read_text(encoding="utf-8"))
             if item["language"] == args.language]
    if args.provider == "faster-whisper":
        def load() -> Any:
            from faster_whisper import WhisperModel
            return WhisperModel(str(args.model), device="cpu", compute_type="int8",
                                cpu_threads=args.threads, num_workers=1, local_files_only=True)

        model, load_metrics = measure(load)
        if model.model.device != "cpu":
            raise RuntimeError("CPU-only evaluation cannot use another device")
        import numpy as np

        def recognize(pcm: bytes) -> str:
            audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
            segments, _ = model.transcribe(audio, language=args.language, beam_size=1,
                                          temperature=0, condition_on_previous_text=False,
                                          vad_filter=False, word_timestamps=False)
            # Consume the lazy generator INSIDE measurement, not just transcribe().
            return " ".join(segment.text.strip() for segment in segments).strip()
        versions = {name: importlib.metadata.version(name) for name in (
            "faster-whisper", "ctranslate2", "av", "numpy", "onnxruntime")}
    else:
        def load() -> Any:
            import vosk
            vosk.SetLogLevel(-1)
            return vosk.Model(str(args.model))

        model, load_metrics = measure(load)
        import vosk

        def recognize(pcm: bytes) -> str:
            recognizer = vosk.KaldiRecognizer(model, 16000)
            recognizer.SetWords(True)
            finals = []
            for offset in range(0, len(pcm), 3200):
                if recognizer.AcceptWaveform(pcm[offset:offset + 3200]):
                    finals.append(json.loads(recognizer.Result()).get("text", ""))
                else:
                    recognizer.PartialResult()
            finals.append(json.loads(recognizer.FinalResult()).get("text", ""))
            return " ".join(text for text in finals if text).strip()
        versions = {"vosk": importlib.metadata.version("vosk")}
    # First utterance after model load is reported independently, not mixed into warm medians.
    first_pcm = read_pcm(args.output / "audio" / (items[0]["id"] + ".wav"))
    _, first_metrics = measure(lambda: recognize(first_pcm))
    rows = []
    for repeat in range(args.repeats):
        for item in items:
            path = args.output / "audio" / (item["id"] + ".wav")
            if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                raise ValueError("Audio hash differs from the evaluation manifest")
            pcm = read_pcm(path)
            text, metrics = measure(lambda: recognize(pcm))
            rows.append({**item, "repeat": repeat, "hypothesis": text,
                         **score(item["text"], text), **metrics,
                         "real_time_factor": metrics["wall_seconds"] / item["duration_seconds"]})
    result = {"provider": args.provider, "language": args.language, "threads": args.threads,
              "versions": versions, "python": sys.version, "platform": platform.platform(),
              "logical_cpus": os.cpu_count(), "load": load_metrics,
              "first_utterance": {"id": items[0]["id"], **first_metrics}, "rows": rows}
    args.result.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")


def summarize(result: dict[str, Any], category: str) -> dict[str, Any]:
    """Aggregate weighted errors and warm utterance metrics for one category."""
    rows = [row for row in result["rows"] if row["category"] == category]
    words = sum(row["reference_words"] for row in rows)
    chars = sum(row["reference_characters"] for row in rows)
    return {"provider": result["provider"], "language": result["language"],
            "threads": result["threads"], "category": category,
            "wer_percent": 100 * sum(row["word_edits"] for row in rows) / words if words else None,
            "cer_percent": 100 * sum(row["character_edits"] for row in rows) / chars if chars else None,
            "exact_percent": 100 * sum(row["exact"] for row in rows) / len(rows),
            "wall_median_seconds": statistics.median(row["wall_seconds"] for row in rows),
            "wall_max_seconds": max(row["wall_seconds"] for row in rows),
            "rtf_median": statistics.median(row["real_time_factor"] for row in rows),
            "rtf_max": max(row["real_time_factor"] for row in rows),
            "cpu_percent_one_core_mean": statistics.mean(row["cpu_percent_one_core"] for row in rows),
            "cpu_percent_machine_mean": statistics.mean(row["cpu_percent_machine"] for row in rows),
            "rss_peak_sampled_mib": max(row["rss_peak_sampled_mib"] for row in rows),
            "observations": len(rows), "unique_clips": len({row["id"] for row in rows})}


def main() -> None:
    """Expose preparation, isolated worker execution and report commands."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "worker", "run"))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", type=Path, default=DEFAULT_OUTPUT / "models" / "small")
    parser.add_argument("--result", type=Path)
    parser.add_argument("--provider", choices=("vosk", "faster-whisper"))
    parser.add_argument("--language", choices=("en", "es"))
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1 or args.threads < 1:
        parser.error("repeats and threads must be positive")
    args.output = args.output.resolve()
    # Restrict generated artifacts to the ignored evaluation directory.
    if not args.output.is_relative_to(DEFAULT_OUTPUT.resolve()):
        parser.error("output must remain inside local-data/stt-evaluation")
    if args.action == "prepare":
        prepare(args.output)
    elif args.action == "worker":
        if not args.result or not args.provider or not args.language:
            parser.error("worker requires result, provider and language")
        args.result = args.result.resolve()
        if not args.result.is_relative_to(args.output):
            parser.error("worker results must remain inside the ignored output directory")
        worker(args)
    else:
        reports = []
        for provider, threads in (("vosk", 1), ("faster-whisper", 2), ("faster-whisper", 4)):
            for language in ("en", "es"):
                target = args.output / f"{provider}-{threads}-{language}.json"
                python = ROOT / (".venv" if provider == "vosk" else "local-data/stt-evaluation/venv") / "Scripts/python.exe"
                model = (ROOT / "local-data/models" / (
                    "vosk-model-small-en-us-0.15" if language == "en" else "vosk-model-small-es-0.42")) if provider == "vosk" else args.model
                command = [str(python), str(Path(__file__).resolve()), "worker", "--output", str(args.output),
                           "--model", str(model), "--provider", provider, "--threads", str(threads),
                           "--language", language, "--result", str(target), "--repeats", str(args.repeats)]
                print(f"Evaluating {provider} / {language} / {threads} threads", flush=True)
                subprocess.run(command, check=True, timeout=1800,
                               env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
                result = json.loads(target.read_text(encoding="utf-8"))
                for category in ("clean", "noise-15db", "silence", "short-silence"):
                    reports.append(summarize(result, category))
        (args.output / "summary.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
        print("Evaluation complete; results are in ignored local-data/stt-evaluation", flush=True)


if __name__ == "__main__":
    main()
