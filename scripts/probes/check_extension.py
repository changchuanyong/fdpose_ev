"""Run a real operation in one required extension and save separate evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import traceback


ROOT = Path(__file__).resolve().parents[2]


def check(component: str, foundationpose_dir: Path) -> dict:
    import numpy as np

    if component == "mycpp":
        sys.path.insert(0, str(foundationpose_dir / "mycpp" / "build"))
        import mycpp

        identity = np.eye(4, dtype=np.float32)
        rotated = np.diag([-1, -1, 1, 1]).astype(np.float32)
        poses = np.stack([identity, identity, rotated])
        clusters = np.asarray(mycpp.cluster_poses(30, 99999, poses, identity[None]))
        if clusters.shape != (2, 4, 4) or not np.allclose(clusters, poses[[0, 2]]):
            raise RuntimeError("Unexpected native pose-clustering result")
        return {"module": mycpp.__file__, "input_poses": 3, "output_clusters": 2}
    if component == "warp":
        import warp as wp
        import warp.utils

        wp.config.kernel_cache_dir = str(ROOT / ".cache/warp")
        wp.init()
        source = wp.array([1, 2, 3], dtype=wp.int32, device="cuda:0")
        target = wp.empty_like(source)
        wp.utils.array_scan(source, target, inclusive=True)
        wp.synchronize()
        if not np.array_equal(target.numpy(), [1, 3, 6]):
            raise RuntimeError("Unexpected CUDA prefix-sum result")
        return {"version": wp.__version__, "device": str(target.device), "result": target.numpy().tolist()}
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable")
    if component == "pytorch3d":
        import pytorch3d
        from pytorch3d.ops import knn_points

        query = torch.tensor([[[0, 0, 0], [2, 0, 0]]], dtype=torch.float32, device="cuda")
        reference = torch.tensor([[[0, 0, 0], [3, 0, 0]]], dtype=torch.float32, device="cuda")
        result = knn_points(query, reference, K=1)
        torch.cuda.synchronize()
        if not result.dists.is_cuda or result.dists.cpu().flatten().tolist() != [0, 1]:
            raise RuntimeError("Unexpected CUDA nearest-neighbour distances")
        return {"version": pytorch3d.__version__, "distances": result.dists.cpu().flatten().tolist()}
    import nvdiffrast
    import nvdiffrast.torch as dr

    context = dr.RasterizeCudaContext()
    vertices = torch.tensor([[[-0.5, -0.5, 0, 1], [0.5, -0.5, 0, 1], [0, 0.5, 0, 1]]], dtype=torch.float32, device="cuda")
    triangles = torch.tensor([[0, 1, 2]], dtype=torch.int32, device="cuda")
    raster, _ = dr.rasterize(context, vertices, triangles, resolution=[32, 32])
    torch.cuda.synchronize()
    covered = int((raster[..., 3] > 0).sum())
    if not raster.is_cuda or not torch.isfinite(raster).all() or covered == 0:
        raise RuntimeError("CUDA rasterization produced no valid triangle pixels")
    return {"module": nvdiffrast.__file__, "covered_pixels": covered}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("component", choices=["pytorch3d", "nvdiffrast", "warp", "mycpp"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--foundationpose-dir",
        type=Path,
        default=ROOT / "third_party/FoundationPose",
        help="FoundationPose checkout that owns mycpp/build (default: this repo's third_party copy).",
    )
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    dll_handle = None
    if os.name == "nt":
        dll_handle = os.add_dll_directory(str(Path(sys.prefix) / "Library/bin"))
    with args.output.open("x", encoding="utf-8") as handle:
        report = {
            "component": args.component,
            "python": sys.executable,
            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            "passed": False,
        }
        try:
            report.update(check(args.component, args.foundationpose_dir))
            report["passed"] = True
        except Exception as exc:
            report.update(error=str(exc), error_type=type(exc).__name__, traceback=traceback.format_exc())
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    if dll_handle:
        dll_handle.close()
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
