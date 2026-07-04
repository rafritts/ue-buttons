"""`terrain` — terrain as a heightfield (SPEC-01 E3; SPEC-05 rename of `landscape`).

MACRO ≈ UE Landscape — the name UE uses is deliberately NOT worn: 5.8's Landscape API is
unscriptable from Python, so this is StaticMesh(DynamicMesh) terrain with no layers, no
grass types, and the real name is reserved for the real system if Python ever authors it.

The agent describes landforms; the runtime synthesises the heightmap. It never hand-writes
height arrays over the wire. The mesh is displaced by the pure-Python `heightfield.height_at`.
Because that same function backs `describe` sampling, sampled heights agree with world traces.

Undo honesty (SPEC-01): DynamicMesh shaping does not sit in the editor transaction stack, so
these ops report `undoable: false` and are NOT logged to the 1:1 history — teardown is the
`remove` op (or editor delete), not `history op=undo_to`. Lying about undo is worse than a
documented gap.
"""
import json
import os

import unreal

from . import _state
from . import _ue
from . import heightfield

DEFAULT_CELL_CM = 200.0     # target grid resolution: one vertex row every ~2 m
MAX_STEPS = 220             # cap grid density so a shape stays a single snappy RC call
DEFAULT_UV_TILE_CM = 400.0  # ground texture repeat: one UV tile every 4 m (G33)
_META_NAME = "ueb_terrains.json"
_OLD_META_NAME = "ueb_landscapes.json"   # pre-SPEC-05 file; renamed on first hydrate


# ── persistence (survives editor restart; the hamlet is rebuilt from calls, but describe
#    wants the feature list back after a relaunch) ─────────────────────────────────────────
def _meta_path():
    saved = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_saved_dir())
    return os.path.normpath(os.path.join(saved, _META_NAME))


def _save_meta(prune=None):
    """MERGE _state.terrains into the on-disk meta — the file is shared across levels,
    and with SPEC-04's new/open/clear in play a flat dump from level B would silently
    destroy level A's persisted heightfields. prune=[labels] deletes entries (terrain
    removed / level cleared); stale disk entries are otherwise harmless — _hydrate only
    adopts a label whose actor exists in the loaded level."""
    try:
        disk = {}
        if os.path.exists(_meta_path()):
            with open(_meta_path()) as f:
                disk = json.load(f)
    except Exception:
        disk = {}
    disk.update(_state.terrains)
    for label in (prune or []):
        disk.pop(label, None)
    try:
        with open(_meta_path(), "w") as f:
            json.dump(disk, f)
    except Exception:
        pass


def _hydrate():
    """Load terrain meta from disk once per session, but only for terrains whose actor still
    exists in the level — so describe/flatten survive an editor restart or a runtime
    reimport (which resets _state). Guarded by a flag so it runs once."""
    if _state.terrains:
        return
    path = _meta_path()
    if not os.path.exists(path):
        # one-time migration: adopt the pre-SPEC-05 meta file so existing levels'
        # terrains survive the rename (the old name dies here, not a compat path)
        legacy = os.path.join(os.path.dirname(path), _OLD_META_NAME)
        if os.path.exists(legacy):
            os.rename(legacy, path)
        else:
            return
    if not os.path.exists(path):
        return
    try:
        with open(path) as f:
            disk = json.load(f)
    except Exception:
        return
    for label, meta in disk.items():
        if _ue.find_by_label(label) is not None:
            _state.terrains[label] = meta
    # G37: the editor-side hide is per-session — reassert it when terrains rehydrate
    # after an editor restart / runtime reimport.
    if _state.terrains:
        set_template_hidden(True)


# ── engine template ground (G37) ──────────────────────────────────────────────────
def set_template_hidden(hidden):
    """Hide/show the engine template's z=0 ground plane (Landscape tree + WP HLOD
    proxies). Traces already ignore it while a ueb terrain exists, but it still RENDERS —
    poking up through any floor dip below z=0, or stretching beyond a raised terrain's
    edge. Pure visual noise, so it goes dark with the first ueb terrain and comes back
    when the last one is removed. Hidden in BOTH editor and game: the editor flag is
    per-session (reapplied by _hydrate after a restart); the game flag saves with the
    level so PIE agrees."""
    n = 0
    for a in _ue.engine_landscape_actors():
        try:
            a.set_is_temporarily_hidden_in_editor(hidden)
            a.set_actor_hidden_in_game(hidden)
            n += 1
        except Exception:
            pass
    return n


def template_hidden():
    """Is the engine template ground currently hidden (editor-side)?"""
    proxies = _ue.engine_landscape_actors()
    return bool(proxies) and all(a.is_temporarily_hidden_in_editor() for a in proxies)


# ── mesh build ───────────────────────────────────────────────────────────────────
def _steps_for(size):
    return [max(2, min(MAX_STEPS, int(round(size[0] / DEFAULT_CELL_CM)))),
            max(2, min(MAX_STEPS, int(round(size[1] / DEFAULT_CELL_CM))))]


def _rebuild(actor, meta):
    """(Re)synthesise the terrain mesh from meta['features'] and give it complex collision so
    world traces (ground-snap, scatter, path drape) hit the real surface."""
    comp = actor.get_dynamic_mesh_component()
    mesh = comp.get_dynamic_mesh()
    mesh.reset()
    size = meta["size"]
    sx, sy = meta["resolution"]
    unreal.GeometryScript_Primitives.append_rectangle_xy(
        mesh, unreal.GeometryScriptPrimitiveOptions(), unreal.Transform(),
        float(size[0]), float(size[1]), sx, sy)
    mesh, vlist, _gaps = unreal.GeometryScript_MeshQueries.get_all_vertex_positions(mesh, False)
    positions = unreal.GeometryScript_List.convert_vector_list_to_array(vlist)
    extent = min(size[0], size[1]) / 2.0
    base = meta["base_height"]
    feats = meta["features"]
    disp = [unreal.Vector(0.0, 0.0, base + heightfield.height_at(p.x, p.y, feats, extent))
            for p in positions]
    dlist = unreal.GeometryScript_List.convert_array_to_vector_list(disp)
    unreal.GeometryScript_MeshDeformers.apply_displace_from_per_vertex_vectors(
        mesh, unreal.GeometryScriptMeshSelection(), dlist, 1.0)
    # G33: the rectangle's default UVs stretch 0..1 over the WHOLE terrain, so a 2 m
    # tiling ground texture smears across 300 m. Re-project planar top-down at a real
    # texel density: one UV repeat per uv_tile_cm (measured: 1 repeat = scale3d cm).
    tile = float(meta.get("uv_tile_cm") or DEFAULT_UV_TILE_CM)
    uv_xf = unreal.Transform()
    uv_xf.scale3d = unreal.Vector(tile, tile, 1.0)
    unreal.GeometryScript_UVs.set_mesh_u_vs_from_planar_projection(
        mesh, 0, uv_xf, unreal.GeometryScriptMeshSelection())
    comp.set_editor_property("enable_complex_collision", True)
    # A DynamicMesh has no simple collision shapes; without complex-as-simple the pawn's
    # physics sweeps find nothing and fall straight through in PIE (editor traces passed
    # trace_complex=True, which is why every mechanical read still said "solid").
    comp.set_editor_property("collision_type",
                             unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE)
    comp.set_dynamic_mesh(mesh)
    comp.set_collision_enabled(unreal.CollisionEnabled.QUERY_AND_PHYSICS)
    mat_path = meta.get("material")
    if mat_path:                                    # G25: an assigned material survives rebuilds
        m = _ue.load_asset(mat_path)
        if m is not None:
            comp.set_material(0, m)
    return len(positions)


def resolve_material(q):
    """A material asset path from a short name or full path (G25). Returns (path, error)."""
    if q.startswith("/Game") or q.startswith("/Engine"):
        return q, None
    from . import asset
    path, cands = asset._resolve_asset_path(
        q, classes=["Material", "MaterialInstanceConstant"])
    if path is not None:
        return path, None
    if not cands:
        return None, f"no material matches '{q}' (asset find kind=material to browse)"
    return None, f"material '{q}' is ambiguous — candidates: {cands[:10]}"


def _set_material(meta, p):
    """Stash a requested material on the meta (applied by _rebuild). Returns error or None."""
    q = p.get("material")
    if not q:
        return None
    path, err = resolve_material(q)
    if err:
        return err
    meta["material"] = path
    return None


def _set_uv_tile(meta, p):
    """Stash a requested UV tile (cm per texture repeat) on the meta (applied by _rebuild)."""
    if p.get("uv_tile_cm"):
        meta["uv_tile_cm"] = float(p["uv_tile_cm"])


def _eff_origin(label, meta):
    """The terrain's EFFECTIVE map origin: authored origin composed with the actor's live
    transform (G26 — a `transform nudge` moves the mesh; the meta origin doesn't follow).
    Every model-side answer (describe, samples, map grid, carve grades) derives from this,
    so a moved terrain never permanently 'diverges' from its own model."""
    ox, oy, oz = meta["origin"]
    a = _ue.find_by_label(label)
    if a is None:
        return [ox, oy, oz]
    loc = a.get_actor_location()
    spawn = meta["origin"]
    return [ox + (loc.x - spawn[0]), oy + (loc.y - spawn[1]), oz + (loc.z - spawn[2])]


# ── actions ──────────────────────────────────────────────────────────────────────
def handle(p):
    _hydrate()
    op = p.get("op", "create")
    fn = {"create": _create, "shape": _shape, "flatten": _flatten, "carve": _carve,
          "describe": _describe, "remove": _remove}.get(op)
    if fn is None:
        return {"error": f"unknown terrain op '{op}'. known: "
                         "create|shape|flatten|carve|describe|remove"}
    return fn(p)


def _meta_of(label):
    return _state.terrains.get(label)


def _create(p):
    """New flat terrain sized to the request, centred on `origin` (a map point, default map
    centre). size=[x_cm, y_cm]; the hamlet wants ~20000×20000 (200 m)."""
    label = p.get("label", "terrain")
    if _ue.find_by_label(label) is not None:
        return {"error": f"label '{label}' already exists (terrain op=remove label="
                         f"'{label}' to rebuild from scratch — G24)"}
    size = p.get("size", [20000.0, 20000.0])
    origin = p.get("origin", [0.0, 0.0, 0.0])
    if len(origin) == 2:
        origin = [origin[0], origin[1], 0.0]
    meta = {"origin": origin, "size": size, "base_height": p.get("base_height", 0.0),
            "resolution": p.get("resolution") or _steps_for(size), "features": []}
    err = _set_material(meta, p)
    if err:
        return {"error": err}
    _set_uv_tile(meta, p)
    actor = _ue.actor_subsystem().spawn_actor_from_class(
        unreal.DynamicMeshActor, unreal.Vector(*origin))
    actor.set_actor_label(label)
    actor.tags = [unreal.Name(_ue.UEB_TAG)]
    verts = _rebuild(actor, meta)
    _state.terrains[label] = meta
    _save_meta()
    _state.engine_grounds_memo = None    # ground attribution changed (B3/G22)
    out = {"created": label, "size_cm": size, "origin": origin,
           "resolution": meta["resolution"], "vertices": verts, "undoable": False}
    hidden = set_template_hidden(True)          # G37: this terrain IS the ground now
    if hidden:
        out["template_ground"] = (f"hid {hidden} engine template Landscape actor(s) — "
                                  "your terrain is the only ground that renders (G37); "
                                  "restored when the last ueb terrain is removed")
    if meta.get("material"):
        out["material"] = meta["material"]
    return out


def _remove(p):
    """Tear down a terrain: destroy the actor, drop the meta (G24 — terrain lifecycle).
    Splines carved into it become orphans; `outliner op=reconcile` GCs them."""
    label = p.get("label", "terrain")
    meta = _meta_of(label)
    actor = _ue.find_by_label(label)
    if meta is None and actor is None:
        return {"error": f"no terrain labelled '{label}'"}
    if actor is not None:
        _ue.actor_subsystem().destroy_actor(actor)
    _state.terrains.pop(label, None)
    _save_meta(prune=[label])
    _state.engine_grounds_memo = None    # ground attribution changed (B3/G22)
    dependents = [sl for sl, sd in _state.splines.items()
                  if sd.get("terrain", "terrain") == label]
    out = {"removed": label, "undoable": False}
    if not _state.terrains:                   # G37: last terrain gone → template returns
        shown = set_template_hidden(False)
        if shown:
            out["template_ground"] = (f"restored {shown} engine template Landscape "
                                      "actor(s) — with no ueb terrain it is the ground again")
    if dependents:
        out["notes"] = [f"splines {dependents} referenced this terrain — outliner op=reconcile "
                        f"to GC them (or spline op=remove each)"]
    return out


def _shape(p):
    """Apply declarative landform features onto the terrain, composed in order. Features:
      {"kind":"valley","axis":"x|y","floor_width":cm,"wall_height":cm,"roughness":0..1}
      {"kind":"hill"|"ridge","at":[x,y],"radius":cm,"height":cm,"length":cm,"axis":"x|y"}
      {"kind":"noise","amplitude":cm,"scale":cm,"octaves":n,"seed":n}
      {"kind":"plateau","at":[x,y],"radius":cm,"height":cm,"blend_margin":cm}
    `at`/coords are MAP points; they're converted to terrain-local internally. Pass
    replace=true to reset the feature list first (default appends)."""
    label = p.get("label", "terrain")
    meta = _meta_of(label)
    actor = _ue.find_by_label(label)
    if meta is None or actor is None:
        return {"error": f"no terrain labelled '{label}' (create it first)"}
    err = _set_material(meta, p)
    if err:
        return {"error": err}
    _set_uv_tile(meta, p)
    feats = _to_local_features(p.get("features", []), _eff_origin(label, meta))
    if p.get("replace"):
        meta["features"] = feats
    else:
        meta["features"].extend(feats)
    verts = _rebuild(actor, meta)
    _save_meta()
    hi, lo = _height_range(meta)
    zb = _eff_origin(label, meta)[2] + meta.get("base_height", 0.0)
    return {"shaped": label, "feature_count": len(meta["features"]),
            "height_range_cm": [round(zb + lo, 1), round(zb + hi, 1)], "vertices": verts,
            "undoable": False}


def _flatten(p):
    """Carve a building pad / path bed: blend the terrain toward a level inside a region,
    feathered over blend_margin. region: circle{at,radius} | rect{at,size} | polygon{points}
    in MAP coords. height defaults to the current terrain height at the region's anchor
    (so a pad sits at grade), or pass an explicit height."""
    label = p.get("label", "terrain")
    meta = _meta_of(label)
    actor = _ue.find_by_label(label)
    if meta is None or actor is None:
        return {"error": f"no terrain labelled '{label}'"}
    eo = _eff_origin(label, meta)
    region = _region_to_local(p.get("region"), eo)
    if region is None:
        return {"error": "flatten requires region={kind:circle|rect|polygon, ...}"}
    anchor = _region_anchor(region)
    extent = min(meta["size"]) / 2.0
    zb = eo[2] + meta.get("base_height", 0.0)       # local height 0 sits at this WORLD z
    target = p.get("height")
    if target is None:                              # default: current grade at the anchor
        target = heightfield.height_at(anchor[0], anchor[1], meta["features"], extent)
    else:
        target = float(target) - zb                 # explicit height is WORLD z → local
    feat = {"kind": "flatten", "region": region, "height": target,
            "blend_margin": p.get("blend_margin", 1500.0)}
    meta["features"].append(feat)
    verts = _rebuild(actor, meta)
    _save_meta()
    return {"flattened": label, "target_height_cm": round(zb + target, 1),
            "region": p.get("region"), "vertices": verts, "undoable": False}


def _carve(p):
    """Flatten the terrain to grade along a spline (`along=<spline label>`): a chain of
    overlapping flatten features, feathered to the spline width + blend_margin — appended
    in ONE batch with ONE mesh rebuild (the first cut rebuilt per disc: 141 rebuilds ≈ the
    30 s bridge blackout, bugs.md B6). Lives on `terrain` because the terrain is what it
    mutates (SPEC-05); the spline keeps the curve."""
    from . import spline as splinemod
    along = p.get("along")
    if not along:
        return {"error": "carve requires along=<spline label> (spline op=create first)"}
    sd = _state.splines.get(along)
    if sd is None:
        return {"error": f"no spline labelled '{along}'"}
    label = p.get("label") or sd.get("terrain", "terrain")
    meta = _meta_of(label)
    actor = _ue.find_by_label(label)
    if meta is None or actor is None:
        return {"error": f"no terrain '{label}' to carve into"}
    poly, cum = splinemod._sample_polyline([[x, y] for x, y, _ in sd["points"]])
    width = sd["width"]
    margin = p.get("blend_margin", width)
    spacing = max(width / 2.0, 200.0)
    n = max(2, int(cum[-1] / spacing))
    # Sample every disc's target from the PRE-CARVE terrain up front. If we instead let each
    # flatten default to the running grade, overlapping discs would each read the previous
    # disc's flattened height and drag the whole bed to a near-constant level (the bug that
    # levelled a valley-spanning road). Fixing targets to the natural grade makes the bed
    # follow the terrain — level across the route, sloping along it. Coords/grades are in
    # terrain-LOCAL space off the EFFECTIVE origin (G26: composes a nudged actor transform).
    ox, oy, _oz = _eff_origin(label, meta)
    extent = min(meta["size"]) / 2.0
    pre_feats = list(meta["features"])
    feats = []
    for i in range(n + 1):
        (x, y), _t = splinemod._point_at_fraction(poly, cum, i / n)
        lx, ly = x - ox, y - oy
        grade = heightfield.height_at(lx, ly, pre_feats, extent)
        feats.append({"kind": "flatten", "height": grade, "blend_margin": margin,
                      "region": {"kind": "circle", "at": [lx, ly], "radius": width / 2.0}})
    meta["features"].extend(feats)
    verts = _rebuild(actor, meta)
    _save_meta()
    out = {"carved": along, "terrain": label, "discs": len(feats),
           "vertices": verts, "undoable": False,
           "note": "bed flattened to natural grade along the spline (one rebuild)"}
    if sd.get("surface_actor"):
        # The strip was draped on the PRE-carve ground — rebuild it on the new bed.
        surf = sd.get("surface", {})
        res = splinemod._surface({"label": along, **surf})
        out["surface_rebuilt"] = res.get("surfaced") or res.get("error")
    return out


def _describe(p):
    """Bounds, height range, and height/slope sampled at MAP points (`at=[[x,y],...]`) — so
    placement can ask "how high is the ground here" without a trace. Sampling uses the same
    height function that built the mesh, so it agrees with world traces."""
    label = p.get("label", "terrain")
    meta = _meta_of(label)
    if meta is None:
        return {"error": f"no terrain labelled '{label}'"}
    # Model answers compose the actor's LIVE transform + base_height (G26): a nudged
    # terrain must not read as 'diverges' forever, and base_height is real world z.
    ox, oy, oz = _eff_origin(label, meta)
    zb = oz + meta.get("base_height", 0.0)
    sx, sy = meta["size"]
    hi, lo = _height_range(meta)
    out = {"label": label, "origin": [ox, oy, oz], "size_cm": meta["size"],
           "bounds": {"x": [ox - sx / 2, ox + sx / 2], "y": [oy - sy / 2, oy + sy / 2],
                      "z": [round(zb + lo, 1), round(zb + hi, 1)]},
           "height_range_cm": [round(zb + lo, 1), round(zb + hi, 1)],
           "feature_count": len(meta["features"])}
    if meta.get("material"):
        out["material"] = meta["material"]
    pts = p.get("at")
    if pts:
        # Ignore everything placed ON the terrain so the trace answers the SURFACE, not a
        # cube resting on it — hit only the terrain itself (G15/G18).
        ignore = [a for a in _ue.ueb_actors() if a.get_actor_label() != label]
        out["samples"] = [_sample(label, meta, pt, ignore) for pt in pts]
        if any(s.get("diverges") for s in out["samples"]):
            out["note"] = ("some samples read the TRACED mesh, which differs from the feature "
                           "model — the terrain was carved/flattened there; trust z (traced)")
    return out


# ── helpers ──────────────────────────────────────────────────────────────────────
def _to_local_features(features, origin):
    """Shift a feature's map coords into terrain-local (centred on origin)."""
    ox, oy = origin[0], origin[1]
    out = []
    for f in features:
        g = dict(f)
        if "at" in g:
            g["at"] = [g["at"][0] - ox, g["at"][1] - oy]
        out.append(g)
    return out


def _region_to_local(region, origin):
    if not region:
        return None
    ox, oy = origin[0], origin[1]
    r = dict(region)
    if "at" in r:
        r["at"] = [r["at"][0] - ox, r["at"][1] - oy]
    if "points" in r:
        r["points"] = [[x - ox, y - oy] for x, y in r["points"]]
    return r


def _region_anchor(region):
    if "at" in region:
        return region["at"]
    if "points" in region:
        pts = region["points"]
        return [sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts)]
    return [0.0, 0.0]


def _height_range(meta):
    """Coarse min/max height by sampling the feature field on a grid (local frame)."""
    sx, sy = meta["size"]
    extent = min(sx, sy) / 2.0
    feats = meta["features"]
    hi, lo = -1e18, 1e18
    N = 24
    for i in range(N + 1):
        for j in range(N + 1):
            lx = (i / N - 0.5) * sx
            ly = (j / N - 0.5) * sy
            h = heightfield.height_at(lx, ly, feats, extent)
            hi = max(hi, h); lo = min(lo, h)
    return hi, lo


def _sample(label, meta, pt, ignore=None):
    ox, oy, oz = _eff_origin(label, meta)
    lx, ly = pt[0] - ox, pt[1] - oy
    extent = min(meta["size"]) / 2.0
    feats = meta["features"]
    h = heightfield.height_at(lx, ly, feats, extent)
    z_model = round(oz + meta.get("base_height", 0.0) + h, 1)
    # slope: gradient magnitude over a 1 m step → degrees from horizontal (model-based)
    d = 100.0
    hx = heightfield.height_at(lx + d, ly, feats, extent) - heightfield.height_at(lx - d, ly, feats, extent)
    hy = heightfield.height_at(lx, ly + d, feats, extent) - heightfield.height_at(lx, ly - d, feats, extent)
    import math
    slope = math.degrees(math.atan2(math.hypot(hx, hy), 2 * d))
    # G15: the feature model doesn't see carve/flatten mesh edits, so TRACE the actual
    # surface and trust it. Fall back to the model only when the trace misses (collision not
    # cooked — the B3 cook race), flagged so a miss never passes as agreement.
    zt = _ue.trace_ground(pt[0], pt[1], ignore=ignore)
    out = {"at": [pt[0], pt[1]], "slope_deg": round(slope, 1), "z_model": z_model}
    if zt is None:
        out["z"] = z_model
        out["source"] = "model (trace missed — collision not cooked yet? see B3)"
    else:
        out["z"] = round(zt, 1)
        out["source"] = "traced (actual mesh)"
        if abs(zt - z_model) > 5.0:
            out["diverges"] = f"feature model says z={z_model}; mesh here is z={round(zt,1)}"
    return out
