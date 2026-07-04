"""Pure-Python heightfield engine — the single source of truth for terrain height.

SPEC-01 (G12): 5.8's Landscape API isn't scriptable and UE's Python has no numpy, so terrain
is a Geometry Script DynamicMesh whose vertices are displaced by a height function computed
here. The SAME `height_at` drives the mesh, `terrain op=describe` sampling, and spline
ground-draping — so sampled heights agree with world traces by construction, no numpy
required. No `unreal` import: this is portable maths, reusable server-side and by lint later.

Coordinates are terrain-LOCAL centimetres (relative to the terrain centre); the verb layer
adds the actor origin. Features compose in list order: additive landforms (valley/hill/
ridge/noise) accumulate; override landforms (plateau/flatten) blend the running height
toward a target inside a region — so you sculpt, then carve pads on top.
"""
import math


# ── deterministic value noise (no numpy, no RNG state) ──────────────────────────
def _hash01(ix, iy, seed):
    h = (ix * 374761393 + iy * 668265263 + seed * 1274126177) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((h ^ (h >> 16)) & 0xFFFF) / 0xFFFF


def _smooth(t):
    return t * t * (3.0 - 2.0 * t)


def _value_noise(x, y, seed):
    """Bilinear value noise in [-1, 1], smoothstep-interpolated. Deterministic in (x,y,seed)."""
    x0, y0 = math.floor(x), math.floor(y)
    fx, fy = x - x0, y - y0
    v00 = _hash01(x0, y0, seed);       v10 = _hash01(x0 + 1, y0, seed)
    v01 = _hash01(x0, y0 + 1, seed);   v11 = _hash01(x0 + 1, y0 + 1, seed)
    ux, uy = _smooth(fx), _smooth(fy)
    a = v00 * (1 - ux) + v10 * ux
    b = v01 * (1 - ux) + v11 * ux
    return (a * (1 - uy) + b * uy) * 2.0 - 1.0


def _fbm(x, y, seed, octaves):
    n = tot = 0.0
    amp = 1.0
    freq = 1.0
    for o in range(max(1, octaves)):
        n += amp * _value_noise(x * freq, y * freq, seed + o)
        tot += amp
        amp *= 0.5
        freq *= 2.0
    return n / tot if tot else 0.0


def _clamp01(t):
    return 0.0 if t < 0 else (1.0 if t > 1 else t)


# ── region membership (shared by flatten and scatter) ───────────────────────────
def region_inset(x, y, region):
    """Signed inset distance (cm) of point (x,y) w.r.t. a region: >0 inside (distance to the
    nearest edge), ≤0 outside. Region kinds: circle{at,radius}, rect{at,size:[w,h]},
    polygon{points:[[x,y],...]}. Used for point-in-region tests and edge blends."""
    kind = region.get("kind", "circle")
    if kind == "circle":
        ax, ay = region["at"]
        return region["radius"] - math.hypot(x - ax, y - ay)
    if kind == "rect":
        ax, ay = region["at"]
        w, h = region["size"]
        dx = w / 2.0 - abs(x - ax)
        dy = h / 2.0 - abs(y - ay)
        if dx >= 0 and dy >= 0:
            return min(dx, dy)                      # inside → distance to nearest edge
        return -math.hypot(max(-dx, 0.0), max(-dy, 0.0))
    if kind == "polygon":
        return _polygon_inset(x, y, region["points"])
    raise ValueError(f"unknown region kind '{kind}'")


def in_region(x, y, region):
    return region_inset(x, y, region) >= 0.0


def _polygon_inset(x, y, pts):
    inside = False
    j = len(pts) - 1
    for i in range(len(pts)):
        xi, yi = pts[i]; xj, yj = pts[j]
        if (yi > y) != (yj > y):
            xc = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < xc:
                inside = not inside
        j = i
    d = _dist_to_polygon_edge(x, y, pts)
    return d if inside else -d


def _dist_to_polygon_edge(x, y, pts):
    best = float("inf")
    j = len(pts) - 1
    for i in range(len(pts)):
        best = min(best, _dist_point_segment(x, y, pts[j], pts[i]))
        j = i
    return best


def _dist_point_segment(px, py, a, b):
    ax, ay = a; bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return math.hypot(px - ax, py - ay)
    t = _clamp01(((px - ax) * dx + (py - ay) * dy) / L2)
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


# ── landform features ────────────────────────────────────────────────────────────
def _valley(lx, ly, f, extent):
    """A valley whose floor runs along `axis`; height rises quadratically off the centreline
    beyond floor_width/2, reaching wall_height over the wall run, then holds flat (a plateau
    top). extent = half-size (cm) on the perpendicular axis.

    G51: the wall run defaults to the whole remaining half-width — a broad wash. Pass
    `wall_width` (cm) to narrow it: the wall climbs from floor edge to wall_height over
    wall_width, then plateaus. A small wall_width is how you author a slot canyon (a steep
    slit) instead of a gentle valley — narrower run over the same rise = steeper wall."""
    axis = f.get("axis", "x").lower()
    perp = ly if axis == "x" else lx
    fw = f.get("floor_width", 8000.0)
    wall = f.get("wall_height", 6000.0)
    remaining = max(1.0, extent - fw / 2.0)
    ww = f.get("wall_width")
    span = max(1.0, min(float(ww), remaining)) if ww else remaining
    d = abs(perp) - fw / 2.0
    if d <= 0:
        base = 0.0
    else:
        t = _clamp01(d / span)
        base = wall * t * t
    rough = f.get("roughness", 0.0)
    if rough:
        base += wall * rough * 0.15 * _fbm(lx / 2500.0, ly / 2500.0, f.get("seed", 7), 3)
    return base


def _radial(lx, ly, f):
    """Smooth radial bump (hill). Optional `axis`+`length` stretches it into a ridge."""
    ax, ay = f.get("at", [0, 0])
    r = f.get("radius", 3000.0)
    height = f.get("height", 2000.0)
    length = f.get("length", 0.0)
    axis = f.get("axis", "x").lower()
    px, py = lx - ax, ly - ay
    if length:                                       # ridge: no falloff along the axis core
        if axis == "x":
            px = max(0.0, abs(px) - length / 2.0)
        else:
            py = max(0.0, abs(py) - length / 2.0)
    d = math.hypot(px, py)
    if d >= r:
        return 0.0
    return height * _smooth(1.0 - d / r)


def _override(h, lx, ly, f, extent, default_target):
    """Blend the running height toward a target inside a region, feathered over blend_margin
    at the edge. Backs both plateau (target = base+height) and flatten (target = a level)."""
    region = f.get("region")
    if region is None:                               # plateau shorthand: at+radius → circle
        region = {"kind": "circle", "at": f.get("at", [0, 0]), "radius": f.get("radius", 3000.0)}
    margin = f.get("blend_margin", 1500.0)
    inset = region_inset(lx, ly, region)
    if inset <= -margin:
        return h                                     # fully outside the feathered zone
    target = f.get("height", default_target)
    if f.get("kind") == "plateau":
        target = f.get("height", 2000.0)
    w = _clamp01((inset + margin) / max(1.0, margin)) if inset < margin else 1.0
    w = _smooth(w)
    return h * (1.0 - w) + target * w


def height_at(lx, ly, features, extent):
    """Terrain height (cm, relative to base) at a terrain-local point. `extent` = half of the
    terrain size on the shorter axis, used to normalise valley walls."""
    h = 0.0
    for f in features:
        k = f.get("kind")
        if k == "valley":
            h += _valley(lx, ly, f, extent)
        elif k in ("hill", "ridge"):
            h += _radial(lx, ly, f)
        elif k == "noise":
            h += f.get("amplitude", 300.0) * _fbm(
                lx / f.get("scale", 3000.0), ly / f.get("scale", 3000.0),
                f.get("seed", 1337), f.get("octaves", 3))
        elif k == "plateau":
            h = _override(h, lx, ly, f, extent, 0.0)
        elif k == "flatten":
            h = _override(h, lx, ly, f, extent, 0.0)
        else:
            raise ValueError(f"unknown landform kind '{k}'")
    return h
