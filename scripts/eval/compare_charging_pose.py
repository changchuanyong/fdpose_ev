"""Compare reviewed-keypoint PnP with FoundationPose on the same RGB frame.

This compares two estimates, not either estimate against a physical 6D truth.
The FoundationPose mesh pose is converted from the CAD frame into the target
frame using the recorded ``cad_to_target`` transform before comparison.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

import cv2
import numpy as np


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def pose_angle_deg(rotation: np.ndarray) -> float:
    return math.degrees(math.acos(float(np.clip((np.trace(rotation) - 1.0) / 2.0, -1.0, 1.0))))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--pnp-geometry", type=Path, required=True)
    parser.add_argument("--cad-geometry", type=Path, required=True)
    parser.add_argument("--foundationpose-jsonl", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    record = load(args.record)
    annotations = load(args.annotations)
    image_hash = record["image_sha256"]
    annotation = next(item for item in annotations["images"] if item["image_sha256"] == image_hash)
    pnp_geometry = load(args.pnp_geometry)["points_mm"]
    cad_geometry = load(args.cad_geometry)
    calibration_hash = record["sources"][0]["camera_sha256"]
    calibration = load(args.source_root / "dataset/vision/calibrations" / f"{calibration_hash}.json")
    K = np.asarray(calibration["camera_matrix"], dtype=np.float64)
    dist = np.asarray(calibration["dist_coeffs"], dtype=np.float64).reshape(-1, 1)
    names = [name for name in pnp_geometry if name in annotation["points"]]
    object_points_mm = np.asarray([pnp_geometry[name] for name in names], dtype=np.float64)
    image_points = np.asarray([annotation["points"][name]["xy"] for name in names], dtype=np.float64)

    sys.path.insert(0, str(args.source_root / "src"))
    from ev_charging.vision.algorithms import pnp2

    pnp_result = pnp2.solve_target_pose(
        {name: tuple(annotation["points"][name]["xy"]) for name in names},
        pnp_geometry,
        K,
        dist,
    )
    rvec, tvec = pnp_result["rvec"], pnp_result["tvec"]
    rotation, _ = cv2.Rodrigues(rvec)
    projected, _ = cv2.projectPoints(object_points_mm, rvec, tvec, K, dist)
    errors = np.linalg.norm(projected.reshape(-1, 2) - image_points, axis=1)
    pnp_pose = np.eye(4, dtype=float)
    pnp_pose[:3, :3] = rotation
    pnp_pose[:3, 3] = tvec.reshape(3) / 1000.0

    foundationpose = load(args.foundationpose_jsonl)
    fp_cad_pose = np.asarray(foundationpose["pose"], dtype=float)
    cad_to_target = np.asarray(cad_geometry["cad_to_target"], dtype=float)
    cad_to_target[:3, 3] /= 1000.0
    fp_target_pose = fp_cad_pose @ np.linalg.inv(cad_to_target)
    relative = np.linalg.inv(pnp_pose) @ fp_target_pose
    report = {
        "schema_version": 1,
        "record": str(args.record),
        "image_sha256": image_hash,
        "comparability": {
            "same_frame": True,
            "pnp_geometry": str(args.pnp_geometry),
            "foundationpose_mesh_frame_to_target": str(args.cad_geometry),
            "physical_6d_ground_truth_available": False,
            "calibration_validated": bool(calibration.get("validated", False)),
            "geometry_validated": bool(cad_geometry.get("validated", False)),
        },
        "pnp": {
            "method": f"ev_charging.pnp2:{pnp_result['method']}",
            "point_count": len(names),
            "names": names,
            "T_camera_target": pnp_pose.tolist(),
            "reprojection_rms_px": float(pnp_result["reproj_rms_error"]),
            "reprojection_max_px": float(pnp_result["max_reproj_error"]),
        },
        "foundationpose": {
            "mask_backend": foundationpose.get("mask", {}).get("backend"),
            "sam2_score": foundationpose.get("mask", {}).get("sam2_score"),
            "T_camera_cad_mesh": fp_cad_pose.tolist(),
            "T_camera_target": fp_target_pose.tolist(),
        },
        "between_estimates": {
            "translation_difference_m": float(np.linalg.norm(relative[:3, 3])),
            "translation_difference_mm": float(np.linalg.norm(relative[:3, 3]) * 1000.0),
            "rotation_difference_deg": pose_angle_deg(relative[:3, :3]),
        },
        "interpretation": "Agreement between two estimates; not absolute pose error without 6D ground truth.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
