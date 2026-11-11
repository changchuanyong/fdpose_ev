"""Exercise actual CUDA matrix multiplication and torchvision NMS on this host."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import traceback


def check(expect_torch: str, expect_torchvision: str) -> dict:
    import torch
    import torchvision

    if torch.__version__ != expect_torch:
        raise RuntimeError(f"Unexpected PyTorch candidate: {torch.__version__} (expected {expect_torch})")
    if torchvision.__version__ != expect_torchvision:
        raise RuntimeError(
            f"Unexpected torchvision candidate: {torchvision.__version__} (expected {expect_torchvision})"
        )
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable")
    device = torch.device("cuda:0")
    matrix = torch.arange(16, dtype=torch.float32, device=device).reshape(4, 4)
    product = matrix @ matrix.T
    reference = matrix.cpu() @ matrix.cpu().T
    torch.cuda.synchronize()
    if not torch.equal(product.cpu(), reference):
        raise RuntimeError("CUDA matrix product differs from CPU reference")
    boxes = torch.tensor([[0, 0, 10, 10], [0, 0, 10, 10], [20, 20, 30, 30]], dtype=torch.float32, device=device)
    scores = torch.tensor([0.9, 0.8, 0.7], device=device)
    selected = torchvision.ops.nms(boxes, scores, 0.5)
    torch.cuda.synchronize()
    if selected.cpu().tolist() != [0, 2]:
        raise RuntimeError("Unexpected CUDA NMS result")
    return {
        "torch": torch.__version__,
        "torchvision": torchvision.__version__,
        "cuda": torch.version.cuda,
        "device": torch.cuda.get_device_name(0),
        "capability": list(torch.cuda.get_device_capability(0)),
        "compiled_architectures": torch.cuda.get_arch_list(),
        "matrix_product_passed": True,
        "torchvision_nms_passed": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expect-torch", default="2.7.1+cu128", help="Expected torch.__version__ string.")
    parser.add_argument(
        "--expect-torchvision", default="0.22.1+cu128", help="Expected torchvision.__version__ string."
    )
    args = parser.parse_args()
    # Refuse to run if its report would overwrite previous validation evidence.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        report = {
            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            "python": sys.executable,
            "passed": False,
        }
        try:
            report.update(check(args.expect_torch, args.expect_torchvision))
            report["passed"] = True
        except Exception as exc:
            report["error_type"] = type(exc).__name__
            report["error"] = str(exc)
            report["traceback"] = traceback.format_exc()
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
