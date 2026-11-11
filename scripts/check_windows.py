"""Read-only Windows inventory; --output writes a new diagnostic JSON only.

No dependency imports, installation, camera access, or robot access. A passing
inventory is only permission to attempt builds, not proof of working inference.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str]) -> dict:
    try:
        result = subprocess.run(args, capture_output=True, timeout=30)
        return {
            "returncode": result.returncode,
            "stdout": result.stdout.decode("utf-8-sig", errors="replace").strip(),
            "stderr": result.stderr.decode("utf-8-sig", errors="replace").strip(),
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"returncode": None, "error": str(exc)}


def inspect() -> dict:
    program_x86 = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
    vswhere = program_x86 / "Microsoft Visual Studio/Installer/vswhere.exe"
    vs_result = run([str(vswhere), "-all", "-products", "*", "-format", "json", "-utf8"])
    instances = []
    if vs_result.get("returncode") == 0:
        try:
            instances = json.loads(vs_result["stdout"])
        except ValueError as exc:
            vs_result["parse_error"] = str(exc)
    toolchains = []
    for instance in instances:
        location = Path(instance["installationPath"])
        for compiler in (location / "VC/Tools/MSVC").glob("*/bin/Hostx64/x64/cl.exe"):
            version = compiler.parents[3].name
            toolchains.append({
                "instance_id": instance.get("instanceId"),
                "instance_path": str(location),
                "instance_complete": instance.get("isComplete", False),
                "toolset": version,
                "compiler": str(compiler),
                "developer_shell_exists": (
                    (location / "Common7/Tools/VsDevCmd.bat").is_file()
                    or (location / "VC/Auxiliary/Build/vcvars64.bat").is_file()
                ),
                "nvcc_host_setup_files": all(
                    (location / "VC/Auxiliary/Build" / name).is_file()
                    for name in ("vcvarsall.bat", "vcvars64.bat")
                ),
            })
    sdk_root = program_x86 / "Windows Kits/10"
    if os.name == "nt":
        import winreg

        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Microsoft\Windows Kits\Installed Roots",
                    access=winreg.KEY_READ | view,
                ) as key:
                    sdk_root = Path(winreg.QueryValueEx(key, "KitsRoot10")[0])
                    break
            except OSError:
                continue
    sdk_files = [
        sdk_root / "Include/10.0.22621.0/um/Windows.h",
        sdk_root / "Include/10.0.22621.0/ucrt/stdio.h",
        sdk_root / "Lib/10.0.22621.0/um/x64/kernel32.lib",
        sdk_root / "Lib/10.0.22621.0/ucrt/x64/ucrt.lib",
    ]
    sdk = {str(path): path.is_file() for path in sdk_files}
    compatible = [
        item for item in toolchains
        if item["toolset"].startswith("14.38.")
        and item["instance_complete"] and item["developer_shell_exists"]
    ]
    conda = shutil.which("conda")
    if not conda:
        for base in (Path.home() / "anaconda3", Path.home() / "miniconda3"):
            candidate = base / "Scripts/conda.exe"
            if candidate.is_file():
                conda = str(candidate)
                break
    gpu = run([shutil.which("nvidia-smi") or "nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"])
    upstream = ROOT / "third_party/FoundationPose"
    git_head = run(["git", "-C", str(upstream), "rev-parse", "HEAD"])
    expected = json.loads((ROOT / "config/upstream.json").read_text(encoding="utf-8"))
    checks = {
        "windows_host": os.name == "nt",
        "conda_found": conda is not None,
        "nvidia_driver_query": gpu.get("returncode") == 0 and bool(gpu.get("stdout")),
        "complete_msvc_14_38": bool(compatible),
        "nvcc_host_setup_files": any(item["nvcc_host_setup_files"] for item in compatible),
        "windows_sdk_22621": all(sdk.values()),
        "upstream_revision_matches": git_head.get("returncode") == 0 and git_head.get("stdout") == expected["foundationpose"]["commit"],
    }
    return {
        "schema_version": 1,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "project": str(ROOT),
        "inventory_python": sys.executable,
        "checks": checks,
        "system_prerequisites_ready": all(checks.values()),
        "blockers": [name for name, passed in checks.items() if not passed],
        "conda": conda,
        "gpu": gpu,
        "visual_studio_query": vs_result,
        "toolchains": toolchains,
        "sdk_files": sdk,
        "project_python_exists": (ROOT / ".runtime/foundationpose/python.exe").is_file(),
        "cuda_nvcc_on_path": shutil.which("nvcc"),
        "foundationpose_revision": git_head,
        "gpu_validation": "not_run_by_this_inventory",
        "official_demo": "not_run_by_this_inventory",
        "charging_port_inference": "not_run_by_this_inventory",
        "camera_validation": {"D435": "not_run_by_this_inventory", "D415": "not_run_by_this_inventory"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Create a new JSON report; never overwrite.")
    args = parser.parse_args()
    report = inspect()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    for name, passed in report["checks"].items():
        print(f"{'PASS' if passed else 'BLOCKED'} {name}")
    print("GPU kernels / FoundationPose / cameras: not exercised by this inventory; see separate reports")
    if args.output:
        print(f"Report: {args.output.resolve()}")
    return 0 if report["system_prerequisites_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
