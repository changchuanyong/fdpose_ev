"""文档相对链接检查：避免再出现指向未入库产物的死链。"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SKIP_TOP = {"third_party", ".git", "artifacts", ".cache", ".runtime"}
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
EXTERNAL = ("http://", "https://", "mailto:", "#")


def markdown_files() -> list[Path]:
    files = [ROOT / "README.md", ROOT / "NOTICE.md"]
    files.extend(sorted((ROOT / "docs").rglob("*.md")))
    return [path for path in files if path.exists()]


class DocsLinkTest(unittest.TestCase):
    def test_relative_links_resolve(self) -> None:
        broken = []
        for path in markdown_files():
            text = path.read_text(encoding="utf-8")
            for target in LINK_RE.findall(text):
                if target.startswith(EXTERNAL):
                    continue
                relative = target.split("#", 1)[0]
                if not relative:
                    continue
                if not (path.parent / relative).resolve().exists():
                    broken.append(f"{path.relative_to(ROOT).as_posix()} -> {target}")
        self.assertEqual([], broken, "存在死链")

    def test_no_links_into_gitignored_artifacts(self) -> None:
        offenders = []
        for path in markdown_files():
            text = path.read_text(encoding="utf-8")
            for target in LINK_RE.findall(text):
                if target.startswith(("artifacts/", "../artifacts/")):
                    offenders.append(f"{path.relative_to(ROOT).as_posix()} -> {target}")
        self.assertEqual([], offenders, "artifacts/ 不随仓库分发，不能作为链接目标")


if __name__ == "__main__":
    unittest.main()
