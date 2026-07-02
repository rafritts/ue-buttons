"""Server-side renderer for `view(map)` — the top-down site plan (SPEC-01 E3).

Takes the map data the runtime assembled (height grid + labelled actor markers + paths +
scatter regions) and draws a labelled coordinate map with PIL. Server-side because it's far
easier to label than an editor screenshot and has no async-capture dependency (G8 doesn't
block it). The map is the grounding for absolute [x,y]: the agent reads waypoints/feature
centres OFF it rather than divining numbers.

Compass convention baked into the axes: north = +X (up), east = +Y (right).
"""
import os

from PIL import Image, ImageDraw, ImageFont

PX = 820                # plot area (square), px
PAD = 70               # margin for axis labels
GRID_CM = 2000.0        # gridline every 20 m at hamlet scale


def _font(size):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _terrain_color(t):
    """Height ramp in [0,1]: valley floor green → slopes tan → peaks grey/white."""
    stops = [(0.0, (60, 90, 55)), (0.35, (95, 120, 70)), (0.6, (150, 135, 95)),
             (0.8, (135, 120, 110)), (1.0, (235, 235, 240))]
    for (a, ca), (b, cb) in zip(stops, stops[1:]):
        if t <= b:
            f = 0 if b == a else (t - a) / (b - a)
            return tuple(int(ca[k] + (cb[k] - ca[k]) * f) for k in range(3))
    return stops[-1][1]


def render(data, out_path):
    """Render map `data` to a PNG at out_path. Returns out_path. North (+X) is up, east (+Y)
    right; the compass matches UE yaw."""
    bounds = data.get("bounds")
    W = PX + 2 * PAD
    img = Image.new("RGB", (W, W), (26, 28, 32))
    dr = ImageDraw.Draw(img)
    f_sm, f_md = _font(13), _font(16)

    if not bounds:
        dr.text((PAD, PAD), "no terrain — create a landscape first", font=f_md,
                fill=(220, 220, 220))
        img.save(out_path)
        return out_path

    x0, x1 = bounds["x"]     # +X = north (screen up)
    y0, y1 = bounds["y"]     # +Y = east (screen right)
    spanx, spany = x1 - x0, y1 - y0

    def to_px(wx, wy):
        # east(+Y) → screen x; north(+X) → screen y inverted (up = larger X)
        sx = PAD + (wy - y0) / spany * PX
        sy = PAD + (x1 - wx) / spanx * PX
        return sx, sy

    # 1. height field
    grid = data.get("grid")
    if grid:
        n = len(grid)
        flat = [h for row in grid for h in row]
        lo, hi = min(flat), max(flat)
        rng = max(1e-6, hi - lo)
        cell = Image.new("RGB", (n, n))
        cpx = cell.load()
        for j in range(n):            # grid row j → y ascending (east); col i → x (north)
            for i in range(n):
                cpx[j, n - 1 - i] = _terrain_color((grid[j][i] - lo) / rng)
        cell = cell.resize((PX, PX), Image.BILINEAR)
        img.paste(cell, (PAD, PAD))

    # 2. gridlines + axis labels (map cm)
    import math
    gx0 = math.ceil(x0 / GRID_CM) * GRID_CM
    val = gx0
    while val <= x1:
        _, sy = to_px(val, y0)
        dr.line([(PAD, sy), (PAD + PX, sy)], fill=(255, 255, 255, 40), width=1)
        dr.text((6, sy - 7), f"{int(val)}", font=f_sm, fill=(170, 175, 185))
        val += GRID_CM
    gy0 = math.ceil(y0 / GRID_CM) * GRID_CM
    val = gy0
    while val <= y1:
        sx, _ = to_px(x0, val)
        dr.line([(sx, PAD), (sx, PAD + PX)], fill=(255, 255, 255, 40), width=1)
        dr.text((sx - 12, PAD + PX + 6), f"{int(val)}", font=f_sm, fill=(170, 175, 185))
        val += GRID_CM
    dr.rectangle([PAD, PAD, PAD + PX, PAD + PX], outline=(90, 95, 105), width=1)
    dr.text((PAD, 6), "north +X ↑   east +Y →   (map cm)", font=f_sm, fill=(150, 200, 150))

    # 3. scatter regions (outlines)
    for s in data.get("scatters", []):
        _draw_region(dr, s.get("region"), to_px, (90, 200, 120))
        c = _region_center(s.get("region"))
        if c:
            sx, sy = to_px(*c)
            dr.text((sx + 3, sy), s["label"], font=f_sm, fill=(120, 220, 150))

    # 4. paths (polylines through waypoints)
    for pth in data.get("paths", []):
        pts = [to_px(px, py) for px, py in pth["points"]]
        if len(pts) >= 2:
            dr.line(pts, fill=(230, 190, 90), width=3, joint="curve")
        for px, py in pts:
            dr.ellipse([px - 3, py - 3, px + 3, py + 3], fill=(240, 210, 120))
        if pts:
            dr.text((pts[0][0] + 4, pts[0][1] - 14), pth["label"], font=f_sm,
                    fill=(240, 210, 120))

    # 5. actor markers (footprint + label)
    for m in data.get("markers", []):
        bx = m.get("bbox")
        if bx:
            p0 = to_px(bx[0], bx[1]); p1 = to_px(bx[2], bx[3])
            dr.rectangle([min(p0[0], p1[0]), min(p0[1], p1[1]),
                          max(p0[0], p1[0]), max(p0[1], p1[1])],
                         outline=(80, 170, 250), width=2)
        sx, sy = to_px(m["x"], m["y"])
        dr.ellipse([sx - 3, sy - 3, sx + 3, sy + 3], fill=(120, 190, 255))
        dr.text((sx + 5, sy - 6), m["label"], font=f_sm, fill=(200, 220, 255))

    img.save(out_path)
    return out_path


def _draw_region(dr, region, to_px, color):
    if not region:
        return
    kind = region.get("kind")
    if kind == "circle":
        cx, cy = region["at"]; r = region["radius"]
        p0 = to_px(cx - r, cy - r); p1 = to_px(cx + r, cy + r)
        dr.ellipse([min(p0[0], p1[0]), min(p0[1], p1[1]),
                    max(p0[0], p1[0]), max(p0[1], p1[1])], outline=color, width=2)
    elif kind == "rect":
        cx, cy = region["at"]; w, h = region["size"]
        p0 = to_px(cx - w / 2, cy - h / 2); p1 = to_px(cx + w / 2, cy + h / 2)
        dr.rectangle([min(p0[0], p1[0]), min(p0[1], p1[1]),
                      max(p0[0], p1[0]), max(p0[1], p1[1])], outline=color, width=2)
    elif kind == "polygon":
        pts = [to_px(x, y) for x, y in region["points"]]
        if len(pts) >= 2:
            dr.polygon(pts, outline=color)


def _region_center(region):
    if not region:
        return None
    if "at" in region:
        return region["at"]
    if "points" in region:
        pts = region["points"]
        return [sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts)]
    return None
