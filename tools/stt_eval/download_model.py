"""Explicitly download only the approved Small multilingual evaluation model.

Run manually in the isolated evaluation environment after owner approval.
The benchmark itself is offline and never calls this module.
"""
from __future__ import annotations

import os
from pathlib import Path

BASE = Path(__file__).resolve().parents[2] / "local-data" / "stt-evaluation"
REVISION = "536b0662742c02347bc0e980a01041f333bce120"


def main() -> None:
    """Fetch pinned CTranslate2 model files into the ignored evaluation tree."""
    os.environ["HF_HOME"] = str(BASE / "hf-cache")
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    from huggingface_hub import snapshot_download

    snapshot_download(
        repo_id="Systran/faster-whisper-small", revision=REVISION,
        local_dir=BASE / "models" / "small",
        allow_patterns=["config.json", "model.bin", "tokenizer.json", "vocabulary.txt",
                        "preprocessor_config.json"],
    )
    (BASE / "model-revision.txt").write_text(REVISION, encoding="utf-8")


if __name__ == "__main__":
    main()
