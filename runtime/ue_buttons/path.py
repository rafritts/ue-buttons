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
    fn = {"create": _create, "carve": _carve, "surface": _surface,
          "describe": _describe, "remove": _remove}.get(p.get("action", "create"))
    if fn is None:
        return {"error": f"unknown path action '{p.get('action')}'. known: "
                         "create|carve|surface|describe|remove"}
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
    label = p.get("label", "path")
    if label in _state.paths:
        return {"error": f"path '{label}' already exists (remove it first)"}
    points = _resolve_points(p)
    width = p.get("width", 300.0)
    draped, misses = _drape(points, width)
    poly, cum = _sample_polyline([[x, y] for x, y, _ in draped])
    _state.paths[label] = {"points": draped, "width": width,
                           "length_cm": round(cum[-1], 1),
                           "terrain": p.get("terrain", "terrain")}
    out = {"created": label, "waypoints": [[round(v, 1) for v in pt] for pt in draped],
           "length_cm": round(cum[-1], 1), "width_cm": width,
           "note": "z draped onto terrain by trace; view(map) shows the route"}
    if misses:
        out["notes"] = [f"{misses}/{len(draped)} waypoints traced NO ground — their z is a "
                        f"0.0 placeholder, not a surface (B3). Is the route on the terrain?"]
    return out


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
    """Flatten the terrain under the path: a chain of overlapping flatten features at grade,
    feathered to the width + margin — appended in ONE batch with ONE mesh rebuild. The first
    cut delegated disc-by-disc to landscape.flatten, which rebuilt the whole heightfield per
    disc (141 rebuilds ≈ the 30 s bridge blackout, bugs.md B6)."""
    from . import landscape
    landscape._hydrate()                          # carve reaches into landscape meta directly
    label = p.get("label", "path")
    path = _state.paths.get(label)
    if path is None:
        return {"error": f"no path labelled '{label}'"}
    terrain_label = p.get("terrain", path.get("terrain", "terrain"))
    meta = landscape._meta_of(terrain_label)
    actor = _ue.find_by_label(terrain_label)
    if meta is None or actor is None:
        return {"error": f"no terrain '{terrain_label}' to carve into"}
    poly, cum = _sample_polyline([[x, y] for x, y, _ in path["points"]])
    width = path["width"]
    margin = p.get("blend_margin", width)
    spacing = max(width / 2.0, 200.0)
    n = max(2, int(cum[-1] / spacing))
    # Sample every disc's target from the PRE-CARVE terrain up front. If we instead let each
    # flatten default to the running grade, overlapping discs would each read the previous
    # disc's flattened height and drag the whole bed to a near-constant level (the bug that
    # levelled a valley-spanning road). Fixing targets to the natural grade makes the bed
    # follow the terrain — level across the path, sloping along it. Coords/grades are in
    # terrain-LOCAL space off the EFFECTIVE origin (G26: composes a nudged actor transform).
    ox, oy, _oz = landscape._eff_origin(terrain_label, meta)
    extent = min(meta["size"]) / 2.0
    pre_feats = list(meta["features"])
    feats = []
    for i in range(n + 1):
        (x, y), _t = _point_at_fraction(poly, cum, i / n)
        lx, ly = x - ox, y - oy
        grade = terrain.height_at(lx, ly, pre_feats, extent)
        feats.append({"kind": "flatten", "height": grade, "blend_margin": margin,
                      "region": {"kind": "circle", "at": [lx, ly], "radius": width / 2.0}})
    meta["features"].extend(feats)
    verts = landscape._rebuild(actor, meta)
    landscape._save_meta()
    out = {"carved": label, "terrain": terrain_label, "discs": len(feats),
           "vertices": verts, "undoable": False,
           "note": "path bed flattened to natural grade along the route (one rebuild)"}
    if path.get("surface_actor"):
        # The strip was draped on the PRE-carve ground — rebuild it on the new bed.
        s = path.get("surface", {})
        res = _surface({"label": label, **s})
        out["surface_rebuilt"] = res.get("surfaced") or res.get("error")
    return out


def _surface(p):
    """Give the path a VISIBLE surface: a thin material ribbon draped onto the terrain
    (gaps.md G25 — a geometrically perfect carve reads as 'the tiniest of tiny lines'
    without a material to separate bed from grass). Builds a DynamicMesh strip from the
    spline: paired left/right vertices every ~half-width, each traced onto the real ground
    and lifted a few cm so the strip sits ON the bed rather than z-fighting it. Idempotent:
    re-running replaces the strip (so carve can rebuild it on the new grade)."""
    label = p.get("label", "path")
    path = _state.paths.get(label)
    if path is None:
        return {"error": f"no path labelled '{label}'"}
    material = p.get("material")
    mat_path = None
    if material:
        from . import landscape
        mat_path, err = landscape.resolve_material(material)
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
           "note": "ribbon draped on the traced ground; re-run after any later carve"}
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
    label = p.get("label", "path")
    path = _state.paths.pop(label, None)
    if path is None:
        return {"error": f"no path labelled '{label}'"}
    out = {"removed": label}
    strip = path.get("surface_actor")
    if strip:
        a = _ue.find_by_label(strip)
        if a is not None:
            _ue.actor_subsystem().destroy_actor(a)
            out["surface_removed"] = strip
    return out
