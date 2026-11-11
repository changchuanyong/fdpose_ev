"""Create the printable calibration-tag plate that bolts onto the charging socket.

The plate and the socket form one rigid assembly: the plate's flat rear face
lies on the socket flange front plane (target z = 0) and two M6 bolts pass
through the socket flange holes at target (36, -36) and (36, 36).  Units are
millimetres; the marker is printed in place with a second extruder, so its size
and height come from the model instead of a glued sticker.

Local frame: origin at the rear lower-left corner, x right, y up, z out of the
plate towards the camera.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import struct
import zipfile


ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "assets" / "print"

PLATE_W, PLATE_H, BASE_T = 80.0, 70.0, 3.0

# Marker frame: outer 14..66 x 9..61, opening 17..63 x 12..58 (46 mm).
FRAME = ((14.0, 66.0, 9.0, 12.0), (14.0, 66.0, 58.0, 61.0),
         (14.0, 17.0, 12.0, 58.0), (63.0, 66.0, 12.0, 58.0))
OPEN_X0, OPEN_X1 = 17.0, 63.0
OPEN_Y0, OPEN_Y1 = 12.0, 58.0
FRAME_Z0, FRAME_Z1 = 3.0, 4.0

MARKER_SIZE = OPEN_X1 - OPEN_X0
MODULE = MARKER_SIZE / 8.0
PIXEL_Z0 = 3.6

# M6 clearance holes, measured from socket_mod.STL: the socket flange has four
# 6.89 mm through-holes at mesh (8.94/80.94, 8.95/80.95), flange face y = 35.
BOLT_D = 6.6
BOLT_LOCAL = ((-9.06, 8.95), (-9.06, 80.95))

# Bolt ears (x0, x1, y0, y1); they overlap the plate so the union is solid.
EARS = ((-16.0, 8.0, 0.0, 18.0), (-16.0, 2.0, 70.0, 90.0))
TOP_CONNECTOR = (0.0, 8.0, 66.0, 90.0)

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


def box(x0: float, x1: float, y0: float, y1: float, z0: float, z1: float) -> list[bytes]:
    v = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
    ]
    faces = [
        ((0, 3, 2, 1), (0, 0, -1)), ((4, 5, 6, 7), (0, 0, 1)),
        ((0, 1, 5, 4), (0, -1, 0)), ((1, 2, 6, 5), (1, 0, 0)),
        ((2, 3, 7, 6), (0, 1, 0)), ((3, 0, 4, 7), (-1, 0, 0)),
    ]
    out = []
    for corners, normal in faces:
        out.extend([tri([v[corners[0]], v[corners[1]], v[corners[2]]], normal),
                    tri([v[corners[0]], v[corners[2]], v[corners[3]]], normal)])
    return out


def face(a, b, c) -> bytes:
    u = [b[i] - a[i] for i in range(3)]
    v = [c[i] - a[i] for i in range(3)]
    normal = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    length = math.sqrt(sum(x * x for x in normal)) or 1.0
    return tri([a, b, c], tuple(x / length for x in normal))


def prism(poly, z0: float, z1: float) -> list[bytes]:
    points = [(x, y) for x, y in poly]
    area = 0.0
    for index, (x1, y1) in enumerate(points):
        x2, y2 = points[(index + 1) % len(points)]
        area += x1 * y2 - x2 * y1
    if area < 0:
        points.reverse()
    n = len(points)
    top = [(x, y, z1) for x, y in points]
    bottom = [(x, y, z0) for x, y in points]
    out = []
    for index in range(1, n - 1):
        out.append(face(top[0], top[index], top[index + 1]))
        out.append(face(bottom[0], bottom[index + 1], bottom[index]))
    for index in range(n):
        j = (index + 1) % n
        out += [face(bottom[index], bottom[j], top[j]), face(bottom[index], top[j], top[index])]
    return out


def rect_with_hole(x0, x1, y0, y1, cx, cy, r, z0, z1, segments=12) -> list[bytes]:
    out = box(x0, cx - r, y0, y1, z0, z1)
    out += box(cx + r, x1, y0, y1, z0, z1)
    out += box(cx - r, cx + r, y0, cy - r, z0, z1)
    out += box(cx - r, cx + r, cy + r, y1, z0, z1)
    for qx, qy, start in ((cx + r, cy + r, 0.0), (cx - r, cy + r, 90.0),
                          (cx - r, cy - r, 180.0), (cx + r, cy - r, 270.0)):
        poly = [(qx, qy)]
        for index in range(segments + 1):
            angle = math.radians(start + 90.0 * index / segments)
            poly.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
        out += prism(poly, z0, z1)
    return out


def marker_grid() -> list[list[bool]]:
    grid = [[True] * 8 for _ in range(8)]
    for row, line in enumerate(PAYLOAD):
        for col, bit in enumerate(line):
            grid[row + 1][col + 1] = bit == "#"
    return grid


def marker_rects(want: bool) -> list[tuple[float, float, float, float]]:
    grid = marker_grid()
    rects = []
    for row in range(8):
        col = 0
        while col < 8:
            if grid[row][col] != want:
                col += 1
                continue
            start = col
            while col < 8 and grid[row][col] == want:
                col += 1
            y1 = OPEN_Y1 - row * MODULE
            rects.append((OPEN_X0 + start * MODULE, OPEN_X0 + col * MODULE, y1 - MODULE, y1))
    return rects


def write_stl(path: Path, triangles: list[bytes]) -> None:
    header = b"fdonpose socket-bolted calibration tag mount".ljust(80, b" ")
    path.write_bytes(header + struct.pack("<I", len(triangles)) + b"".join(triangles))


def plate_triangles(printed: bool) -> list[bytes]:
    pieces = [box(0.0, PLATE_W, 0.0, PLATE_H, 0.0, BASE_T),
              box(*TOP_CONNECTOR, 0.0, BASE_T)]
    for (x0, x1, y0, y1), (cx, cy) in zip(EARS, BOLT_LOCAL):
        pieces.append(rect_with_hole(x0, x1, y0, y1, cx, cy, BOLT_D / 2.0, 0.0, BASE_T))
    for x0, x1, y0, y1 in FRAME:
        pieces.append(box(x0, x1, y0, y1, FRAME_Z0, FRAME_Z1))
    if printed:
        pieces.append(box(OPEN_X0, OPEN_X1, OPEN_Y0, OPEN_Y1, FRAME_Z0, PIXEL_Z0))
    return [triangle for piece in pieces for triangle in piece]


def build_print() -> tuple[list[bytes], list[bytes]]:
    white = plate_triangles(printed=True)
    for x0, x1, y0, y1 in marker_rects(False):
        white += box(x0, x1, y0, y1, PIXEL_Z0, FRAME_Z1)
    black: list[bytes] = []
    for x0, x1, y0, y1 in marker_rects(True):
        black += box(x0, x1, y0, y1, PIXEL_Z0, FRAME_Z1)
    return white, black


def unpack(triangles: list[bytes]):
    vertices, faces = [], []
    for triangle in triangles:
        values = struct.unpack("<3f9fH", triangle)
        base = len(vertices)
        vertices.extend((values[3:6], values[6:9], values[9:12]))
        faces.append((base, base + 1, base + 2))
    return vertices, faces


def mesh_object(object_id: int, name: str, triangles: list[bytes]) -> str:
    vertices, faces = unpack(triangles)
    vertex_xml = "".join(
        f'<vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>' for x, y, z in vertices
    )
    triangle_xml = "".join(
        f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in faces
    )
    return (
        f'<object id="{object_id}" name="{name}" type="model"><mesh>'
        f"<vertices>{vertex_xml}</vertices><triangles>{triangle_xml}</triangles></mesh></object>"
    )


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

MODEL_SETTINGS = """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <object id="3">
    <metadata key="name" value="Black-white tag mount, bolted to the socket"/>
    <metadata key="extruder" value="1"/>
    <part id="1" subtype="normal_part">
      <metadata key="name" value="WHITE - plate, frame and white pixels"/>
      <metadata key="extruder" value="1"/>
    </part>
    <part id="2" subtype="normal_part">
      <metadata key="name" value="BLACK - black pixels"/>
      <metadata key="extruder" value="2"/>
    </part>
  </object>
</config>
"""


def write_3mf(path: Path, white: list[bytes], black: list[bytes]) -> None:
    model = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<model unit="millimeter" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">\n'
        '  <metadata name="Title">Dual-colour fiducial tag mount, bolted to the charging socket</metadata>\n'
        "  <resources>\n"
        "    " + mesh_object(1, "WHITE_plate_and_frame", white) + "\n"
        "    " + mesh_object(2, "BLACK_tag_pixels", black) + "\n"
        '    <object id="3" name="BW_tag_mount" type="model"><components>'
        '<component objectid="1"/><component objectid="2"/></components></object>\n'
        "  </resources>\n"
        '  <build><item objectid="3"/></build>\n'
        "</model>\n"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("_rels/.rels", PACKAGE_RELS)
        archive.writestr("3D/3dmodel.model", model)
        archive.writestr("Metadata/model_settings.config", MODEL_SETTINGS)


def write_layout(path: Path) -> None:
    scale, pad = 6.0, 44.0
    xmin, ymin, xmax, ymax = -16.0, 0.0, 80.0, 90.0
    width = (xmax - xmin) * scale + 2 * pad
    height = (ymax - ymin) * scale + 2 * pad

    def point(x: float, y: float) -> tuple[float, float]:
        return (pad + (x - xmin) * scale, height - pad - (y - ymin) * scale)

    outline = [(-16, 0), (80, 0), (80, 70), (8, 70), (8, 90), (-16, 90),
               (-16, 70), (0, 70), (0, 18), (-16, 18)]
    polygon = " ".join(f"{point(x, y)[0]:.1f},{point(x, y)[1]:.1f}" for x, y in outline)
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
        f'viewBox="0 0 {width:.0f} {height:.0f}">',
        "<style>text{font-family:Arial,sans-serif;fill:#111827}"
        ".small{font-size:17px}.label{font-size:22px;font-weight:bold}</style>",
        f'<polygon points="{polygon}" fill="#dbe7f5" stroke="#1f2937" stroke-width="2"/>',
    ]
    a, b = point(14.0, 61.0), point(66.0, 9.0)
    lines.append(f'<rect x="{a[0]:.1f}" y="{a[1]:.1f}" width="{b[0]-a[0]:.1f}" '
                 f'height="{b[1]-a[1]:.1f}" fill="none" stroke="#2563eb" stroke-width="4"/>')
    a, b = point(OPEN_X0, OPEN_Y1), point(OPEN_X1, OPEN_Y0)
    lines.append(f'<rect x="{a[0]:.1f}" y="{a[1]:.1f}" width="{b[0]-a[0]:.1f}" '
                 f'height="{b[1]-a[1]:.1f}" fill="#ffffff" stroke="#2563eb" stroke-width="2"/>')
    for cx, cy in BOLT_LOCAL:
        c = point(cx, cy)
        lines.append(f'<circle cx="{c[0]:.1f}" cy="{c[1]:.1f}" r="{BOLT_D / 2 * scale:.1f}" '
                     f'fill="#ffffff" stroke="#dc2626" stroke-width="3"/>')
    tx, ty = point(40.0, 35.0)
    lines.append(f'<text x="{tx:.0f}" y="{ty:.0f}" text-anchor="middle" class="label">'
                 "ArUco 46 × 46 mm</text>")
    lines.append(f'<text x="{tx:.0f}" y="{ty + 26:.0f}" text-anchor="middle" class="small">'
                 "8 × 5.75 mm, top edge to target +y</text>")
    tx, ty = point(40.0, 82.0)
    lines.append(f'<text x="{tx:.0f}" y="{ty:.0f}" text-anchor="middle" class="label">'
                 "2 × M6 to the socket flange</text>")
    tx, ty = point(40.0, -8.0)
    lines.append(f'<text x="{tx:.0f}" y="{min(ty, height - 14):.0f}" text-anchor="middle" class="small">'
                 "80 × 70 plate, rear face on the socket flange (target z = 0)</text>")
    tx, ty = point(-16.0, 48.0)
    lines.append(f'<text x="{tx:.0f}" y="{ty:.0f}" text-anchor="middle" class="small" '
                 'transform="rotate(-90 ' + f"{tx:.0f} {ty:.0f}" + ')">'
                 "left edge: target x = +45</text>")
    lines.append("</svg>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_spec() -> dict:
    return {
        "schema_version": 2,
        "units": "mm",
        "assembly": {
            "socket_mesh": str(ROOT / "assets" / "mesh" / "socket_mod.STL"),
            "interface": "plate rear face on the socket flange front plane (target z = 0)",
            "fastening": "2 x M6 x 16 through the 6.89 mm socket flange holes, washer and nut behind the flange",
            "target_hole_centers": [[36.0, -36.0], [36.0, 36.0]],
            "rigid": True,
        },
        "plate": {
            "width": PLATE_W,
            "height": PLATE_H,
            "base_thickness": BASE_T,
            "overall_width": PLATE_W - EARS[0][0],
            "overall_height": 90.0,
        },
        "bolt_holes": {
            "diameter": BOLT_D,
            "local_centers": [list(center) for center in BOLT_LOCAL],
        },
        "tag_square": {
            "frame_outer": [14.0, 66.0, 9.0, 61.0],
            "opening": [OPEN_X0, OPEN_X1, OPEN_Y0, OPEN_Y1],
            "marker_size": MARKER_SIZE,
            "module": MODULE,
            "front_z": FRAME_Z1,
        },
        "datum": {
            "local_origin": "rear lower-left corner",
            "left_edge": "target x=+45 mm socket flange right edge",
            "lower_edge": "target y=-45 mm socket flange lower edge",
            "rear_face": "target z=0 mm socket flange front plane",
        },
        "nominal_tag_center_in_target_m": [0.085, -0.010, 0.004],
        "marker_convention": "ArUco image x right, image y down; the printed pixel grid is mirrored in y against the PNG so the marker top edge faces target +y.",
        "print": {
            "material": "PLA",
            "layer_height_mm": 0.2,
            "infill_percent": 30,
            "supports": "none",
            "nozzle_mm": 0.4,
            "dual_colour": True,
            "note": "flat rear face on the build plate; marker pixels print face up, no overhang",
        },
        "file": str(ASSETS / "tag_mount_plate.stl"),
        "model_file": str(ASSETS / "tag_mount_black_white_H2C.3mf"),
        "marker_file": str(ASSETS / "tag_aruco_6x6_250_id0.png"),
    }


def create_marker() -> Path:
    """Regenerate the marker PNG when OpenCV with aruco is available."""
    path = ASSETS / "tag_aruco_6x6_250_id0.png"
    try:
        import cv2
    except ImportError:
        if not path.is_file():
            raise RuntimeError("opencv_aruco_module_missing")
        return path
    if not hasattr(cv2, "aruco"):
        raise RuntimeError("opencv_aruco_module_missing")
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_6X6_250)
    image = cv2.aruco.generateImageMarker(dictionary, 0, 1000, borderBits=1)
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError("marker_png_encode_failed")
    encoded.tofile(str(path))
    return path


def main() -> int:
    ASSETS.mkdir(parents=True, exist_ok=True)
    write_stl(ASSETS / "tag_mount_plate.stl", plate_triangles(printed=False))
    white, black = build_print()
    write_3mf(ASSETS / "tag_mount_black_white_H2C.3mf", white, black)
    write_layout(ASSETS / "tag_mount_layout.svg")
    create_marker()
    spec = build_spec()
    (ASSETS / "tag_mount_spec.json").write_text(
        json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(spec, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
