"""Dependency-free evaluation contract tests; no GPU, model or network needed."""
from pathlib import Path
import json
import argparse
import hashlib
import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
import wave

from evaluate import edit_distance, normalize, read_pcm, score, summarize, worker, write_pcm


class EvaluationTests(unittest.TestCase):
    def test_normalization_english_and_spanish(self):
        self.assertEqual(normalize("¿CÓMO diseñarías una API REST?"), "como disenarias una api rest")
        self.assertEqual(normalize("TypeScript, interfaces!"), "typescript interfaces")

    def test_word_edits_insertion_deletion_substitution(self):
        self.assertEqual(edit_distance(["a", "b"], ["a", "c", "d"]), 2)
        self.assertEqual(edit_distance([], ["a"]), 1)
        self.assertEqual(edit_distance(["a"], []), 1)

    def test_empty_audio_reference_detects_hallucination(self):
        self.assertFalse(score("", "Thank you")["exact"])
        self.assertEqual(score("", "Thank you")["word_edits"], 2)
        self.assertTrue(score("", "")["exact"])

    def test_pcm_round_trip_and_format_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.wav"
            write_pcm(path, bytes(3200))
            self.assertEqual(read_pcm(path), bytes(3200))
            with wave.open(str(path), "wb") as target:
                target.setparams((2, 2, 16000, 0, "NONE", "not compressed"))
                target.writeframes(bytes(3200))
            with self.assertRaises(ValueError):
                read_pcm(path)

    def test_weighted_wer_not_mean_of_clip_percentages(self):
        common = {"category": "clean", "wall_seconds": 1, "real_time_factor": 0.5,
                  "cpu_percent_one_core": 100, "cpu_percent_machine": 10, "rss_peak_sampled_mib": 20}
        rows = [{**common, "id": "short", **score("a", "b")},
                {**common, "id": "long", **score("a b c", "a b c")}]
        result = summarize({"provider": "fake", "language": "en", "threads": 2, "rows": rows}, "clean")
        self.assertEqual(result["wer_percent"], 25)
        self.assertEqual(result["exact_percent"], 50)

    def test_corpus_covers_both_languages_and_technical_questions(self):
        corpus = json.loads(Path(__file__).with_name("corpus.json").read_text(encoding="utf-8"))
        self.assertEqual(len({item["id"] for item in corpus}), len(corpus))
        for language in ("en", "es"):
            items = [item for item in corpus if item["language"] == language]
            self.assertEqual(len(items), 6)
            self.assertTrue(any("TypeScript" in item["text"] for item in items))
            self.assertTrue(any("mutex" in item["text"] for item in items))

    def test_silence_aggregation_does_not_divide_by_zero(self):
        row = {"category": "silence", "id": "silence", **score("", ""),
               "wall_seconds": 0.1, "real_time_factor": 0.1,
               "cpu_percent_one_core": 100, "cpu_percent_machine": 10, "rss_peak_sampled_mib": 20}
        summary = summarize({"provider": "fake", "language": "es", "threads": 2, "rows": [row]}, "silence")
        self.assertIsNone(summary["wer_percent"])
        self.assertIsNone(summary["cer_percent"])
        self.assertEqual(summary["exact_percent"], 100)

    def test_mocked_whisper_worker_is_cpu_only_offline_and_consumes_segments(self):
        for language in ("en", "es"):
            with self.subTest(language=language), tempfile.TemporaryDirectory() as directory:
                output = Path(directory)
                (output / "audio").mkdir()
                audio = output / "audio" / "synthetic.wav"
                write_pcm(audio, bytes(3200))
                item = {"id": "synthetic", "text": "API", "language": language,
                        "sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
                        "duration_seconds": 0.1, "category": "clean"}
                (output / "manifest.json").write_text(json.dumps([item]), encoding="utf-8")
                active = [False]

                def measured(operation):
                    active[0] = True
                    try:
                        return operation(), {"wall_seconds": 1.0}
                    finally:
                        active[0] = False

                def segments():
                    self.assertTrue(active[0], "Lazy inference must happen inside timing")
                    yield SimpleNamespace(text=" API ")

                model = MagicMock()
                model.model.device = "cpu"
                model.transcribe.side_effect = lambda *a, **kw: (segments(), None)
                factory = MagicMock(return_value=model)
                fake_numpy = MagicMock()
                args = argparse.Namespace(output=output, provider="faster-whisper", language=language,
                                          threads=2, model=output / "model", repeats=1,
                                          result=output / "results.json")
                with patch.dict("sys.modules", {"faster_whisper": SimpleNamespace(WhisperModel=factory),
                                                 "numpy": fake_numpy}), patch.dict(os.environ), \
                        patch("evaluate.measure", side_effect=measured), \
                        patch("evaluate.importlib.metadata.version", return_value="mock"):
                    worker(args)
                    self.assertEqual(os.environ["CUDA_VISIBLE_DEVICES"], "-1")
                    self.assertEqual(os.environ["HF_HUB_OFFLINE"], "1")
                factory.assert_called_once_with(str(output / "model"), device="cpu", compute_type="int8",
                                                cpu_threads=2, num_workers=1, local_files_only=True)
                for call in model.transcribe.call_args_list:
                    self.assertEqual(call.kwargs["language"], language)
                    self.assertFalse(call.kwargs["vad_filter"])
                result = json.loads(args.result.read_text(encoding="utf-8"))
                self.assertTrue(result["rows"][0]["exact"])


if __name__ == "__main__":
    unittest.main()
