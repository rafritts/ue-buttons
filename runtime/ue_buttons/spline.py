"""`spline` — routes as first-class intent (SPEC-01 E4; SPEC-05 rename of `path`).

A spline IS a list of waypoints — the UE construct is SplineComponent, though 5.8 blocks
adding one from Python (G13), so the curve is a pure-Python Catmull-Rom spline over
waypoints, stored in `_state.splines`. The agent thinks in 2D map positions; the runtime
drapes z onto the terrain by tracing and answers position+tangent at any fraction. Route
form encodes "winding" naturally as a walk of bearings/turns. Carving the terrain along a
spline lives on `terrain op=carve` — the op belongs to the thing it mutates (SPEC-05).

Map positions (polar or absolute) resolve through `map_ref.resolve` — derived, not divined.
"""
import math

import unreal

from . import _state
from . import _ue
from . import map_ref



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
    """[x,y,z] and unit planar tangent at a fraction along a stored spline. z is the stored
    draped value (interpolated). Used by map_ref anchors and the along=/facing= placement."""
    path = _state.splines.get(label)
    if path is None:
        raise ValueError(f"no spline labelled '{label}'")
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
    op = p.get("op", "create")
    if op == "carve":
        return {"error": "carve moved to the verb that mutates the terrain — use "
                         "terrain op=carve along=<spline label> [blend_margin=]"}
    fn = {"create": _create, "surface": _surface,
          "describe": _describe, "remove": _remove}.get(op)
    if fn is None:
        return {"error": f"unknown spline op '{op}'. known: "
                         "create|surface|describe|remove"}
    return fn(p)


def _resolve_points(p):
    """Resolve either points=[map positions] or route={start, steps} to a list of [x,y]."""
    if p.get("route"):
        return _walk_route(p["route"])
    pts = p.get("points")
    if not pts:
        raise ValueError("spline create needs points=[...] or route={start, steps}")
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
    """Trace each waypoint onto the terrain for z. A miss is COUNTED, never silently
    written as a real height (B3: four quiet z=0.0s became a baked-in causeway) — the
    0.0 placeholder still fills the slot, but the caller warns with the miss count."""
    draped, misses = [], 0
    for x, y in points:
        z = _ue.trace_ground(x, y)
        if z is None:
            misses += 1
        draped.append([x, y, z if z is not None else 0.0])
    return draped, misses


def _create(p):
    label = p.get("label", "spline")
    if label in _state.splines:
        return {"error": f"spline '{label}' already exists (remove it first)"}
    points = _resolve_points(p)
    width = p.get("width", 300.0)
    draped, misses = _drape(points, width)
    poly, cum = _sample_polyline([[x, y] for x, y, _ in draped])
    _state.splines[label] = {"points": draped, "width": width,
                           "length_cm": round(cum[-1], 1),
                           "terrain": p.get("terrain", "terrain")}
    out = {"created": label, "waypoints": [[round(v, 1) for v in pt] for pt in draped],
           "length_cm": round(cum[-1], 1), "width_cm": width,
           "note": "z draped onto terrain by trace; spline op=describe returns the waypoints"}
    if misses:
        out["notes"] = [f"{misses}/{len(draped)} waypoints traced NO ground — their z is a "
                        f"0.0 placeholder, not a surface (B3). Is the route on the terrain?"]
    return out


def _describe(p):
    label = p.get("label", "spline")
    path = _state.splines.get(label)
    if path is None:
        return {"error": f"no spline labelled '{label}'"}
    poly, cum = _sample_polyline([[x, y] for x, y, _ in path["points"]])
    out = {"label": label, "waypoint_count": len(path["points"]),
           "length_cm": round(cum[-1], 1), "width_cm": path["width"],
           "waypoints": [[round(v, 1) for v in pt] for pt in path["points"]]}
    grade = _grade_profile(path["points"])
    if grade:
        out["grade"] = grade
        if grade["max_pct"] > 20.0:
            out.setdefault("notes", []).append(
                f"max grade {grade['max_pct']}% at fraction {grade['max_at_fraction']} — "
                f"steeper than a walkable trail (~15–20% is scrambling territory); "
                f"terrain op=carve re-grades the bed, or reroute the steep segment")
    if "at_fraction" in p:
        (x, y), (tx, ty) = _point_at_fraction(poly, cum, p["at_fraction"])
        z = _ue.trace_ground(x, y)
        bearing = (math.degrees(math.atan2(ty, tx))) % 360.0   # compass: atan2(east,north)
        out["at"] = {"fraction": p["at_fraction"], "point": [round(x, 1), round(y, 1),
                     round(z, 1) if z is not None else None],
                     "tangent": [round(tx, 3), round(ty, 3)], "bearing_deg": round(bearing, 1)}
    return out


def _grade_profile(points):
    """G45: slope-along-route as numbers — per-segment grade % from LIVE ground traces at
    the waypoints (post-carve reality, not the creation-time z), plus avg/max and where the
    max sits. Playtest FEEL stays the human's; steepness is an instrument. Segments whose
    trace misses are skipped (a 0.0 placeholder would fabricate a cliff, B3's lesson)."""
    traced = []
    for x, y, _ in points:
        z = _ue.trace_ground(x, y)
        traced.append([x, y, z])
    grades = []
    for i in range(1, len(traced)):
        if traced[i][2] is None or traced[i - 1][2] is None:
            continue
        run = math.hypot(traced[i][0] - traced[i - 1][0], traced[i][1] - traced[i - 1][1])
        if run < 1.0:
            continue
        grades.append((abs(traced[i][2] - traced[i - 1][2]) / run * 100.0, i))
    if not grades:
        return None
    mx, mi = max(grades)
    return {"avg_pct": round(sum(g for g, _ in grades) / len(grades), 1),
            "max_pct": round(mx, 1),
            "max_at_fraction": round((mi - 0.5) / (len(traced) - 1), 2),
            "per_segment_pct": [round(g, 1) for g, _ in grades],
            "source": "live ground traces at the waypoints"}


def _surface(p):
    """Give the path a VISIBLE surface: a thin material ribbon draped onto the terrain
    (gaps.md G25 — a geometrically perfect carve reads as 'the tiniest of tiny lines'
    without a material to separate bed from grass). Builds a DynamicMesh strip from the
    spline: paired left/right vertices every ~half-width, each traced onto the real ground
    and lifted a few cm so the strip sits ON the bed rather than z-fighting it. Idempotent:
    re-running replaces the strip (so carve can rebuild it on the new grade)."""
    label = p.get("label", "spline")
    path = _state.splines.get(label)
    if path is None:
        return {"error": f"no spline labelled '{label}'"}
    material = p.get("material")
    mat_path = None
    if material:
        from . import terrain
        mat_path, err = terrain.resolve_material(material)
        if err:
            return {"error": err}
    elif path.get("surface", {}).get("material"):
        mat_path = path["surface"]["material"]
    width = float(p.get("width", path["width"]))
    lift = float(p.get("lift", 5.0))    # 5 cm default: crest guards catch edge-scale bumps,
                                        # the lift swallows the sub-edge residue (G34)
    tile = float(p.get("tile", 400.0))              # UV tiling: one texture repeat per `tile` cm
    strip_label = path.get("surface_actor", f"{label}_surface")

    poly, cum = _sample_polyline([[x, y] for x, y, _ in path["points"]])
    spacing = max(width / 2.0, 150.0)
    n = max(2, int(cum[-1] / spacing))
    old = _ue.find_by_label(strip_label)
    misses = 0
    zs_by_frac = [z for _, _, z in path["points"]]

    def _draped_z(frac):
        fi = frac * (len(zs_by_frac) - 1)
        i0 = int(fi); i1 = min(i0 + 1, len(zs_by_frac) - 1)
        return zs_by_frac[i0] + (zs_by_frac[i1] - zs_by_frac[i0]) * (fi - i0)

    # pass 1: rows of THREE columns (left edge, centreline, right edge). With only two
    # verts across, a ground crest under the strip's middle cannot be represented at all —
    # the quad renders its corners' bilinear while the bed crowns through it (G34's actual
    # geometry, found by the mid-span census: every worst poke sat at lateral 0.5).
    offs = [width / 2.0, 0.0, -width / 2.0]
    pos, grounds = [], []                            # pos[i] = [(x,y) L, C, R]
    for i in range(n + 1):
        (x, y), (tx, ty) = _point_at_fraction(poly, cum, i / n)
        nx, ny = -ty, tx                            # planar left normal
        row_p, row_g = [], []
        for off in offs:
            vx, vy = x + nx * off, y + ny * off
            z = _ue.trace_ground(vx, vy, ignore=old)
            if z is None:                            # fall back to the draped waypoint z
                misses += 1
                z = _draped_z(i / n)
            row_p.append((vx, vy)); row_g.append(z)
        pos.append(row_p); grounds.append(row_g)
    # pass 2 (G34): the ground can also crest BETWEEN adjacent verts. Trace every mesh
    # edge's midpoint — longitudinal per column and lateral per row — against the linear
    # interpolation that edge will render, and raise both endpoints by the CONVEX excess
    # only (a uniform slope has zero excess, so grades never inflate the lift; only
    # genuine bumps push the strip up).
    raise_by = [[0.0, 0.0, 0.0] for _ in range(n + 1)]
    guards = [0]
    def _guard(ia, ca, ib, cb):
        (ax, ay), (bx, by) = pos[ia][ca], pos[ib][cb]
        g = _ue.trace_ground((ax + bx) / 2.0, (ay + by) / 2.0, ignore=old)
        if g is None:
            return
        excess = g - (grounds[ia][ca] + grounds[ib][cb]) / 2.0
        if excess > 0.5:                             # ignore trace noise
            raise_by[ia][ca] = max(raise_by[ia][ca], excess)
            raise_by[ib][cb] = max(raise_by[ib][cb], excess)
            guards[0] += 1
    for i in range(n + 1):
        _guard(i, 0, i, 1); _guard(i, 1, i, 2)       # lateral
    for c in (0, 1, 2):
        for i in range(n):
            _guard(i, c, i + 1, c)                   # longitudinal
    crest_guards = guards[0]
    verts, uvs = [], []
    for i in range(n + 1):
        along = (i / n) * cum[-1]
        for c in (0, 1, 2):
            vx, vy = pos[i][c]
            verts.append(unreal.Vector(vx, vy, grounds[i][c] + raise_by[i][c] + lift))
            uvs.append(unreal.Vector2D((width / tile) * (c / 2.0), along / tile))
    tris = []
    for i in range(n):
        for c in (0, 1):
            a = 3 * i + c                            # sub-quad (a, a+1, a+3, a+4)
            b = a + 3
            # Both windings per quad: the strip must read from above AND below regardless
            # of the engine's facing convention — it's a 2D ribbon, not a solid.
            tris += [unreal.IntVector(a, b, a + 1), unreal.IntVector(a + 1, b, b + 1),
                     unreal.IntVector(a, a + 1, b), unreal.IntVector(a + 1, b + 1, b)]

    if old is not None:
        _ue.actor_subsystem().destroy_actor(old)
    actor = _ue.actor_subsystem().spawn_actor_from_class(
        unreal.DynamicMeshActor, unreal.Vector(0.0, 0.0, 0.0))
    actor.set_actor_label(strip_label)
    actor.tags = [unreal.Name(_ue.UEB_TAG)]
    comp = actor.get_dynamic_mesh_component()
    mesh = comp.get_dynamic_mesh()
    mesh.reset()
    buf = unreal.GeometryScriptSimpleMeshBuffers()
    buf.set_editor_property("vertices", verts)
    buf.set_editor_property("triangles", tris)
    buf.set_editor_property("uv0", uvs)
    unreal.GeometryScript_MeshEdits.append_buffers_to_mesh(mesh, buf)
    # complex-as-simple so the pawn walks ON the strip instead of falling through it
    # (same PIE trap as the terrain — see landscape._rebuild)
    comp.set_editor_property("enable_complex_collision", True)
    comp.set_editor_property("collision_type",
                             unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE)
    comp.set_dynamic_mesh(mesh)
    comp.set_collision_enabled(unreal.CollisionEnabled.QUERY_AND_PHYSICS)
    if mat_path:
        m = _ue.load_asset(mat_path)
        if m is not None:
            comp.set_material(0, m)
    path["surface_actor"] = strip_label
    path["surface"] = {"material": mat_path, "lift": lift, "width": width, "tile": tile}
    out = {"surfaced": label, "actor": strip_label, "material": mat_path,
           "vertices": len(verts), "width_cm": width, "lift_cm": lift, "undoable": False,
           "note": "ribbon draped on the traced ground; terrain op=carve re-drapes it automatically"}
    if not mat_path:
        out["notes"] = ["no material given — the strip renders with the engine default "
                        "(flat grey); pass material=<name|/Game path> "
                        "(asset find kind=material to browse)"]
    if crest_guards:
        out["crest_guards"] = crest_guards           # mid-span crests the strip was raised over (G34)
    if misses:
        out.setdefault("notes", []).append(
            f"{misses}/{len(verts)} strip vertices traced no ground — used draped path z")
    return out


def _remove(p):
    label = p.get("label", "spline")
    path = _state.splines.pop(label, None)
    if path is None:
        return {"error": f"no spline labelled '{label}'"}
    out = {"removed": label}
    strip = path.get("surface_actor")
    if strip:
        a = _ue.find_by_label(strip)
        if a is not None:
            _ue.actor_subsystem().destroy_actor(a)
            out["surface_removed"] = strip
    return out
