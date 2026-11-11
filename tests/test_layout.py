"""目录结构冒烟检查：只依赖标准库。"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 绕过的目录：上游源码、产物、缓存
SKIP_TOP = {"third_party", ".git", "artifacts", ".cache", ".runtime"}

REQUIRED = (
    "README.md",
    "NOTICE.md",
    "pyproject.toml",
    ".gitignore",
    ".gitattributes",
    "docs/index.md",
    "docs/jetson_setup.md",
    "docs/charging_replay.md",
    "docs/tag_mount.md",
    "config/runtime-jetson.txt",
    "config/upstream.json",
    "config/geometry/socket_openings_ply.json",
    "assets/mesh/socket_mod.STL",
    "patches/README.md",
    "patches/foundationpose-windows.patch",
    "apps/jetson_foundationpose_d415.py",
    "scripts/setup/jetson_setup.sh",
    "scripts/pipeline/charging_replay.py",
    "scripts/pipeline/tag_mount_common.py",
    "scripts/pipeline/create_tag_mount_v2.py",
    "scripts/eval/jetson_pose_parity.py",
    "scripts/probes/check_extension.py",
    "scripts/probes/check_torch_gpu.py",
)

PARENTS_RE = re.compile(r"parents\[(\d+)\]")


class LayoutTest(unittest.TestCase):
    def test_required_paths_exist(self) -> None:
        missing = [name for name in REQUIRED if not (ROOT / name).exists()]
        self.assertEqual([], missing, f"缺少约定文件：{missing}")

    def test_repo_root_depth_matches(self) -> None:
        """脚本里 parents[N] 的 N 必须等于该文件到仓库根相隔的目录层数。"""
        problems = []
        for path in sorted(ROOT.rglob("*.py")):
            rel = path.relative_to(ROOT)
            if rel.parts[0] in SKIP_TOP or "__pycache__" in rel.parts:
                continue
            depth = len(rel.parts) - 1
            text = path.read_text(encoding="utf-8", errors="replace")
            for index in sorted({int(n) for n in PARENTS_RE.findall(text)}):
                if index != depth:
                    problems.append(f"{rel.as_posix()}: parents[{index}]，实际深度 {depth}")
        self.assertEqual([], problems)

    def test_no_legacy_asset_name(self) -> None:
        """旧的资产文件名不应再出现在代码与文档里。"""
        legacy = "\u63d2\u5ea7\u6539"  # 原网格文件名，已改为 socket_mod.*
        stale = []
        for pattern in ("*.py", "*.md", "*.sh"):
            for path in ROOT.rglob(pattern):
                rel = path.relative_to(ROOT)
                if rel.parts[0] in SKIP_TOP or "__pycache__" in rel.parts:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                if legacy in text:
                    stale.append(rel.as_posix())
        self.assertEqual([], stale, f"仍引用旧资产名：{stale}")


if __name__ == "__main__":
    unittest.main()
