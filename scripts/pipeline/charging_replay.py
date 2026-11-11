"""Offline FoundationPose replay for the charging-socket RGB-D library.

The default mask mode is deliberately explicit ``rectangle``. It is a detector
box mask for smoke testing and is not a segmentation result. ``sam2`` is an
optional backend and fails clearly until a compatible SAM2 checkpoint is
provided. Every frame is initialized independently because the source library
does not guarantee a continuous sequence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = ROOT.parent / "robot-ev-charging"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_image(path: Path, flags: int) -> np.ndarray | None:
    """Use byte decoding because OpenCV's Windows path reader rejects CJK paths."""
    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, flags)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def resolve_source_path(source_root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute() and path.is_file():
        return path
    candidate = (source_root / value).resolve()
    if candidate.is_file():
        return candidate
    library_candidate = (source_root / "dataset/vision" / value).resolve()
    if library_candidate.is_file():
        return library_candidate
    raise FileNotFoundError(value)


def align_depth_to_color(raw: np.ndarray, calibration: dict, color_camera: dict) -> np.ndarray:
    depth_camera = calibration["depth_camera"]
    depth_k = np.asarray(depth_camera["camera_matrix"], dtype=np.float32)
    color_k = np.asarray(color_camera["camera_matrix"], dtype=np.float32)
    rotation = np.asarray(calibration["depth_to_color"]["rotation"], dtype=np.float32)
    translation = np.asarray(calibration["depth_to_color"]["translation_m"], dtype=np.float32)
    scale = float(calibration["depth_scale_m"])
    height, width = int(color_camera["image_height"]), int(color_camera["image_width"])
    ys, xs = np.nonzero(raw > 0)
    if len(xs) == 0:
        return np.zeros((height, width), dtype=np.float32)
    z = raw[ys, xs].astype(np.float32) * scale
    points = np.stack(((xs - depth_k[0, 2]) * z / depth_k[0, 0],
                       (ys - depth_k[1, 2]) * z / depth_k[1, 1], z), axis=1)
    points = points @ rotation.T + translation
    valid = points[:, 2] > 0
    points = points[valid]
    pixels = points @ color_k.T
    pixels[:, 0] /= pixels[:, 2]
    pixels[:, 1] /= pixels[:, 2]
    u = np.rint(pixels[:, 0]).astype(np.int32)
    v = np.rint(pixels[:, 1]).astype(np.int32)
    valid = (u >= 0) & (u < width) & (v >= 0) & (v < height)
    u, v, z = u[valid], v[valid], points[:, 2][valid]
    aligned = np.zeros((height, width), dtype=np.float32)
    order = np.argsort(z)
    flat = v[order] * width + u[order]
    aligned.flat[flat] = z[order]
    return aligned


def detector_mask(rgb: np.ndarray, weights: Path, mode: str, confidence: float, sam2_predictor=None) -> tuple[np.ndarray, dict]:
    from ultralytics import YOLO

    result = YOLO(str(weights))(rgb, conf=confidence, verbose=False)
    candidates = []
    for prediction in result:
        for box in prediction.boxes:
            candidates.append({
                "xyxy": [float(value) for value in box.xyxy[0].tolist()],
                "confidence": float(box.conf[0]),
                "class": int(box.cls[0]),
            })
    if not candidates:
        raise RuntimeError("detector_found_no_object")
    selected = max(candidates, key=lambda item: item["confidence"])
    x0, y0, x1, y1 = np.rint(selected["xyxy"]).astype(int)
    x0, y0 = max(x0, 0), max(y0, 0)
    x1, y1 = min(x1, rgb.shape[1]), min(y1, rgb.shape[0])
    if x1 <= x0 or y1 <= y0:
        raise RuntimeError("detector_box_out_of_image")
    if mode == "sam2":
        if sam2_predictor is None:
            raise RuntimeError("sam2_predictor_not_initialized")
        sam2_predictor.set_image(rgb)
        masks, scores, _ = sam2_predictor.predict(
            box=np.asarray([x0, y0, x1, y1], dtype=np.float32),
            multimask_output=False,
        )
        if masks is None or len(masks) != 1:
            raise RuntimeError("sam2_returned_no_mask")
        mask = np.asarray(masks[0], dtype=np.uint8)
        return mask, {
            "backend": "sam2_box_prompt",
            "selected": selected,
            "candidate_count": len(candidates),
            "sam2_score": float(np.asarray(scores).reshape(-1)[0]),
        }
    mask = np.zeros(rgb.shape[:2], dtype=np.uint8)
    mask[y0:y1, x0:x1] = 1
    return mask, {"backend": "rectangle_detector_box", "selected": selected, "candidate_count": len(candidates)}


def run(args: argparse.Namespace) -> int:
    source_root = args.source_root.resolve()
    record_paths = [args.record.resolve()] if args.record else sorted((source_root / "dataset/vision/records").glob("*.json"))[:args.max_frames]
    if not record_paths:
        raise FileNotFoundError("no_vision_records")
    mesh_path = args.mesh.resolve()
    weights = args.weights.resolve()
    if not mesh_path.is_file() or not weights.is_file():
        raise FileNotFoundError("mesh_or_weights_missing")

    sys.path.insert(0, str(ROOT / "third_party/FoundationPose"))
    from estimater import FoundationPose
    from learning.training.predict_pose_refine import PoseRefinePredictor
    from learning.training.predict_score import ScorePredictor
    import nvdiffrast.torch as dr
    import trimesh

    mesh = trimesh.load(mesh_path)
    # The project CAD export has no STL unit metadata; the recorded geometry
    # contract treats this socket mesh as millimetres.
    mesh.apply_scale(0.001)
    scorer = ScorePredictor()
    refiner = PoseRefinePredictor()
    estimator = FoundationPose(
        model_pts=mesh.vertices,
        model_normals=mesh.vertex_normals,
        mesh=mesh,
        scorer=scorer,
        refiner=refiner,
        glctx=dr.RasterizeCudaContext(),
        debug=0,
        debug_dir=str(args.output.parent / "foundationpose_debug"),
    )
    sam2_predictor = None
    if args.mask_mode == "sam2":
        # FoundationPose's training imports add ``third_party`` to sys.path;
        # remove that repository root so the editable SAM2 package is not
        # mistaken for the parent directory of the SAM2 repository.
        third_party_root = (ROOT / "third_party").resolve()
        sys.path[:] = [entry for entry in sys.path if Path(entry or ".").resolve() != third_party_root]
        from sam2.build_sam import build_sam2
        from sam2.sam2_image_predictor import SAM2ImagePredictor

        # SAM2 initializes Hydra from the installed ``sam2`` package.
        sam2_config = "configs/sam2.1/sam2.1_hiera_s.yaml"
        if not args.sam2_checkpoint.is_file():
            raise FileNotFoundError("sam2_checkpoint_missing")
        sam2_model = build_sam2(sam2_config, str(args.sam2_checkpoint), device="cuda")
        sam2_predictor = SAM2ImagePredictor(sam2_model)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        for record_path in record_paths:
            started = time.perf_counter()
            record = load_json(record_path)
            item = {
                "schema_version": 1,
                "record": str(record_path),
                "status": "invalid",
                "pose": None,
                "reason": None,
                "mask": None,
                "quality": {"geometry_validated": False, "calibration_validated": False},
            }
            try:
                if record.get("status") != "ready":
                    raise RuntimeError("record_not_ready")
                image_path = resolve_source_path(source_root, record["image"])
                depth_path = resolve_source_path(source_root, record["depth"]["file"])
                if record.get("image_sha256") and sha256(image_path) != record["image_sha256"]:
                    raise RuntimeError("rgb_sha256_mismatch")
                if record["depth"].get("file_sha256") and sha256(depth_path) != record["depth"]["file_sha256"]:
                    raise RuntimeError("depth_sha256_mismatch")
                source = record["sources"][0]
                try:
                    camera_path = resolve_source_path(source_root, source["camera_file"])
                except FileNotFoundError:
                    camera_path = source_root / "dataset/vision/calibrations" / f"{source['camera_sha256']}.json"
                color_camera = load_json(camera_path)
                calibration_ref = record["depth"].get("calibration", {}).get(
                    "source_file", record["depth"].get("calibration_file")
                )
                try:
                    calibration_path = resolve_source_path(source_root, calibration_ref)
                except FileNotFoundError:
                    calibration_hash = record["depth"].get("calibration", {}).get("sha256")
                    calibration_path = source_root / "dataset/vision/calibrations" / f"{calibration_hash}.json"
                calibration = load_json(calibration_path)
                rgb_bgr = read_image(image_path, cv2.IMREAD_COLOR)
                rgb = cv2.cvtColor(rgb_bgr, cv2.COLOR_BGR2RGB) if rgb_bgr is not None else None
                raw_depth = read_image(depth_path, cv2.IMREAD_UNCHANGED)
                if rgb is None or raw_depth is None or raw_depth.dtype != np.uint16:
                    raise RuntimeError("rgb_or_uint16_depth_unreadable")
                depth = align_depth_to_color(raw_depth, calibration, color_camera)
                # FoundationPose's reference readers keep K as float64; matching
                # that dtype avoids a mixed float32/float64 matrix path.
                K = np.asarray(color_camera["camera_matrix"], dtype=float)
                mask, mask_info = detector_mask(rgb, weights, args.mask_mode, args.confidence, sam2_predictor)
                pose = estimator.register(K=K, rgb=rgb, depth=depth, ob_mask=mask.astype(bool), iteration=args.est_refine_iter)
                item.update({
                    "status": "valid_algorithm_result",
                    "pose": np.asarray(pose, dtype=float).tolist(),
                    "mask": mask_info,
                    "camera_serial": color_camera.get("serial"),
                    "calibration_validated": bool(calibration.get("validated")),
                    "geometry_validated": False,
                })
            except Exception as exc:
                item["reason"] = f"{type(exc).__name__}:{exc}"
            item["elapsed_s"] = time.perf_counter() - started
            stream.write(json.dumps(item, ensure_ascii=False, allow_nan=False) + "\n")
            stream.flush()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--record", type=Path)
    parser.add_argument("--max-frames", type=int, default=1)
    parser.add_argument("--mesh", type=Path, default=ROOT / "assets/mesh/socket_mod.STL")
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mask-mode", choices=["rectangle", "sam2"], default="rectangle")
    parser.add_argument(
        "--sam2-checkpoint",
        type=Path,
        default=ROOT / "third_party/sam2/checkpoints/sam2.1_hiera_small.pt",
    )
    parser.add_argument("--confidence", type=float, default=0.25)
    parser.add_argument("--est-refine-iter", type=int, default=5)
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
