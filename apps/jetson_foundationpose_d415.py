"""Measure live D415 → FoundationPose socket tracking on Jetson."""

import argparse
from collections import deque
from itertools import product
import json
import logging
import os
from pathlib import Path
import sys
import time

import cv2
import numpy as np
import pyrealsense2 as rs
import torch
import trimesh

from pose_checks import (MAX_REVIEW_ROTATION_DEG, MAX_REVIEW_TRANSLATION_M,
                         depth_alignment, pose_delta)


ROOT = Path(__file__).resolve().parents[1]
CHECK_PERIOD_S = 0.6
MIN_BOX_IOU = 0.35
RECOVERY_WINDOW_S = 3.0
REGISTRATION_RETRY_S = 5.0


def detect_socket(detector, bgr):
    boxes = detector.predict(bgr, classes=[0], conf=0.50, device=0, verbose=False)[0].boxes
    if not len(boxes):
        return None
    best = max(boxes, key=lambda box: float(box.conf.item()))
    return best.xyxy[0].cpu().numpy(), float(best.conf.item())


def box_in_view(box, shape, margin=8):
    x0, y0, x1, y1 = box
    height, width = shape[:2]
    return margin <= x0 < x1 <= width - margin and margin <= y0 < y1 <= height - margin


def projected_box(K, corners, pose):
    points = corners @ pose[:3, :3].T + pose[:3, 3]
    if not np.isfinite(points).all() or np.any(points[:, 2] <= 0):
        return None
    pixels = points @ K.T
    xy = pixels[:, :2] / pixels[:, 2:]
    return np.concatenate((xy.min(axis=0), xy.max(axis=0)))


def box_iou(a, b):
    if a is None or b is None:
        return 0.0
    overlap = np.maximum(np.minimum(a[2:], b[2:]) - np.maximum(a[:2], b[:2]), 0)
    intersection = float(np.prod(overlap))
    union = float(np.prod(a[2:] - a[:2]) + np.prod(b[2:] - b[:2])) - intersection
    return intersection / union if union > 0 else 0.0


class PreviewWindow:
    """Show FoundationPose overlays on the Jetson desktop."""

    def __init__(self):
        import tkinter as tk
        from PIL import Image, ImageTk

        self.root = tk.Tk()
        self.root.title("FoundationPose D415")
        self.label = tk.Label(self.root)
        self.label.pack()
        self.closed = False
        self.root.protocol("WM_DELETE_WINDOW", self.request_close)
        for key in ("<Escape>", "<q>", "<Q>"):
            self.root.bind(key, self.request_close)
        self.image = Image
        self.photo_image = ImageTk.PhotoImage

    def request_close(self, _event=None):
        self.closed = True

    def present(self, bgr, status):
        self.root.title(f"FoundationPose D415 | {status}")
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        self.photo = self.photo_image(self.image.fromarray(rgb))
        self.label.configure(image=self.photo)
        self.root.update()
        return not self.closed

    def close(self):
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--foundationpose", type=Path, default=ROOT / "third_party/FoundationPose")
    parser.add_argument("--mesh", type=Path, required=True)
    parser.add_argument("--geometry", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--sam2-checkpoint", type=Path, default=ROOT / "weights/sam2.1_hiera_small.pt")
    parser.add_argument("--serial", required=True, help="RealSense SDK serial")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frames", type=int, default=60, help="Tracking frames after initialization, 0 for continuous")
    parser.add_argument("--stream-width", type=int, default=640)
    parser.add_argument("--stream-height", type=int, default=480)
    parser.add_argument("--init-width", type=int, default=640,
                        help="Downscale SAM2 and registration to this width")
    parser.add_argument("--est-refine-iter", type=int, default=3,
                        help="Register refinement iterations; official default 5, 3 measured within 0.12 mm / 0.28 deg on the socket")
    parser.add_argument("--show", action="store_true", help="Show live RGB and pose overlays on the Jetson desktop")
    args = parser.parse_args()
    if args.frames < 0:
        parser.error("--frames must be nonnegative")
    if args.stream_width <= 0 or args.stream_height <= 0 or args.init_width <= 0:
        parser.error("--stream-width, --stream-height and --init-width must be positive")
    if args.est_refine_iter < 1:
        parser.error("--est-refine-iter must be positive")
    if not (args.foundationpose / "estimater.py").is_file():
        parser.error(f"Project FoundationPose source not found: {args.foundationpose}")
    if args.show and not os.environ.get("DISPLAY"):
        parser.error("--show needs a desktop display. Run from a terminal on the Jetson desktop.")
    if not args.sam2_checkpoint.is_file():
        parser.error(f"SAM2 checkpoint not found: {args.sam2_checkpoint}")
    args.output.mkdir(parents=True, exist_ok=False)
    os.environ.setdefault("YOLO_CONFIG_DIR", str(args.output.parent / "ultralytics"))
    os.environ.setdefault("FDONPOSE_TMP", str(args.output / "tmp"))
    sys.path.insert(0, str(args.foundationpose.resolve()))
    sys.path.insert(0, str(ROOT / "third_party/sam2"))
    from estimater import FoundationPose, draw_posed_3d_box, draw_xyz_axis, nvdiffrast_render, set_seed
    from sam2.build_sam import build_sam2
    from sam2.sam2_image_predictor import SAM2ImagePredictor
    from ultralytics import YOLO

    logging.getLogger().setLevel(logging.WARNING)
    set_seed(0)
    if not torch.cuda.is_available():
        raise RuntimeError("FoundationPose requires CUDA")
    mesh = trimesh.load(args.mesh, force="mesh")
    mesh.apply_scale(0.001)
    corners = np.asarray(list(product(*mesh.bounds.T)))
    target_from_cad = np.asarray(json.loads(args.geometry.read_text(encoding="utf-8-sig"))["cad_to_target"], dtype=float)
    target_from_cad[:3, 3] /= 1000
    cad_from_target = np.linalg.inv(target_from_cad)
    estimator = FoundationPose(model_pts=mesh.vertices, model_normals=mesh.vertex_normals,
                               mesh=mesh, debug=0, debug_dir=str(args.output))
    detector = YOLO(str(args.weights))
    segmenter = SAM2ImagePredictor(build_sam2(
        "configs/sam2.1/sam2.1_hiera_s.yaml", str(args.sam2_checkpoint),
        device="cuda", apply_postprocessing=False,
    ))
    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_device(args.serial)
    config.enable_stream(rs.stream.color, args.stream_width, args.stream_height, rs.format.rgb8, 30)
    config.enable_stream(rs.stream.depth, args.stream_width, args.stream_height, rs.format.z16, 30)
    profile = pipeline.start(config)
    preview = None
    try:
        if args.show:
            preview = PreviewWindow()
        device = profile.get_device()
        serial = device.get_info(rs.camera_info.serial_number)
        name = device.get_info(rs.camera_info.name)
        if serial != args.serial or name.split()[-1] != "D415":
            raise RuntimeError(f"Unexpected camera {name} {serial}")
        color_profile = profile.get_stream(rs.stream.color).as_video_stream_profile()
        depth_profile = profile.get_stream(rs.stream.depth).as_video_stream_profile()
        intr = color_profile.get_intrinsics()
        K = np.array([[intr.fx, 0, intr.ppx], [0, intr.fy, intr.ppy], [0, 0, 1]], dtype=float)
        scale = device.first_depth_sensor().get_depth_scale()
        coefficients = np.array(intr.coeffs, dtype=float)
        rectify = None
        if intr.model != rs.distortion.none and np.any(coefficients != 0):
            if intr.model != rs.distortion.brown_conrady:
                raise RuntimeError(f"Unsupported color distortion model {intr.model}")
            rectify = cv2.initUndistortRectifyMap(K, coefficients, None, K, (intr.width, intr.height), cv2.CV_32FC1)
        align = rs.align(rs.stream.color)
        print(json.dumps({"camera": name, "serial": serial, "color_fps": color_profile.fps(),
                          "rgb_resolution": [intr.width, intr.height],
                          "depth_resolution": [depth_profile.width(), depth_profile.height()],
                          "K": K.tolist(), "distortion": str(intr.model), "dist_coeffs": coefficients.tolist(),
                          "depth_scale_m": scale}), flush=True)

        def read_frame():
            frames = align.process(pipeline.wait_for_frames(4000))
            color, depth_frame = frames.get_color_frame(), frames.get_depth_frame()
            if not color or not depth_frame:
                raise RuntimeError("No aligned RGB-D pair")
            rgb = np.asanyarray(color.get_data()).copy()
            depth = np.asanyarray(depth_frame.get_data()).astype(np.float32) * scale
            if rectify is not None:
                rgb = cv2.remap(rgb, *rectify, cv2.INTER_LINEAR)
                depth = cv2.remap(depth, *rectify, cv2.INTER_NEAREST)
            return rgb, depth, color.get_frame_number(), color.get_timestamp()

        def draw_pose(bgr_frame, cad_pose, target_pose):
            boxed = draw_posed_3d_box(K, bgr_frame, cad_pose, mesh.bounds)
            scale = 0.04
            axes = np.vstack((np.zeros((1, 3)), np.eye(3) * scale))
            bounds = projected_box(K, axes, target_pose)
            if bounds is None:
                return boxed
            height, width = boxed.shape[:2]
            x0, y0 = np.maximum(np.floor(bounds[:2]).astype(int) - 4, 0)
            x1, y1 = np.minimum(np.ceil(bounds[2:]).astype(int) + 5, (width, height))
            if x1 > x0 and y1 > y0:
                local_K = K.copy()
                local_K[:2, 2] -= [x0, y0]
                crop = boxed[y0:y1, x0:x1]
                crop[:] = draw_xyz_axis(crop, target_pose, scale=scale, K=local_K)
            return boxed

        def validate_pose(pose, detection_box, measured_depth, evaluation_K=None):
            evaluation_K = K if evaluation_K is None else evaluation_K
            iou = box_iou(projected_box(evaluation_K, corners, pose), detection_box)
            result = {"accepted": False, "alignment_iou": iou}
            if detection_box is None or iou < MIN_BOX_IOU:
                return result
            with torch.inference_mode():
                _, rendered_depth, _ = nvdiffrast_render(
                    K=evaluation_K, H=measured_depth.shape[0], W=measured_depth.shape[1],
                    ob_in_cams=estimator.pose_last.reshape(1, 4, 4), glctx=estimator.glctx,
                    mesh_tensors=estimator.mesh_tensors, output_size=measured_depth.shape,
                )
            rendered = rendered_depth[0].detach().cpu().numpy()
            result.update(depth_alignment(rendered, measured_depth))
            return result

        def save_drift(before, after, rejected_pose, recovery_pose, rejected_validation,
                       recovery_validation, change):
            directory = args.output / "drift" / f"{after[2]:06d}"
            directory.mkdir(parents=True, exist_ok=False)
            for name, frame in (("before", before), ("after", after)):
                rgb, depth, number, timestamp, pose = frame
                cv2.imwrite(str(directory / f"{name}_rgb.png"), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
                np.save(directory / f"{name}_depth.npy", depth, allow_pickle=False)
                cv2.imwrite(str(directory / f"{name}_depth_mm.png"),
                            np.rint(depth * 1000).astype(np.uint16))
                np.savetxt(directory / f"{name}_pose.txt", pose)
            np.savetxt(directory / "cam_K.txt", K)
            np.savetxt(directory / "rejected_pose.txt", rejected_pose)
            np.savetxt(directory / "recovery_pose.txt", recovery_pose)
            metadata = {"before_frame": before[2], "after_frame": after[2],
                        "before_device_time_ms": before[3], "after_device_time_ms": after[3],
                        "change_from_confirmed": {"translation_m": change[0], "rotation_deg": change[1]},
                        "rejected_validation": rejected_validation,
                        "recovery_validation": recovery_validation}
            (directory / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n",
                                                       encoding="utf-8")
            print(json.dumps({"event": "drift_rgbd_saved", "path": str(directory)}), flush=True)

        def write_pose(stream, pose, frame, device_ms, stage, elapsed_ms, validation=None, change=None):
            target_pose = np.asarray(pose, dtype=float) @ cad_from_target
            rotation = target_pose[:3, :3]
            if (not np.isfinite(target_pose).all() or target_pose[2, 3] <= 0
                    or not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-3)
                    or abs(np.linalg.det(rotation) - 1) > 1e-3):
                raise RuntimeError("FoundationPose returned an invalid rigid transform")
            record = {"frame": frame, "device_time_ms": device_ms, "stage": stage,
                      "elapsed_ms": elapsed_ms, "validation": validation,
                      "change_from_confirmed": change, "T_camera_target_m": target_pose.tolist()}
            stream.write(json.dumps(record, allow_nan=False) + "\n")
            stream.flush()
            return target_pose

        registration_not_before = 0.0

        def seek_pose():
            nonlocal registration_not_before
            deadline = float("inf") if preview else time.monotonic() + 25
            status = "Aim at the socket"
            while time.monotonic() < deadline:
                started = time.perf_counter()
                rgb, depth, number, timestamp = read_frame()
                bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                detection = detect_socket(detector, bgr)
                if detection is None or not box_in_view(detection[0], bgr.shape):
                    status = "Aim at the socket" if detection is None else "Socket clipped | Move it fully into view"
                    if preview and not preview.present(bgr, f"{status} | Q or Esc to quit"):
                        return None
                    continue
                box, confidence = detection
                now = time.monotonic()
                if last_confirmed_pose_last is not None and now < registration_not_before:
                    estimator.pose_last = last_confirmed_pose_last.clone()
                    recovered = estimator.track_one(rgb=rgb, depth=depth, K=K, iteration=4)
                    torch.cuda.synchronize()
                    validation = validate_pose(recovered, box, depth)
                    elapsed = (time.perf_counter() - started) * 1000
                    if validation["accepted"]:
                        print(json.dumps({"event": "tracking_recovered", "frame": number,
                                          "validation": validation,
                                          "backend": "last_confirmed_pose"}), flush=True)
                        return (recovered, rgb, depth, bgr, bgr, number, timestamp,
                                elapsed, validation, "recover")
                    status = "Recovering from last confirmed pose | No SAM2"
                    if preview and not preview.present(bgr, status):
                        return None
                    continue
                if now < registration_not_before:
                    status = "Waiting before registration retry | No SAM2"
                    if preview and not preview.present(bgr, status):
                        return None
                    continue
                registration_not_before = time.monotonic() + REGISTRATION_RETRY_S
                init_scale = min(1.0, args.init_width / rgb.shape[1])
                init_height = round(rgb.shape[0] * init_scale)
                init_width = round(rgb.shape[1] * init_scale)
                init_rgb = cv2.resize(rgb, (init_width, init_height), interpolation=cv2.INTER_LINEAR)
                init_depth = cv2.resize(depth, (init_width, init_height), interpolation=cv2.INTER_NEAREST)
                init_K = K.copy()
                init_K[0] *= init_scale
                init_K[1] *= init_scale
                init_box = box * init_scale
                with torch.inference_mode():
                    segmenter.set_image(init_rgb)
                    masks, scores, _ = segmenter.predict(box=init_box, multimask_output=False)
                    segmenter.reset_predictor()
                init_mask = masks[0].astype(bool)
                ys, xs = np.nonzero(init_mask)
                if (len(xs) < 128 or np.count_nonzero(init_depth[init_mask] > 0)
                        < max(128, len(xs) // 10)):
                    status = "Insufficient aligned depth in SAM2 mask"
                    if preview and not preview.present(bgr, status):
                        return None
                    continue
                mask_box = np.array([xs.min(), ys.min(), xs.max() + 1, ys.max() + 1])
                if not box_in_view(mask_box, init_rgb.shape, margin=1):
                    status = "SAM2 mask clipped | Move socket fully into view"
                    if preview and not preview.present(bgr, status):
                        return None
                    continue
                overlay = bgr.copy()
                overlay_mask = cv2.resize(init_mask.astype(np.uint8), (rgb.shape[1], rgb.shape[0]),
                                          interpolation=cv2.INTER_NEAREST).astype(bool)
                overlay[overlay_mask] = (overlay[overlay_mask] * 0.55
                                         + np.array([0, 255, 0]) * 0.45).astype(np.uint8)
                x0, y0, x1, y1 = np.rint(box).astype(int)
                cv2.rectangle(overlay, (x0, y0), (x1, y1), (0, 200, 255), 2)
                cv2.imwrite(str(args.output / "candidate_mask.jpg"), overlay)
                if preview and not preview.present(overlay, "SAM2 mask | Initializing FoundationPose"):
                    return None
                started = time.perf_counter()
                initial = estimator.register(K=init_K, rgb=init_rgb, depth=init_depth,
                                             ob_mask=init_mask, iteration=args.est_refine_iter)
                torch.cuda.synchronize()
                elapsed = (time.perf_counter() - started) * 1000
                validation = validate_pose(initial, mask_box, init_depth, evaluation_K=init_K)
                if estimator.pose_last is None or not validation["accepted"]:
                    estimator.pose_last = None
                    status = "FoundationPose pose failed projection/depth validation"
                    print(json.dumps({"event": "registration_rejected", "validation": validation}), flush=True)
                    continue
                print(json.dumps({"event": "registration_accepted", "frame": number,
                                  "detector_confidence": confidence, "sam2_score": float(scores[0]),
                                  "validation": validation, "register_ms": elapsed}), flush=True)
                return (initial, rgb, depth, bgr, overlay, number, timestamp,
                        elapsed, validation, "register")
            cv2.imwrite(str(args.output / "camera.jpg"), bgr)
            print(f"No aligned charging socket pose before timeout: {status}", flush=True)
            return None

        for _ in range(12):
            read_frame()
        times, translations = deque(maxlen=600), deque(maxlen=600)
        tracked_poses = registrations = checks = recoveries = resets = 0
        duration = 0.0
        init_ms = image = last_overlay = None
        last_confirmed_pose = last_confirmed_pose_last = last_confirmed_frame = None
        with (args.output / "poses.jsonl").open("x", encoding="utf-8") as stream:
            try:
                while not args.frames or tracked_poses < args.frames:
                    registration = seek_pose()
                    if registration is None:
                        break
                    (pose, rgb, depth, bgr, mask_overlay, number, timestamp,
                     elapsed, validation, stage) = registration
                    target_pose = write_pose(stream, pose, number, timestamp, stage, elapsed,
                                             validation=validation)
                    if stage == "register":
                        registrations += 1
                    else:
                        recoveries += 1
                    last_confirmed_pose = pose.copy()
                    last_confirmed_pose_last = estimator.pose_last.clone()
                    last_confirmed_frame = rgb, depth, number, timestamp, pose.copy()
                    last_overlay = bgr, pose, target_pose
                    image = draw_pose(bgr.copy(), pose, target_pose)
                    if registrations == 1 and stage == "register":
                        init_ms = elapsed
                        cv2.imwrite(str(args.output / "initial_mask.jpg"), mask_overlay)
                        cv2.imwrite(str(args.output / "first_pose.jpg"), image)
                    if preview and not preview.present(image, "Tracking | Q or Esc to quit"):
                        break
                    next_check_at = 0.0
                    while not args.frames or tracked_poses < args.frames:
                        started = time.perf_counter()
                        rgb, depth, new_number, timestamp = read_frame()
                        if new_number <= number:
                            raise RuntimeError("Camera frame number did not advance")
                        number = new_number
                        stage, validation = "track", None
                        pose = estimator.track_one(rgb=rgb, depth=depth, K=K, iteration=2)
                        torch.cuda.synchronize()
                        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                        projection = projected_box(K, corners, pose)
                        translation_change, rotation_change = pose_delta(last_confirmed_pose, pose)
                        change = {"translation_m": translation_change, "rotation_deg": rotation_change}
                        sudden_change = (translation_change > MAX_REVIEW_TRANSLATION_M
                                         or rotation_change > MAX_REVIEW_ROTATION_DEG)
                        if projection is None or sudden_change or started >= next_check_at:
                            detection = detect_socket(detector, bgr)
                            detection_box = detection[0] if detection and box_in_view(detection[0], bgr.shape) else None
                            validation = validate_pose(pose, detection_box, depth)
                            checks += 1
                            next_check_at = started + CHECK_PERIOD_S
                            if not validation["accepted"]:
                                rejected_pose = pose.copy()
                                rejected_validation = validation
                                estimator.pose_last = last_confirmed_pose_last.clone()
                                recovered = estimator.track_one(rgb=rgb, depth=depth, K=K, iteration=4)
                                torch.cuda.synchronize()
                                recovery_validation = validate_pose(recovered, detection_box, depth)
                                save_drift(last_confirmed_frame,
                                           (rgb, depth, number, timestamp, rejected_pose),
                                           rejected_pose, recovered, rejected_validation,
                                           recovery_validation, (translation_change, rotation_change))
                                if recovery_validation["accepted"]:
                                    pose, validation, stage = recovered, recovery_validation, "recover"
                                    translation_change, rotation_change = pose_delta(last_confirmed_pose, pose)
                                    change = {"translation_m": translation_change,
                                              "rotation_deg": rotation_change}
                                    recoveries += 1
                                    print(json.dumps({"event": "tracking_recovered", "frame": number,
                                                      "validation": validation,
                                                      "backend": "last_confirmed_pose"}), flush=True)
                                else:
                                    resets += 1
                                    estimator.pose_last = None
                                    registration_not_before = time.monotonic() + RECOVERY_WINDOW_S
                                    if preview:
                                        preview.present(bgr, "Pose rejected | Recovering target")
                                    duration += time.perf_counter() - started
                                    print(json.dumps({"event": "tracking_lost", "frame": number,
                                                      "rejected_validation": rejected_validation,
                                                      "recovery_validation": recovery_validation,
                                                      "fallback": "cached_pose_then_throttled_register"}), flush=True)
                                    break
                        ms = (time.perf_counter() - started) * 1000
                        target_pose = write_pose(stream, pose, number, timestamp, stage, ms,
                                                 validation=validation, change=change)
                        times.append(ms)
                        translations.append(target_pose[:3, 3])
                        tracked_poses += 1
                        if validation is not None and validation["accepted"]:
                            last_confirmed_pose = pose.copy()
                            last_confirmed_pose_last = estimator.pose_last.clone()
                            last_confirmed_frame = rgb, depth, number, timestamp, pose.copy()
                        last_overlay = bgr, pose, target_pose
                        if preview:
                            image = draw_pose(bgr, pose, target_pose)
                            preview.present(image, "Tracking | Q or Esc to quit")
                        duration += time.perf_counter() - started
                        if preview and preview.closed:
                            break
                    if preview and preview.closed:
                        break
            except KeyboardInterrupt:
                pass
        if not preview and last_overlay is not None:
            image = draw_pose(*last_overlay)
        if image is not None:
            cv2.imwrite(str(args.output / "last_pose.jpg"), image)
        summary = {"camera_serial": serial, "resolution": [intr.width, intr.height],
                   "requested_stream_fps": 30, "initialization_mask": "SAM2.1_hiera_small",
                   "est_refine_iter": args.est_refine_iter,
                   "register_ms": init_ms, "registrations": registrations, "tracked_poses": tracked_poses,
                   "tracking_checks": checks, "tracking_recoveries": recoveries, "tracking_resets": resets,
                   "tracking_fps": tracked_poses / duration if tracked_poses else None,
                   "statistics_sample_frames": len(times),
                   "tracking_latency_p50_ms": float(np.median(times)) if times else None,
                   "tracking_latency_p95_ms": float(np.percentile(times, 95)) if times else None,
                   "position_std_xyz_mm": (np.std(translations, axis=0) * 1000).tolist() if translations else None,
                   "last_position_xyz_m": translations[-1].tolist() if translations else None,
                   "calibration_independently_validated": False, "pose_accuracy_validated": False}
        (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False), flush=True)
    finally:
        try:
            pipeline.stop()
        finally:
            if preview:
                preview.close()


if __name__ == "__main__":
    main()
