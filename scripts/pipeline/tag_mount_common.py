"""标定板生成器共用的网格三角化与 3MF 打包原语。

原先这些定义在 v1 生成器 ``create_tag_mount.py`` 里；v1 方案已废弃，
只保留 v2 需要的部分。
"""

from __future__ import annotations

import math
from pathlib import Path
import struct


# ArUco DICT_6X6_250 id 0 payload, image rows top -> bottom.
PAYLOAD = (
    "###...",
    ".###..",
    "..#...",
    "#..###",
    "##.#.#",
    ".##..#",
)


def tri(vertices: list[tuple[float, float, float]], normal: tuple[float, float, float]) -> bytes:
    return struct.pack("<3f9fH", *normal, *vertices[0], *vertices[1], *vertices[2], 0)


def face(a, b, c) -> bytes:
    u = [b[i] - a[i] for i in range(3)]
    v = [c[i] - a[i] for i in range(3)]
    normal = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    length = math.sqrt(sum(x * x for x in normal)) or 1.0
    return tri([a, b, c], tuple(x / length for x in normal))


def marker_grid() -> list[list[bool]]:
    grid = [[True] * 8 for _ in range(8)]
    for row, line in enumerate(PAYLOAD):
        for col, bit in enumerate(line):
            grid[row + 1][col + 1] = bit == "#"
    return grid


def write_stl(path: Path, triangles: list[bytes]) -> None:
    header = b"fdonpose socket-bolted calibration tag mount".ljust(80, b" ")
    path.write_bytes(header + struct.pack("<I", len(triangles)) + b"".join(triangles))


CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
  <Default Extension="config" ContentType="text/xml"/>
</Types>
"""

PACKAGE_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>
"""
