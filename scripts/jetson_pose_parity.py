"""Compare two FoundationPose ``ob_in_cam`` pose directories frame by frame.

Each pose file is a 4x4 ``ob_in_cam`` matrix written by ``run_demo.py``. The
report is a reproducibility check between two runs of the same input, not an
accuracy measurement against a physical ground truth.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys

import numpy as np


def load_pose(path: Path) -> np.ndarray:
    pose = np.loadtxt(path)
    if pose.shape != (4, 4):
        raise ValueError(f"{path.name}: expected 4x4, got {pose.shape}")
    return pose


def rotation_difference_deg(a: np.ndarray, b: np.ndarray) -> float:
    relative = a.T @ b
    cosine = (float(np.trace(relative)) - 1.0) / 2.0
    return math.degrees(math.acos(min(1.0, max(-1.0, cosine))))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True, help="reference ob_in_cam directory")
    parser.add_argument("--candidate", type=Path, required=True, help="candidate ob_in_cam directory")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worst", type=int, default=5)
    args = parser.parse_args()

    reference = {path.name: path for path in args.reference.glob("*.txt")}
    candidate = {path.name: path for path in args.candidate.glob("*.txt")}
    missing = sorted(set(reference) - set(candidate))
    extra = sorted(set(candidate) - set(reference))
    names = sorted(set(reference) & set(candidate))
    if not names:
        raise SystemExit("no pose files with matching names")

    frames = []
    for name in names:
        ref_pose = load_pose(reference[name])
        cand_pose = load_pose(candidate[name])
        frames.append(
            {
                "frame": name,
                "translation_m": float(np.linalg.norm(ref_pose[:3, 3] - cand_pose[:3, 3])),
                "rotation_deg": rotation_difference_deg(ref_pose[:3, :3], cand_pose[:3, :3]),
            }
        )

    translations = np.asarray([item["translation_m"] for item in frames], dtype=float)
    rotations = np.asarray([item["rotation_deg"] for item in frames], dtype=float)
    worst = sorted(frames, key=lambda item: item["translation_m"], reverse=True)[: args.worst]
    first = frames[0]
    report = {
        "schema_version": 1,
        "compared_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.executable,
        "reference": str(args.reference),
        "candidate": str(args.candidate),
        "counts": {
            "reference": len(reference),
            "candidate": len(candidate),
            "matched": len(frames),
            "missing_in_candidate": len(missing),
            "extra_in_candidate": len(extra),
        },
        "translation_m": {
            "max": float(translations.max()),
            "mean": float(translations.mean()),
            "p95": float(np.percentile(translations, 95)),
        },
        "rotation_deg": {
            "max": float(rotations.max()),
            "mean": float(rotations.mean()),
            "p95": float(np.percentile(rotations, 95)),
        },
        "first_frame": first,
        "worst_frames": worst,
        "missing_files": missing[:20],
        "extra_files": extra[:20],
        "acceptance": {
            "all_frames_matched": not missing and not extra,
            "first_frame_translation_below_1mm": first["translation_m"] < 1e-3,
            "first_frame_rotation_below_0p1deg": first["rotation_deg"] < 0.1,
        },
        "interpretation": (
            "Deviation between two runs of the same code, weights and demo data on different GPUs; "
            "tracks library-level nondeterminism, not accuracy against a physical ground truth."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps(report["acceptance"], ensure_ascii=True))
    print(f"max translation {report['translation_m']['max']:.6f} m")
    print(f"max rotation    {report['rotation_deg']['max']:.6f} deg")
    return 0 if all(report["acceptance"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
