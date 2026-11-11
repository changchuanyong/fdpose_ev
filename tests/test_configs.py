"""配置与版本锁文件的可解析性检查：只依赖标准库。"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# name、可选 extras、若干版本约束（pip 允许逗号分隔，如 numpy>=2,<3）
REQUIREMENT_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*"
    r"(?:\[[A-Za-z0-9,._-]+\])?"
    r"(?:[<>=!~]=?\s*[0-9][0-9A-Za-z.*+_-]*"
    r"(?:\s*,\s*[<>=!~]=?\s*[0-9][0-9A-Za-z.*+_-]*)*)?$"
)


def requirement_lines(path: Path) -> list[tuple[int, str]]:
    lines = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if line:
            lines.append((number, line))
    return lines


class ConfigTest(unittest.TestCase):
    def test_json_configs_parse(self) -> None:
        broken = []
        for path in sorted((ROOT / "config").rglob("*.json")):
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                broken.append(f"{path.relative_to(ROOT).as_posix()}: {exc}")
        self.assertEqual([], broken)

    def test_jetson_requirements_are_well_formed(self) -> None:
        path = ROOT / "config" / "runtime-jetson.txt"
        bad = [
            f"{path.name}:{number}: {line}"
            for number, line in requirement_lines(path)
            if not REQUIREMENT_RE.match(line)
        ]
        self.assertEqual([], bad, "无法解析的依赖行")

    def test_no_duplicate_requirements(self) -> None:
        """同一个包只写一行；重复出现通常意味着两条约束互相矛盾。

        例：同时写 ``opencv-python-headless==5.0.0.93`` 和 ``opencv-python-headless<5``，
        pip 取交集为空，``pip install -r`` 会直接解析失败。
        """
        path = ROOT / "config" / "runtime-jetson.txt"
        seen: dict[str, list[int]] = {}
        for number, line in requirement_lines(path):
            name = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", line).group(0).lower()
            seen.setdefault(name, []).append(number)
        duplicates = {name: lines for name, lines in seen.items() if len(lines) > 1}
        self.assertEqual({}, duplicates, f"重复的依赖行（包名 -> 行号）：{duplicates}")

    def test_upstream_pin_has_commit(self) -> None:
        data = json.loads((ROOT / "config" / "upstream.json").read_text(encoding="utf-8"))
        text = json.dumps(data)
        self.assertRegex(text, r"\b[0-9a-f]{40}\b", "上游固定提交缺失或格式不对")


if __name__ == "__main__":
    unittest.main()
