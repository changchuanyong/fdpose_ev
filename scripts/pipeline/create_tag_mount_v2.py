"""Generate the two-bolt socket marker and the fit coupon without CAD dependencies."""

from collections import defaultdict
import json
from math import cos, pi, sin
from pathlib import Path
import zipfile

from create_tag_mount import CONTENT_TYPES, PACKAGE_RELS, face, marker_grid, write_stl


OUT = Path(__file__).resolve().parents[2] / "assets" / "print"
HOLES = ((36.0, -36.0), (36.0, 36.0))
HOLE_RADIUS = 3.5
TAG_X, TAG_Y = 80.0, 0.0
TAG_SIZE = 46.0
PITCH = TAG_SIZE / 8
TAG_LEFT, TAG_BOTTOM = TAG_X - TAG_SIZE / 2, TAG_Y - TAG_SIZE / 2
THICKNESS, COUPON_THICKNESS, COLOR_DEPTH = 5.0, 3.0, 0.4
FLANGE_FRONT_CAD_Y, TARGET_ORIGIN_CAD_Y = 40.0, 52.5


def ear(cx, cy):
    """Triangulate one 18 mm square ear with a 64-sided through-hole."""
    inner, outer = [], []
    for index in range(64):
        angle = 2 * pi * index / 64
        dx, dy = cos(angle), sin(angle)
        scale = 9 / max(abs(dx), abs(dy))
        inner.append((round(cx + HOLE_RADIUS * dx, 6), round(cy + HOLE_RADIUS * dy, 6)))
        outer.append((round(cx + scale * dx, 6), round(cy + scale * dy, 6)))
    triangles = []
    for index, current in enumerate(outer):
        following = (index + 1) % len(outer)
        triangles.extend(((inner[index], current, outer[following]),
                          (inner[index], outer[following], inner[following])))
    return triangles, {y for x, y in outer if x == 45.0}


def footprint(coupon=False):
    """Return CCW planar triangles and the top color of each triangle."""
    triangles = []
    rows = set()
    for cx, cy in HOLES:
        ear_triangles, seam_rows = ear(cx, cy)
        triangles.extend((triangle, False) for triangle in ear_triangles)
        rows.update(seam_rows)

    grid = marker_grid()[::-1]  # Convert image rows to increasing target y.
    x_edges = [TAG_LEFT + i * PITCH for i in range(9)]
    y_edges = [TAG_BOTTOM + i * PITCH for i in range(9)]
    columns = [45.0, 52.0] if coupon else [45.0, *x_edges, 115.0]
    rows = sorted(rows if coupon else rows.union(y_edges))
    # At diagonal-only black contacts, separate the pixels by 0.20 mm on
    # either axis. This avoids a non-manifold vertical edge between colors.
    diamonds = set()
    if not coupon:
        for j in range(1, 8):
            for i in range(1, 8):
                a, b = grid[j - 1][i - 1:i + 1]
                c, d = grid[j][i - 1:i + 1]
                if a == d and b == c and a != b:
                    diamonds.add((x_edges[i], y_edges[j]))

    clip = 0.20
    for x, y in sorted(diamonds):
        points = [(x + clip, y), (x, y + clip), (x - clip, y), (x, y - clip)]
        for i, point in enumerate(points):
            triangles.append((((x, y), point, points[(i + 1) % 4]), False))

    for x0, x1 in zip(columns, columns[1:]):
        for y0, y1 in zip(rows, rows[1:]):
            center = ((x0 + x1) / 2, (y0 + y1) / 2)
            u = int((center[0] - TAG_LEFT) // PITCH)
            v = int((center[1] - TAG_BOTTOM) // PITCH)
            black = not coupon and 0 <= u < 8 and 0 <= v < 8 and grid[v][u]
            corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
            directions = [((0, 1), (1, 0)), ((-1, 0), (0, 1)),
                          ((0, -1), (-1, 0)), ((1, 0), (0, -1))]
            polygon = []
            for (x, y), offsets in zip(corners, directions):
                if (x, y) in diamonds:
                    polygon.extend((x + clip * dx, y + clip * dy) for dx, dy in offsets)
                else:
                    polygon.append((x, y))
            for i, point in enumerate(polygon):
                triangles.append(((center, point, polygon[(i + 1) % len(polygon)]), black))
    return triangles


def solid(triangles, bottom, thickness, inlay=False):
    """Close a tessellated height field, omitting interior vertical faces."""
    mesh = []
    edges = defaultdict(list)
    for (a, b, c), black in triangles:
        top = thickness - COLOR_DEPTH if inlay and black else thickness
        mesh.append(((*a, top), (*b, top), (*c, top)))
        mesh.append(((*a, bottom), (*c, bottom), (*b, bottom)))
        for start, end in ((a, b), (b, c), (c, a)):
            edges[tuple(sorted((start, end)))].append((start, end, top))

    for sides in edges.values():
        if len(sides) == 1:
            (start, end, top), = sides
            low = bottom
        else:
            (start, end, top), (_, _, low) = sorted(sides, key=lambda side: -side[2])
            if top == low:
                continue
        mesh.extend((((*start, low), (*end, low), (*end, top)),
                     ((*start, low), (*end, top), (*start, top))))
    return mesh


def mesh_xml(object_id, name, mesh):
    vertices = {}
    faces = [tuple(vertices.setdefault(point, len(vertices)) for point in triangle)
             for triangle in mesh]
    vertex_xml = "".join(f'<vertex x="{x:.6f}" y="{y:.6f}" z="{z:.6f}"/>'
                         for x, y, z in vertices)
    triangle_xml = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in faces)
    return (f'<object id="{object_id}" name="{name}" type="model" pid="4" pindex="{object_id - 1}">'
            f'<mesh><vertices>{vertex_xml}</vertices><triangles>{triangle_xml}</triangles></mesh></object>')


def write_multicolor(path, white, black):
    model = f'''<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
  <resources>
    <basematerials id="4"><base name="White" displaycolor="#FFFFFF"/><base name="Black" displaycolor="#101010"/></basematerials>
    {mesh_xml(1, "WHITE body", white)}
    {mesh_xml(2, "BLACK ArUco", black)}
    <object id="3" name="M6 socket marker v2" type="model">
      <components><component objectid="1"/><component objectid="2"/></components>
    </object>
  </resources>
  <build><item objectid="3" transform="1 0 0 0 1 0 0 0 1 57 128 0"/></build>
</model>'''
    settings = '''<?xml version="1.0" encoding="UTF-8"?>
<config><object id="3">
  <metadata key="name" value="M6 socket marker v2"/>
  <metadata key="extruder" value="1"/>
  <part id="1" subtype="normal_part"><metadata key="name" value="WHITE body"/><metadata key="extruder" value="1"/></part>
  <part id="2" subtype="normal_part"><metadata key="name" value="BLACK ArUco"/><metadata key="extruder" value="2"/></part>
</object></config>'''
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("_rels/.rels", PACKAGE_RELS)
        archive.writestr("3D/3dmodel.model", model)
        archive.writestr("Metadata/model_settings.config", settings)


def write_drawing(path):
    marker = []
    for row, values in enumerate(marker_grid()):
        for col, black in enumerate(values):
            if black:
                marker.append(f'<rect x="{57 + col * PITCH}" y="{-23 + row * PITCH}" '
                              f'width="{PITCH}" height="{PITCH}"/>')
    path.write_text(f'''<svg xmlns="http://www.w3.org/2000/svg" width="980" height="590" viewBox="0 0 980 590">
  <defs>
    <marker id="start" viewBox="0 0 10 10" refX="2" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M10 0 L0 5 L10 10 Z" fill="#1e4a7b"/></marker>
    <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0 L10 5 L0 10 Z" fill="#1e4a7b"/></marker>
  </defs>
  <style>
    text {{ font-family: Microsoft YaHei; fill: #162539; font-size: 16px; }}
    .title {{ font-weight: bold; font-size: 26px; }}
    .dim {{ fill: none; stroke: #1e4a7b; stroke-width: 1.3; }}
    .outline {{ stroke: #22354d; stroke-width: 1.5; vector-effect: non-scaling-stroke; }}
  </style>
  <rect width="980" height="590" fill="#fff"/>
  <text x="32" y="42" class="title">插座标定板 V2 · 双 M6 螺栓安装</text>
  <text x="32" y="72">正视图 · 尺寸单位 mm</text>
  <g transform="translate(205 314) scale(3.5)">
    <rect class="outline" x="-45" y="-45" width="90" height="90" fill="#e5e9ee"/>
    <circle class="outline" r="35.75" fill="#d3dce7"/>
    <circle class="outline" cx="-36" cy="-36" r="3.5" fill="white"/>
    <circle class="outline" cx="-36" cy="36" r="3.5" fill="white"/>
    <path class="outline" fill="#fff" d="M27 -45 H115 V45 H27 V27 H45 V-27 H27 Z"/>
    <path class="outline" fill="none" stroke-dasharray="2 1" d="M52 -45 V45"/>
    <g fill="#101010">{''.join(marker)}</g>
    <g stroke="#294f78" stroke-width=".42" fill="white">
      <circle cx="36" cy="-36" r="3.5"/><circle cx="36" cy="36" r="3.5"/>
    </g>
  </g>
  <g class="dim">
    <path d="M331 188 H410 M331 440 H410 M300 153 V117 M607 153 V117 M48 472 V516 M363 472 V516"/>
    <path d="M300 122 H607" marker-start="url(#start)" marker-end="url(#arrow)"/>
    <path d="M400 188 V440" marker-start="url(#start)" marker-end="url(#arrow)"/>
    <path d="M48 505 H363" marker-start="url(#start)" marker-end="url(#arrow)"/>
    <path d="M615 174 H577 L343 188" marker-end="url(#arrow)"/>
  </g>
  <text x="454" y="112" text-anchor="middle">88 · 新板总宽</text>
  <text x="411" y="230">72</text>
  <text x="205" y="532" text-anchor="middle">90 · 插座法兰宽</text>
  <text x="627" y="178">2 × Ø7 通孔</text>
  <text x="80" y="310">插座前端</text>
  <text x="485" y="499" text-anchor="middle">ArUco 46 × 46</text>
  <text x="32" y="565">虚线是试装件外缘。整板和试装件共用两个安装孔及安装耳。</text>
  <text x="645" y="238" class="title">紧固剖面</text>
  <text x="645" y="265">前方 / 相机侧 ←</text>
  <g class="outline">
    <rect x="747" y="304" width="28" height="88" fill="#f3f7fb"/>
    <rect x="775" y="304" width="28" height="88" fill="#d3dce7"/>
    <rect x="728" y="334" width="14" height="28" fill="#a9b8c9"/>
    <rect x="742" y="330" width="5" height="36" fill="#c0cad5"/>
    <rect x="803" y="330" width="5" height="36" fill="#c0cad5"/>
    <rect x="808" y="334" width="18" height="28" fill="#a9b8c9"/>
    <rect x="742" y="343" width="93" height="10" fill="#9baec3"/>
  </g>
  <text x="649" y="418">板厚 5</text>
  <text x="774" y="418">法兰厚 5</text>
  <text x="649" y="447">M6×20 螺栓 + 两面垫片 + 螺母</text>
  <text x="649" y="476">螺母侧留出工具空间</text>
</svg>
''', encoding="utf-8")


def main():
    OUT.mkdir(exist_ok=True)
    planar = footprint()
    write_stl(OUT / "socket_tag_m6_v2.stl", [face(*tri) for tri in solid(planar, 0.0, THICKNESS)])
    coupon = solid(footprint(coupon=True), 0.0, COUPON_THICKNESS)
    write_stl(OUT / "socket_tag_m6_fit_coupon.stl", [face(*tri) for tri in coupon])
    white = solid(planar, 0.0, THICKNESS, inlay=True)
    black = solid([(tri, color) for tri, color in planar if color], THICKNESS - COLOR_DEPTH, THICKNESS)
    write_multicolor(OUT / "socket_tag_m6_v2.3mf", white, black)
    write_drawing(OUT / "socket_tag_m6_assembly.svg")
    flange_z = FLANGE_FRONT_CAD_Y - TARGET_ORIGIN_CAD_Y
    spec = {
        "units": "mm", "validated_on_hardware": False,
        "mesh_frame": "x and y follow target; z=0 is the plate rear mounting face",
        "target_origin_cad_y_mm": TARGET_ORIGIN_CAD_Y,
        "flange_front_cad_y_mm": FLANGE_FRONT_CAD_Y, "flange_front_target_z_mm": flange_z,
        "mount_hole_centers_xy_mm": HOLES, "mount_hole_diameter_mm": 2 * HOLE_RADIUS,
        "plate_thickness_mm": THICKNESS, "fit_coupon_thickness_mm": COUPON_THICKNESS,
        "marker": {"dictionary": "DICT_6X6_250", "id": 0, "side_mm": TAG_SIZE,
                   "top_edge_direction": "+target_y", "center_target_mm": [TAG_X, TAG_Y, flange_z + THICKNESS],
                   "T_target_tag_nominal_m": [[1, 0, 0, TAG_X / 1000], [0, 1, 0, TAG_Y / 1000],
                                             [0, 0, 1, (flange_z + THICKNESS) / 1000], [0, 0, 0, 1]]},
    }
    (OUT / "socket_tag_m6_spec.json").write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
