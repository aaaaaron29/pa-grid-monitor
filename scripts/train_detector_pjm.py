#!/usr/bin/env python
"""Trains the PJM detector, one zone at a time, and saves each as a ModelArtifact.
Architecture.md Section 7: a PJM-trained artifact is PJM-derived material (Section 2's
publication policy), so it never ships baked into a public image -- it lives on a PVC on
the VM, mounted at runtime, for the private-tier inference service to load.

Usage: python scripts/train_detector_pjm.py [--zone PECO] [--out-dir artifacts/]
Trains all 5 zones if --zone is omitted.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.config import get_settings  # noqa: E402
from common.logging import configure_logging  # noqa: E402
from model.data_pjm import ZONES  # noqa: E402
from model.train import train_pjm_detector  # noqa: E402

log = logging.getLogger("train_detector_pjm")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zone", choices=ZONES, default=None)
    parser.add_argument("--out-dir", default="artifacts")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    zones = [args.zone] if args.zone else list(ZONES)
    for zone in zones:
        artifact = train_pjm_detector(settings, zone)
        out_path = out_dir / f"pjm_detector_{zone}.joblib"
        artifact.save(out_path)
        log.info(
            "artifact saved",
            extra={"path": str(out_path), "zone": zone, "train_rows": artifact.train_rows},
        )


if __name__ == "__main__":
    main()
