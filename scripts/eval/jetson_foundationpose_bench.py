"""Capture real D415 inputs and compare the live runner with the official demo."""

import argparse
from functools import wraps
import json
import logging
import os
from pathlib import Path
import runpy
from statistics import median
import sys
import time

import cv2
import numpy as np
import torch
import trimesh


PROJECT = Path(__file__).resolve().parents[2]
FOUNDATIONPOSE = PROJECT / "third_party/FoundationPose"
MESH = PROJECT / "assets/mesh/socket_mod.PLY"
TRACK_FRAMES = 8


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def instrument(estimator, timings, frames=None):
    for method in ("register", "track_one"):
        original = getattr(estimator, method)

        def wrapper(original, method):
            @wraps(original)
            def timed(self, **kwargs):
                if frames is not None:
                    frames.append({key: value.copy() for key, value in kwargs.items()
                                   if key in {"rgb", "depth", "K", "ob_mask"}})
                torch.cuda.synchronize()
                started = time.perf_counter()
                pose = original(self, **kwargs)
                torch.cuda.synchronize()
                timings.append({"stage": method, "ms": (time.perf_counter() - started) * 1000,
                                "pose_cad_m": np.asarray(pose).tolist()})
                return pose

            return timed

        setattr(estimator, method, wrapper(original, method))


def capture(directory, serial, estimator):
    sys.path.insert(0, str(PROJECT / "third_party/sam2"))
    from sam2.sam2_image_predictor import SAM2ImagePredictor

    masks_ms = []
    for method in ("set_image", "predict"):
        original = getattr(SAM2ImagePredictor, method)

        def wrapper(original, method):
            @wraps(original)
            def timed(self, *args, **kwargs):
                torch.cuda.synchronize()
                started = time.perf_counter()
                result = original(self, *args, **kwargs)
                torch.cuda.synchronize()
                masks_ms.append({"stage": method, "ms": (time.perf_counter() - started) * 1000})
                return result

            return timed

        setattr(SAM2ImagePredictor, method, wrapper(original, method))

    timings, frames = [], []
    instrument(estimator, timings, frames)
    script = PROJECT / "apps/jetson_foundationpose_d415.py"
    live = directory / "live"
    sys.argv = [str(script), "--serial", serial, "--mesh", str(MESH),
                "--geometry", str(PROJECT / "config/geometry/socket_openings_ply.json"),
                "--weights", str(PROJECT / "weights/best.pt"), "--output", str(live),
                "--frames", str(TRACK_FRAMES)]
    runpy.run_path(str(script), run_name="__main__")
    summary = json.loads((live / "summary.json").read_text())
    stages = [row["stage"] for row in timings]
    if stages != ["register"] + ["track_one"] * TRACK_FRAMES or summary["tracked_poses"] != TRACK_FRAMES:
        raise RuntimeError(f"Capture needs one accepted registration and {TRACK_FRAMES} consecutive tracks. See {live}")

    scene = directory / "scene"
    for subdir in ("rgb", "depth", "masks", "exact_depth"):
        (scene / subdir).mkdir(parents=True)
    np.savetxt(scene / "cam_K.txt", frames[0]["K"])
    for index, frame in enumerate(frames):
        name = f"{index:06d}"
        color = cv2.cvtColor(frame["rgb"], cv2.COLOR_RGB2BGR)
        depth = np.rint(frame["depth"] * 1000).astype(np.uint16)
        if not cv2.imwrite(str(scene / f"rgb/{name}.png"), color):
            raise OSError("Failed to write RGB")
        if not cv2.imwrite(str(scene / f"depth/{name}.png"), depth):
            raise OSError("Failed to write depth")
        np.save(scene / f"exact_depth/{name}.npy", frame["depth"], allow_pickle=False)
    if not cv2.imwrite(str(scene / "masks/000000.png"), frames[0]["ob_mask"].astype(np.uint8) * 255):
        raise OSError("Failed to write mask")
    mesh = trimesh.load(MESH, force="mesh")
    mesh.apply_scale(0.001)
    mesh.export(scene / "socket_m.ply")
    write_json(directory / "capture.json", {"timings": timings, "sam2_calls": masks_ms, "camera": summary})
    print(f"Captured the live RGB-D and SAM2 inputs at {scene}", flush=True)


def pose_delta(reference, candidate):
    a, b = np.asarray(reference), np.asarray(candidate)
    delta = np.linalg.inv(a) @ b
    radians = np.arccos(np.clip((np.trace(delta[:3, :3]) - 1) / 2, -1, 1))
    return float(np.linalg.norm(delta[:3, 3]) * 1000), float(np.degrees(radians))


def compare(directory, estimator):
    from datareader import YcbineoatReader
    from Utils import draw_posed_3d_box

    scene = directory / "scene"
    live = json.loads((directory / "capture.json").read_text())
    mesh = trimesh.load(scene / "socket_m.ply", force="mesh")
    script = FOUNDATIONPOSE / "run_demo.py"
    timings = []
    instrument(estimator, timings)
    # Supply the original float depth values to both paths. Standard PNGs are
    # also saved so the official demo can replay this directory directly.
    YcbineoatReader.get_depth = lambda self, i: np.load(
        scene / f"exact_depth/{self.id_strs[i]}.npy", allow_pickle=False
    )
    rows = []
    for index, iterations in enumerate((5, 3, 2, 2, 3, 5), start=1):
        timings.clear()
        output = directory / f"official-{index}-iter{iterations}"
        sys.argv = [str(script), "--mesh_file", str(scene / "socket_m.ply"),
                    "--test_scene_dir", str(scene), "--debug", "0", "--headless",
                    "--debug_dir", str(output), "--est_refine_iter", str(iterations), "--track_refine_iter", "2"]
        runpy.run_path(str(script), run_name="__main__")
        if len(timings) != len(live["timings"]):
            raise RuntimeError("Official and live frame counts differ")
        delta = [pose_delta(a["pose_cad_m"], b["pose_cad_m"]) for a, b in zip(live["timings"], timings)]
        row = {"run": index, "iterations": iterations, "register_ms": timings[0]["ms"],
               "track_median_ms": median(x["ms"] for x in timings[1:]),
               "initial_delta_to_live_mm_deg": delta[0],
               "max_delta_to_live_mm_deg": np.max(delta, axis=0).tolist()}
        rows.append(row)
        overlay = cv2.imread(str(scene / "rgb/000000.png"))
        K = np.loadtxt(scene / "cam_K.txt")
        pose = np.asarray(timings[0]["pose_cad_m"])
        cv2.imwrite(str(output / "first_pose.jpg"), draw_posed_3d_box(K, overlay, pose, mesh.bounds))
        write_json(directory / "comparison.json", {"live_register_ms": live["timings"][0]["ms"],
                   "live_track_median_ms": median(x["ms"] for x in live["timings"][1:]),
                   "sam2_calls": live["sam2_calls"], "official_trials": rows})
        print(json.dumps(row), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("capture", "compare"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("--serial", default="349222063070")
    args = parser.parse_args()
    directory = args.directory.resolve()
    sys.path.insert(0, str(FOUNDATIONPOSE))
    os.environ.setdefault("FDONPOSE_TMP", str(directory / "tmp"))
    from estimater import FoundationPose

    logging.getLogger().setLevel(logging.WARNING)
    if args.mode == "capture":
        directory.mkdir(parents=True, exist_ok=False)
        capture(directory, args.serial, FoundationPose)
    else:
        compare(directory, FoundationPose)


if __name__ == "__main__":
    main()
