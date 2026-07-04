"""Relational perception + placement — ported from blender-buttons, remapped to UE.

Ported from extension/queries.py + extension/placement.py. Two conventions differ and
EVERY axis/tolerance below reflects the remap (do not copy Blender values):

  * Units:  Blender metres → UE **centimetres**. Blender's _TOUCH 0.0005 m → 0.05 cm;
            its describe/align 1e-3 m → 0.1 cm.
  * Axes:   Blender front = −Y, right = +X.  UE front = **+X**, right = **+Y**, up +Z.
            So Blender's X-face (left/right) relations map to UE's **Y** faces, and
            Blender's Y-face (front/back) relations map to UE's **X** faces.

BasicShapes actors have a CENTERED pivot, so for an unrotated actor the actor location
== AABB center; a spawned primitive's placement coordinate IS its center. (Placing a NEW
primitive relative to a pre-existing non-centered-pivot actor is still fine — the
reference's world AABB comes from get_actor_bounds regardless of its pivot; see gaps.md
G4 for the transform-on-foreign-pivot caveat.)
"""
import math

from . import _ue

CONTACT = 0.1     # cm — face-contact / flush / rests-on tolerance (Blender 1e-3 m)
FINE = 0.05       # cm — gap "touching" tolerance (Blender _TOUCH 0.0005 m)

# Corner name → (x_side, y_side): -1 = min face, +1 = max face. UE: +X front, +Y right.
_CORNERS = {
    "front_right": (+1, +1), "front_left": (+1, -1),
    "back_right": (-1, +1), "back_left": (-1, -1),
}

_ADJ_ALIASES = {  # placement key aliases → canonical (ported, remapped names kept)
    "above": "on", "below": "under", "beneath": "under",
    "front": "in_front_of", "in_front": "in_front_of", "back": "behind",
    "left": "left_of", "right": "right_of",
}


def _half(actor):
    s = _ue.bounds(actor)["size"]
    return [s[0] / 2, s[1] / 2, s[2] / 2]


def _need(label):
    a = _ue.find_by_label(label)
    if a is None:
        raise ValueError(f"no actor labelled '{label}'")
    return a


# ── placement ─────────────────────────────────────────────────────────────────
def resolve_placement(actor, place):
    """Resolve a placement spec to the target's world center (cm). Returns [x,y,z].

    Whole-object (mutually exclusive): on | under | between | centered_on | at_corner.
    Adjacency (overrides x/y it sets): left_of | right_of | in_front_of | behind.
    Then: mirror_of(+axis), then on_floor (z override, applied last). `gap` (cm, default
    0) pushes farther apart (negative = overlap) for on/under/adjacency.

    Empty spec → rest on the floor at world origin.
    """
    place = {_ADJ_ALIASES.get(k, k): v for k, v in place.items()}
    if "at" in place:                       # raw-coords ripcord (documented escape hatch)
        return list(place["at"])

    w, d, h = _half(actor)                   # half extents of the object being placed
    gap = place.get("gap", 0.0)

    cx = cy = 0.0
    cz = h                                    # default: bottom on the floor at origin

    def ref_bounds(key):
        r = _need(place[key]) if isinstance(place[key], str) else None
        return _ue.bounds(r) if r else None

    if "on" in place:
        rb = ref_bounds("on")
        cx, cy = rb["center"][0], rb["center"][1]
        cz = rb["max"][2] + h + gap
    elif "under" in place:
        rb = ref_bounds("under")
        cx, cy = rb["center"][0], rb["center"][1]
        cz = rb["min"][2] - h - gap
    elif "between" in place:
        a, b = [_ue.bounds(_need(n)) for n in place["between"]]
        cx = (a["center"][0] + b["center"][0]) / 2
        cy = (a["center"][1] + b["center"][1]) / 2
        cz = (a["center"][2] + b["center"][2]) / 2
    elif "centered_on" in place:
        rb = ref_bounds("centered_on")
        cx, cy, cz = rb["center"]
    elif "at_corner" in place:
        spec = place["at_corner"]            # {of, corner, top(default true), inset}
        rb = _ue.bounds(_need(spec["of"]))
        corner = spec.get("corner")
        if corner not in _CORNERS:
            raise ValueError(f"unknown corner '{corner}'. known: {sorted(_CORNERS)}")
        sx, sy = _CORNERS[corner]
        inset = spec.get("inset", 0.0)
        cx = (rb["max"][0] if sx > 0 else rb["min"][0]) - sx * (w + inset)
        cy = (rb["max"][1] if sy > 0 else rb["min"][1]) - sy * (d + inset)
        if spec.get("under"):                # table-leg style: hang below the top
            cz = rb["min"][2] - h
        elif spec.get("top", True):
            cz = rb["max"][2] + h            # stand on top
        else:
            cz = rb["min"][2] + h            # sink to the shared floor

    elif "grid" in place:
        # G10: modular composition — span a fixed module from an anchor piece instead of
        # abutting face-to-face. cell counts modules along x/y (UE map axes); z stays level
        # with the anchor's centre so a wall ring shares its datum (combine with
        # {"ground": true} to reseat). The module is MEASURED (from the wall family), the
        # anchor is PERCEIVED — derived, not divined.
        spec = place["grid"]                 # {"anchor": label, "module": cm, "cell": [i, j]}
        rb = _ue.bounds(_need(spec["anchor"]))
        module = float(spec["module"])
        ci, cj = spec.get("cell", [0, 0])
        cx = rb["center"][0] + ci * module
        cy = rb["center"][1] + cj * module
        cz = rb["center"][2]

    # adjacency overrides the axis it controls (UE: left/right = Y, front/back = X)
    if "left_of" in place:
        rb = ref_bounds("left_of")
        cy = rb["min"][1] - d - gap; cx, cz = rb["center"][0], rb["center"][2]
    elif "right_of" in place:
        rb = ref_bounds("right_of")
        cy = rb["max"][1] + d + gap; cx, cz = rb["center"][0], rb["center"][2]
    elif "in_front_of" in place:
        rb = ref_bounds("in_front_of")
        cx = rb["max"][0] + w + gap; cy, cz = rb["center"][1], rb["center"][2]
    elif "behind" in place:
        rb = ref_bounds("behind")
        cx = rb["min"][0] - w - gap; cy, cz = rb["center"][1], rb["center"][2]

    if "along" in place:                     # a point offset to one side of a spline
        spec = place["along"]
        from . import spline as _splinemod
        pt, tan = _splinemod.point_and_tangent(spec["spline"], spec.get("fraction", 0.5))
        off = spec.get("offset", spec.get("offset_cm", 0.0))
        side = spec.get("side", "left")
        # left of travel = rotate the planar tangent +90° (N=+X up, E=+Y right on view(map))
        perp = (-tan[1], tan[0]) if side == "left" else (tan[1], -tan[0])
        cx = pt[0] + perp[0] * off
        cy = pt[1] + perp[1] * off
        cz = pt[2] + h                        # bottom sits on the draped spline height

    if "mirror_of" in place:                 # mirror about world origin on `axis`
        src = _ue.bounds(_need(place["mirror_of"]))["center"]
        axis = place.get("axis", "X").upper()
        cx, cy, cz = src
        if axis == "X": cx = -src[0]
        elif axis == "Y": cy = -src[1]
        elif axis == "Z": cz = -src[2]
        else: raise ValueError(f"mirror axis must be X/Y/Z, got '{axis}'")

    if place.get("on_floor"):                # relational datum, applied LAST
        cz = h

    return [cx, cy, cz]


# ── interior / enclosure sense (G49) ────────────────────────────────────────────
_BEARINGS = [("N", 0.0), ("NE", 45.0), ("E", 90.0), ("SE", 135.0),
             ("S", 180.0), ("SW", 225.0), ("W", 270.0), ("NW", 315.0)]


def clearance(p):
    """G49 — sense the negative space around a point: a ray fan from `at=[x,y,z]` reporting
    the distance to the floor (down), the ceiling (up), and a wall on each of eight compass
    bearings (horizontal), plus which rays escape to open sky. Numbers only — the way to
    'see' a cave's hollowness, whether an assembled chamber's lid leaks sky, and how much
    room a build has, without a screenshot (vision policy). range_cm caps each ray (default
    10000 = 100 m); a ray that hits nothing inside range is 'open' (sky leak / no wall)."""
    at = p.get("at")
    if not at or len(at) < 3:
        return {"error": "clearance needs at=[x,y,z] — a world point to probe from"}
    x, y, z = float(at[0]), float(at[1]), float(at[2])
    rng = float(p.get("range_cm") or 10000.0)
    origin = [x, y, z]

    def ray(dx, dy, dz):
        end = [x + dx * rng, y + dy * rng, z + dz * rng]
        hit = _ue.trace_hit(origin, end)
        if hit is None:
            return None
        return round(math.dist([hit.x, hit.y, hit.z], origin), 1)

    floor = ray(0.0, 0.0, -1.0)
    ceiling = ray(0.0, 0.0, 1.0)
    walls, open_bearings = {}, []
    for name, bearing in _BEARINGS:
        a = math.radians(bearing)               # compass: N=+X, clockwise, E=+Y
        d = ray(math.cos(a), math.sin(a), 0.0)
        walls[name] = d
        if d is None:
            open_bearings.append(name)
    hit_walls = {k: v for k, v in walls.items() if v is not None}
    nearest = min(hit_walls.items(), key=lambda kv: kv[1]) if hit_walls else None

    leaks = []
    if ceiling is None:
        leaks.append("overhead (no ceiling within range — open to sky)")
    if open_bearings:
        leaks.append(f"horizontally: {', '.join(open_bearings)} (no wall within range)")

    enclosed = ceiling is not None and not open_bearings and floor is not None
    if enclosed:
        verdict = "ENCLOSED — floor, ceiling, and a wall on every bearing within range"
    elif floor is None:
        verdict = "NO FLOOR beneath this point within range — is the point above the ground?"
    else:
        verdict = "OPEN — " + "; ".join(leaks)

    out = {"at": [round(x, 1), round(y, 1), round(z, 1)], "range_cm": rng,
           "floor_cm": floor, "ceiling_cm": ceiling, "walls_cm": walls,
           "open_bearings": open_bearings, "enclosed": enclosed, "verdict": verdict}
    if nearest:
        out["nearest_wall"] = {"bearing": nearest[0], "cm": nearest[1]}
    if floor is not None and ceiling is not None:
        out["headroom_cm"] = round(floor + ceiling, 1)   # floor-to-ceiling at this column
    if leaks:
        out["sky_leaks"] = leaks
    return out


# ── perception ────────────────────────────────────────────────────────────────
def feel(p):
    op = p.get("op", "describe")
    if op == "describe":
        return _describe(p.get("target"))
    if op == "distance_between":
        return _distance_between(p.get("a"), p.get("b"), p.get("axis", "ANY"))
    if op == "gap_between":
        return _gap_between(p.get("a"), p.get("b"))
    if op == "is_aligned":
        return _is_aligned(p.get("a"), p.get("b"), p.get("side", "CENTER_Z"),
                           p.get("tolerance", CONTACT))
    return {"error": f"unknown feel op '{op}'"}


def _ov(amin, amax, bmin, bmax):
    """Strict 1-D overlap (no tolerance) — matches blender-buttons describe."""
    return amin < bmax and amax > bmin


def _relations(a, b):
    """All relation strings from AABB a (me) to AABB b (other), UE axes. Ported from
    describe (queries.py): rests_on/under via Z-face + XY footprint overlap; flush via
    the two perpendicular overlaps + a shared face plane within CONTACT."""
    out = []
    ax_ov = _ov(a["min"][0], a["max"][0], b["min"][0], b["max"][0])
    ay_ov = _ov(a["min"][1], a["max"][1], b["min"][1], b["max"][1])
    az_ov = _ov(a["min"][2], a["max"][2], b["min"][2], b["max"][2])

    if ax_ov and ay_ov:
        if abs(a["min"][2] - b["max"][2]) < CONTACT:
            out.append("rests_on")
        elif abs(a["max"][2] - b["min"][2]) < CONTACT:
            out.append("directly_under")
    # left/right = Y faces (need X+Z overlap)
    if az_ov and ax_ov:
        if abs(a["max"][1] - b["min"][1]) < CONTACT:
            out.append("flush_left_of")
        elif abs(a["min"][1] - b["max"][1]) < CONTACT:
            out.append("flush_right_of")
    # front/back = X faces, +X front (need Y+Z overlap)
    if az_ov and ay_ov:
        if abs(a["min"][0] - b["max"][0]) < CONTACT:
            out.append("flush_in_front_of")
        elif abs(a["max"][0] - b["min"][0]) < CONTACT:
            out.append("flush_behind")
    return out


def _describe(label):
    a = _need(label)
    b = _ue.bounds(a)
    rel = []
    on_floor = abs(b["min"][2]) < CONTACT
    for other in _ue.ueb_actors():          # scope to our arrangement (gaps.md G7)
        if other == a:
            continue
        ob = _ue.bounds(other)
        if ob["size"] == [0, 0, 0]:
            continue
        rs = _relations(b, ob)
        if rs:
            rel.append({"actor": other.get_actor_label(), "relations": rs})
    return {"actor": label,
            "dims_cm": [round(v, 1) for v in b["size"]],
            "bounds": {k: [round(v, 1) for v in b[k]] for k in ("min", "max", "center")},
            "on_floor": on_floor,
            "relations": rel}


_GEO_NEAR_RANGE = 500.0    # refine with real geometry only at contact range (G5)
_GEO_TRI_CAP = 200_000     # skip the mesh path when a copy would be this heavy


def _geometry_nearest(actor_a, actor_b):
    """G5: true mesh-surface nearest distance via GeometryScript — copy both meshes to
    world-space DynamicMeshes, build BVHs, and run alternating nearest-point projection
    (seeded from the AABB centres; 4 rounds converge for anything box-ish and give a tight
    upper bound otherwise). Returns None when either actor has no mesh, a copy fails, or
    the meshes are too heavy to copy on the dispatch path."""
    import unreal
    meshes = []
    for actor in (actor_a, actor_b):
        comp = (actor.get_component_by_class(unreal.StaticMeshComponent)
                or actor.get_component_by_class(unreal.DynamicMeshComponent))
        if comp is None:
            return None
        sm = getattr(comp, "static_mesh", None)
        if sm is not None:
            try:
                if sm.get_num_triangles(0) > _GEO_TRI_CAP:
                    return None
            except Exception:
                pass
        dm = unreal.DynamicMesh()
        try:
            _, _, ok = unreal.GeometryScript_SceneUtils.copy_mesh_from_component(
                comp, dm, unreal.GeometryScriptCopyMeshFromComponentOptions(), True)
        except Exception:
            return None
        if ok != unreal.GeometryScriptOutcomePins.SUCCESS:
            return None
        if dm.get_triangle_count() > _GEO_TRI_CAP:
            return None
        _, bvh = unreal.GeometryScript_MeshSpatial.build_bvh_for_mesh(dm)
        meshes.append((dm, bvh))
    (dma, bva), (dmb, bvb) = meshes
    qo = unreal.GeometryScriptSpatialQueryOptions()

    def _nearest(dm, bvh, pt):
        _, hit, found = unreal.GeometryScript_MeshSpatial.find_nearest_point_on_mesh(
            dm, bvh, unreal.Vector(*pt), qo)
        if found != unreal.GeometryScriptSearchOutcomePins.FOUND:
            return None
        h = hit.get_editor_property("position")
        return [h.x, h.y, h.z]

    p = _nearest(dma, bva, _ue.bounds(actor_b)["center"])
    if p is None:
        return None
    q = None
    for _i in range(4):
        q = _nearest(dmb, bvb, p)
        if q is None:
            return None
        p2 = _nearest(dma, bva, q)
        if p2 is None:
            return None
        p = p2
    return {"distance_cm": round(math.dist(p, q), 2),
            "nearest_point_on_a": [round(v, 1) for v in p],
            "nearest_point_on_b": [round(v, 1) for v in q]}


def _distance_between(la, lb, axis):
    aa, ab = _need(la), _need(lb)
    a, b = _ue.bounds(aa), _ue.bounds(ab)
    axis = axis.upper()
    if axis in ("X", "Y", "Z"):
        i = "XYZ".index(axis)
        return {"a": la, "b": lb, "axis": axis, "measured": "centre-to-centre",
                "distance_cm": round(abs(a["center"][i] - b["center"][i]), 2)}
    # ANY: nearest-surface distance between the two world AABBs. Per axis the empty gap is
    # max(bmin−amax, amin−bmax, 0); the Euclidean length of those gaps is the closest
    # approach of the boxes (0 if they overlap) — exact for box footprints.
    gaps = [max(b["min"][i] - a["max"][i], a["min"][i] - b["max"][i], 0.0) for i in range(3)]
    surf = math.sqrt(sum(g * g for g in gaps))
    out = {"a": la, "b": lb, "axis": "ANY", "measured": "nearest-surface (AABB)",
           "distance_cm": round(surf, 2),
           "centre_to_centre_cm": round(math.dist(a["center"], b["center"]), 2)}
    # G5: at contact range the AABB answer over-reads a non-box mesh (a sphere's corner is
    # empty space) — refine against the real surfaces where it matters, keep both figures.
    if surf < _GEO_NEAR_RANGE:
        geo = _geometry_nearest(aa, ab)
        if geo is not None:
            out["aabb_distance_cm"] = out["distance_cm"]
            out["distance_cm"] = geo["distance_cm"]
            out["measured"] = "nearest-surface (mesh geometry, BVH)"
            out["nearest_point_on_a"] = geo["nearest_point_on_a"]
            out["nearest_point_on_b"] = geo["nearest_point_on_b"]
    return out


def _gap_between(la, lb):
    """Per-axis empty space between two AABBs (negative = overlap). Ported gap_between."""
    a, b = _ue.bounds(_need(la)), _ue.bounds(_need(lb))
    g = {}
    for i, ax in enumerate("xyz"):
        g[ax] = round(max(b["min"][i] - a["max"][i], a["min"][i] - b["max"][i]), 2)
    touching = [ax.upper() for ax in "xyz" if abs(g[ax]) < FINE]
    return {"a": la, "b": lb, "gap_cm": g, "touching_on_axes": touching}


# side → (a_scalar_fn, b_scalar_fn) picking the face/center to compare. UE axes.
def _side_scalars(a, b, side):
    S = side.upper()
    pick = {
        "TOP": (a["max"][2], b["max"][2]), "BOTTOM": (a["min"][2], b["min"][2]),
        "FRONT": (a["max"][0], b["max"][0]), "BACK": (a["min"][0], b["min"][0]),
        "RIGHT": (a["max"][1], b["max"][1]), "LEFT": (a["min"][1], b["min"][1]),
        "CENTER_X": (a["center"][0], b["center"][0]),
        "CENTER_Y": (a["center"][1], b["center"][1]),
        "CENTER_Z": (a["center"][2], b["center"][2]),
    }
    if S not in pick:
        raise ValueError(f"unknown side '{side}'. known: {sorted(pick)}")
    return pick[S]


def _is_aligned(la, lb, side, tol):
    a, b = _ue.bounds(_need(la)), _ue.bounds(_need(lb))
    va, vb = _side_scalars(a, b, side)
    return {"a": la, "b": lb, "side": side.upper(),
            "aligned": abs(va - vb) < tol,
            "difference_cm": round(va - vb, 2)}
