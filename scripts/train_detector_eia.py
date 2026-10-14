#!/usr/bin/env python
"""Trains the EIA detector and saves it as a ModelArtifact. Architecture.md Section 7:
"Training happens off-cluster... the image ships with the artifact baked in" -- this is the
off-cluster step; the Dockerfile copies the output into the public-tier inference image.

Usage: python scripts/train_detector_eia.py [--out artifacts/eia_detector.joblib]
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.config import get_settings  # noqa: E402
from common.logging import configure_logging  # noqa: E402
from model.train import train_eia_detector  # noqa: E402

log = logging.getLogger("train_detector_eia")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="artifacts/eia_detector.joblib")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)

    artifact = train_eia_detector(settings)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    artifact.save(out_path)
    log.info(
        "artifact saved",
        extra={"path": str(out_path), "train_rows": artifact.train_rows, "tier": artifact.tier},
    )


if __name__ == "__main__":
    main()
