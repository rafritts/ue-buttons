"""`path` — splines as first-class intent (SPEC-01 E4).

A path IS a list of waypoints (the rare case where the UE primitive and intent space agree).
Modelled as a pure-Python Catmull-Rom spline over waypoints (G13: no editor SplineComponent
from script), stored in `_state.paths`. The agent thinks in 2D map positions; the runtime
drapes z onto the terrain by tracing, carves a bed, and answers position+tangent at any
fraction. Route form encodes "winding" naturally as a walk of bearings/turns.

Map positions (polar or absolute) resolve through `map_ref.resolve` — derived, not divined.
"""
import math

import unreal

from . import _state
from . import _ue
from . import map_ref
from . import terrain


# ── Catmull-Rom spline over waypoints (pure Python) ─────────────────────────────
def _catmull(p0, p1, p2, p3, t):
    t2 = t * t
    t3 = t2 * t
    return [
        0.5 * ((2 * p1[k]) + (-p0[k] + p2[k]) * t
               + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * t2
               + (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * t3)
        for k in range(2)]


def _sample_polyline(points, per_segment=16):
    """Sample the Catmull-Rom curve through `points` (list of [x,y]) into a dense polyline of
    [x,y] plus per-vertex cumulative arc length. Endpoints are duplicated for end tangents."""
    if len(points) < 2:
        return [list(p) for p in points], [0.0]
    pts = [points[0]] + [list(p) for p in points] + [points[-1]]
    poly = []
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i], pts[i + 1]  # placeholder, fixed below
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
        steps = per_segment if i < len(pts) - 3 else per_segment + 1
        for s in range(steps):
            poly.append(_catmull(p0, p1, p2, p3, s / per_segment))
    # cumulative arc length
    cum = [0.0]
    for a, b in zip(poly, poly[1:]):
        cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    return poly, cum


def _point_at_fraction(poly, cum, frac):
    """(x,y) and unit tangent (tx,ty) at arc-length fraction along the sampled polyline."""
    frac = max(0.0, min(1.0, frac))
    target = frac * cum[-1]
    i = 1
    while i < len(cum) - 1 and cum[i] < target:
        i += 1
    a, b = poly[i - 1], poly[i]
    seg = cum[i] - cum[i - 1]
    u = 0.0 if seg <= 0 else (target - cum[i - 1]) / seg
    x = a[0] + (b[0] - a[0]) * u
    y = a[1] + (b[1] - a[1]) * u
    tx, ty = b[0] - a[0], b[1] - a[1]
    n = math.hypot(tx, ty) or 1.0
    return [x, y], [tx / n, ty / n]


def point_and_tangent(label, fraction):
    """[x,y,z] and unit planar tangent at a fraction along a stored path. z is the stored
    draped value (interpolated). Used by map_ref anchors and the along=/facing= placement."""
    path = _state.paths.get(label)
    if path is None:
        raise ValueError(f"no path labelled '{label}'")
    pts2 = [[x, y] for x, y, _ in path["points"]]
    poly, cum = _sample_polyline(pts2)
    (x, y), tan = _point_at_fraction(poly, cum, fraction)
    # interpolate draped z from nearest waypoints by fraction of waypoint index
    zs = [z for _, _, z in path["points"]]
    fi = fraction * (len(zs) - 1)
    i0 = int(fi); i1 = min(i0 + 1, len(zs) - 1)
    z = zs[i0] + (zs[i1] - zs[i0]) * (fi - i0)
    return [x, y, z], tan


# ── actions ──────────────────────────────────────────────────────────────────────
def handle(p):
    fn = {"create": _create, "carve": _carve, "describe": _describe,
          "remove": _remove}.get(p.get("action", "create"))
    if fn is None:
        return {"error": f"unknown path action '{p.get('action')}'. known: "
                         "create|carve|describe|remove"}
    return fn(p)


def _resolve_points(p):
    """Resolve either points=[map positions] or route={start, steps} to a list of [x,y]."""
    if p.get("route"):
        return _walk_route(p["route"])
    pts = p.get("points")
    if not pts:
        raise ValueError("path create needs points=[...] or route={start, steps}")
    return [map_ref.resolve(pt) for pt in pts]


def _walk_route(route):
    """Walk a route: start point, then steps of {bearing,distance} (absolute compass) or
    {turn,distance} (relative to current heading). Returns resolved [x,y] waypoints and
    reports them so the agent knows exactly where the chain ended up (no dead reckoning)."""
    pos = map_ref.resolve(route["start"])
    heading = route.get("start_bearing", 0.0)     # compass deg, north=+X
    out = [list(pos)]
    for step in route.get("steps", []):
        if "bearing" in step:
            heading = step["bearing"]
        elif "turn" in step:
            heading += step["turn"]
        dist = step["distance"]
        rad = math.radians(heading)
        pos = [pos[0] + dist * math.cos(rad), pos[1] + dist * math.sin(rad)]  # N=+X, E=+Y
        out.append(list(pos))
    return out


def _drape(points, width):
    """Trace each waypoint onto the terrain for z; store draped [x,y,z] + planar tangents."""
    draped = []
    for x, y in points:
        z = _ue.trace_ground(x, y)
        draped.append([x, y, z if z is not None else 0.0])
    return draped


def _create(p):
    label = p.get("label", "path")
    if label in _state.paths:
        return {"error": f"path '{label}' already exists (remove it first)"}
    points = _resolve_points(p)
    width = p.get("width", 300.0)
    draped = _drape(points, width)
    poly, cum = _sample_polyline([[x, y] for x, y, _ in draped])
    _state.paths[label] = {"points": draped, "width": width,
                           "length_cm": round(cum[-1], 1)}
    return {"created": label, "waypoints": [[round(v, 1) for v in pt] for pt in draped],
            "length_cm": round(cum[-1], 1), "width_cm": width,
            "note": "z draped onto terrain by trace; view(map) shows the route"}


def _describe(p):
    label = p.get("label", "path")
    path = _state.paths.get(label)
    if path is None:
        return {"error": f"no path labelled '{label}'"}
    poly, cum = _sample_polyline([[x, y] for x, y, _ in path["points"]])
    out = {"label": label, "waypoint_count": len(path["points"]),
           "length_cm": round(cum[-1], 1), "width_cm": path["width"],
           "waypoints": [[round(v, 1) for v in pt] for pt in path["points"]]}
    if "at_fraction" in p:
        (x, y), (tx, ty) = _point_at_fraction(poly, cum, p["at_fraction"])
        z = _ue.trace_ground(x, y)
        bearing = (math.degrees(math.atan2(ty, tx))) % 360.0   # compass: atan2(east,north)
        out["at"] = {"fraction": p["at_fraction"], "point": [round(x, 1), round(y, 1),
                     round(z, 1) if z is not None else None],
                     "tangent": [round(tx, 3), round(ty, 3)], "bearing_deg": round(bearing, 1)}
    return out


def _carve(p):
    """Flatten/smooth the terrain under the path — delegate to landscape.flatten along the
    spline: a chain of overlapping flatten regions at grade, feathered to the width + margin."""
    from . import landscape
    landscape._hydrate()                          # carve reaches into landscape meta directly
    label = p.get("label", "path")
    path = _state.paths.get(label)
    if path is None:
        return {"error": f"no path labelled '{label}'"}
    terrain_label = p.get("terrain", "terrain")
    if landscape._meta_of(terrain_label) is None:
        return {"error": f"no terrain '{terrain_label}' to carve into"}
    poly, cum = _sample_polyline([[x, y] for x, y, _ in path["points"]])
    width = path["width"]
    margin = p.get("blend_margin", width)
    spacing = max(width / 2.0, 200.0)
    n = max(2, int(cum[-1] / spacing))
    meta = landscape._meta_of(terrain_label)
    # Sample every disc's target from the PRE-CARVE terrain up front. If we instead let each
    # flatten default to the running grade, overlapping discs would each read the previous
    # disc's flattened height and drag the whole bed to a near-constant level (the bug that
    # levelled a valley-spanning road). Fixing targets to the natural grade makes the bed
    # follow the terrain — level across the path, sloping along it.
    ox, oy, _oz = meta["origin"]
    extent = min(meta["size"]) / 2.0
    pre_feats = list(meta["features"])
    discs = []
    for i in range(n + 1):
        (x, y), _t = _point_at_fraction(poly, cum, i / n)
        grade = terrain.height_at(x - ox, y - oy, pre_feats, extent)
        discs.append((x, y, grade))
    for x, y, grade in discs:
        landscape.handle({"action": "flatten", "label": terrain_label, "height": grade,
                          "region": {"kind": "circle", "at": [x, y], "radius": width / 2.0},
                          "blend_margin": margin})
    return {"carved": label, "terrain": terrain_label, "discs": len(discs),
            "undoable": False, "note": "path bed flattened to natural grade along the route"}


def _remove(p):
    label = p.get("label", "path")
    if _state.paths.pop(label, None) is None:
        return {"error": f"no path labelled '{label}'"}
    return {"removed": label}
