"""The M1 verb surface — one handler per verb, routed by `handle`.

Auto-status rides on every MUTATING verb (SPEC-00). Read-only / nav verbs neither log to
history nor push a transaction nor carry a status block — the same three-way
classification blender-buttons uses to keep history 1:1 with the undo stack (gaps.md G1).
"""
import unreal

from . import _state
from . import _ue
from . import relational
from . import asset
from . import terrain
from . import landscape
from . import map_ref
from . import path as pathmod
from . import scatter as scattermod

# Verbs that mutate the world: they log an op, run inside a ueb:<id> transaction, and get
# the status block appended. Everything else is a pure read / navigation.
MUTATING = {"add", "transform"}
# `select` mutates editor selection (not the world) — it refreshes status but is NOT
# logged/undoable (matches blender-buttons: selection is not a geometry op).
STATUS_ONLY = {"select"}
# Spatial-domain verbs (SPEC-01) mutate the world but manage their own lifecycle and are NOT
# cleanly undoable via the transaction stack (DynamicMesh/HISM edits don't sit in it — G12),
# so they never log to the 1:1 history nor push a _Txn. They get a status block; each carries
# an honest `undoable: false`, and teardown is their own `remove`/editor delete.
SPATIAL = {"landscape", "path", "scatter"}
# `history` with op=undo_to mutates but manages its own undo accounting — never logs
# itself (would desync the 1:1 count) and never nests a transaction.


def handle(verb, params):
    fn = _VERBS.get(verb)
    if fn is None:
        return {"error": f"unknown verb '{verb}'. known: {sorted(_VERBS)}"}
    result = fn(params)
    if (verb in MUTATING or verb in STATUS_ONLY or verb in SPATIAL) \
            and isinstance(result, dict) and "error" not in result:
        result["status"] = _status_block()
    return result


# ── transactions ────────────────────────────────────────────────────────────
class _Txn:
    """Wrap one mutating verb in an editor transaction labelled `ueb:<id> <verb>`, so
    editor Ctrl+Z and our undo agree and stay 1:1 (gaps.md G1). The op id is minted up
    front so the label carries it."""
    def __init__(self, verb):
        self.verb = verb
        self.op_id = _state.reserve_op_id()

    def __enter__(self):
        label = f"ueb:{self.op_id} {self.verb}"
        unreal.SystemLibrary.begin_transaction("ueb", unreal.Text(label), None)
        return self

    def __exit__(self, exc_type, exc, tb):
        unreal.SystemLibrary.end_transaction()
        return False


# ── auto-status ───────────────────────────────────────────────────────────────
def _status_block():
    """The ── ue status ── block appended to mutating verbs (SPEC-00 format)."""
    eas = _ue.actor_subsystem()
    sel = eas.get_selected_level_actors()
    sel_labels = [a.get_actor_label() for a in sel]
    active = sel[-1] if sel else None
    lines = ["── ue status ───────────────────────────────"]
    lines.append(f"  level:      {_ue.level_name()}")
    lines.append(f"  selected:   {sel_labels}")
    if active is not None:
        b = _ue.bounds(active)
        sz = [round(v, 1) for v in b["size"]]
        bx = [round(b['min'][0], 1), round(b['max'][0], 1)]
        by = [round(b['min'][1], 1), round(b['max'][1], 1)]
        bz = [round(b['min'][2], 1), round(b['max'][2], 1)]
        lines.append(f"  active:     {active.get_actor_label()}  dims: {sz} cm  "
                     f"bounds: x={bx} y={by} z={bz}")
    else:
        lines.append("  active:     (none)")
    last = _state.last_op()
    lines.append(f"  last_action: {last}")
    lines.append("────────────────────────────────────────────")
    return "\n".join(lines)


# ── verbs ───────────────────────────────────────────────────────────────────
def _v_scene(p):
    """Actor tree grouped by type, counts, level name. Scoped to ueb-spawned actors by
    default (gaps.md G7); pass include_all:true to see the whole level. Untracked count
    is always reported so the engine scaffolding is acknowledged, not hidden."""
    include_all = p.get("include_all", False)
    pool = _ue.all_actors() if include_all else _ue.ueb_actors()
    groups = {}
    for a in pool:
        b = _ue.bounds(a)
        if b["size"] == [0, 0, 0]:
            continue
        cls = a.get_class().get_name()
        groups.setdefault(cls, []).append(a.get_actor_label())
    untracked = len(_ue.all_actors()) - len(_ue.ueb_actors())
    return {"level": _ue.level_name(),
            "scope": "all" if include_all else "ueb",
            "count": sum(len(v) for v in groups.values()),
            "untracked": untracked,
            "actors": {k: sorted(v) for k, v in groups.items()}}


def _ground_flag(place):
    """Pull a ground-snap directive out of the placement spec, returning (clean_place,
    snap?). Accepts {"ground": true} or the natural {"on": "ground"} phrasing — either
    way "ground" is a z-datum handled by a trace, not a label resolve_placement can look
    up, so it must be stripped before placement math runs."""
    if not place:
        return place, False
    snap = bool(place.get("ground")) or place.get("on") == "ground"
    if snap:
        place = {k: v for k, v in place.items()
                 if not (k == "ground" or (k == "on" and v == "ground"))}
    return place, snap


def _facing_yaw(place, facing):
    """Compass yaw (deg) that points the actor's +X toward a path. `facing` is a path label;
    the object faces the path point at the along-fraction it was placed at (or the midpoint),
    from its offset side — "cabin_2 facing the path" reads as looking at the road."""
    import math
    spec = place.get("along") or {}
    frac = spec.get("fraction", 0.5)
    pt, tan = pathmod.point_and_tangent(facing, frac)
    off = spec.get("offset", spec.get("offset_cm", 0.0))
    side = spec.get("side", "left")
    perp = (-tan[1], tan[0]) if side == "left" else (tan[1], -tan[0])
    # object sits at pt + perp*off; direction back to the path centre is -perp
    dx, dy = -perp[0], -perp[1]
    return math.degrees(math.atan2(dy, dx))          # bearing: atan2(east, north), N=+X


def _place_actor(actor, place, yaw=None, snap_ground=False, facing=None):
    """Shared placement tail for every spawn (primitive or project asset).

    Order matters: rotate first so the world AABB (and the pivot→centre offset) reflect the
    final footprint, resolve the relational spec to a desired bounds *centre*, correct for a
    non-centred pivot (G4), then optionally drop the actor onto the ground by a downward
    trace. Centred-pivot BasicShapes have a zero delta, so this is behaviour-preserving for
    the M1 primitive path."""
    if facing is not None:
        yaw = _facing_yaw(place, facing)
    if yaw is not None:
        actor.set_actor_rotation(unreal.Rotator(yaw=yaw, pitch=0.0, roll=0.0), False)
    target = relational.resolve_placement(actor, place)      # desired world bounds centre
    if snap_ground:
        gz = _ue.trace_ground(target[0], target[1], ignore=actor)
        if gz is not None:
            half_z = _ue.bounds(actor)["size"][2] / 2.0      # sit bounds-min on the ground
            target = [target[0], target[1], gz + half_z]
    delta = _ue.pivot_to_center_delta(actor)                 # centre − location
    actor.set_actor_location(
        unreal.Vector(target[0] - delta[0], target[1] - delta[1], target[2] - delta[2]),
        False, False)
    return target


def _v_add(p):
    """Spawn a primitive OR a project asset with relational placement.
    Primitive: what, dims:[x,y,z]. Project asset: asset (inventory name or /Game path),
    optional dims override, yaw. Common: label, place:{...}, place may carry {"ground":true}
    (or {"on":"ground"}) to drop onto the terrain by a trace."""
    label = p.get("label")
    if not label:
        return {"error": "add requires a unique 'label'"}
    if _ue.find_by_label(label) is not None:
        return {"error": f"label '{label}' already exists (labels must be unique)"}
    place, snap = _ground_flag(p.get("place") or {})
    yaw = p.get("yaw")
    facing = p.get("facing")

    if p.get("asset"):
        return _add_asset(p, label, place, snap, yaw, facing)

    shape = p.get("what", "cube")
    if shape not in _ue.BASIC_SHAPES:
        return {"error": f"unknown shape '{shape}'. known: {sorted(_ue.BASIC_SHAPES)}"}
    dims = p.get("dims", [100, 100, 100])
    with _Txn("add") as txn:
        actor = _ue.spawn_basic_shape(shape, [0, 0, 0])
        actor.set_actor_label(label)
        _ue.set_scale_for_dims(actor, dims)
        _place_actor(actor, place, yaw=yaw, snap_ground=snap, facing=facing)
        _ue.actor_subsystem().set_selected_level_actors([actor])
    op_id = _state.log_op(txn.op_id, "add", f"{shape} '{label}' {dims}cm",
                          f"ueb add {label}")
    return {"added": label, "shape": shape, "dims": dims, "op": op_id}


def _add_asset(p, label, place, snap, yaw, facing=None):
    """Spawn a project StaticMesh or Blueprint by inventory name / full path (SPEC-01 E2).
    Native scale by default (marketplace dims are placement info, not a resize invite); an
    explicit dims override scales and warns."""
    query = p["asset"]
    path, candidates = asset._resolve_asset_path(query)
    if path is None:
        if not candidates:
            return {"error": f"no asset matches '{query}'"}
        return {"error": f"'{query}' is ambiguous — pick one or use scatter for random "
                         "variants", "candidates": candidates[:20],
                "candidate_count": len(candidates)}

    is_bp = unreal.EditorAssetLibrary.load_blueprint_class(path) is not None
    warn = None
    with _Txn("add") as txn:
        if is_bp:
            actor = _ue.spawn_blueprint(path, [0, 0, 0])
        else:
            actor = _ue.spawn_static_mesh(path, [0, 0, 0])
        actor.set_actor_label(label)
        dims = p.get("dims")
        if dims:                                  # explicit override → scale off native size
            native = _ue.native_size(actor)
            scale = [dims[i] / native[i] if native[i] else 1.0 for i in range(3)]
            cur = actor.get_actor_scale3d()
            actor.set_actor_scale3d(unreal.Vector(cur.x * scale[0], cur.y * scale[1],
                                                  cur.z * scale[2]))
            warn = (f"dims override → scaled {[round(s, 3) for s in scale]}× off native "
                    "size; marketplace meshes are usually best left native")
        _place_actor(actor, place, yaw=yaw, snap_ground=snap, facing=facing)
        _ue.actor_subsystem().set_selected_level_actors([actor])
    b = _ue.bounds(actor)
    op_id = _state.log_op(txn.op_id, "add",
                          f"asset '{label}' <- {path.split('/')[-1]}",
                          f"ueb add {label}")
    out = {"added": label, "asset": path, "kind": "blueprint" if is_bp else "static_mesh",
           "dims_cm": [round(v, 1) for v in b["size"]], "op": op_id}
    if warn:
        out["warning"] = warn
    return out


def _v_transform(p):
    """action: nudge | resize | rotate. target: label. See docstrings per action."""
    action = p.get("action", "nudge")
    target = p.get("target")
    actor = _ue.find_by_label(target) if target else None
    if actor is None:
        return {"error": f"no actor labelled '{target}'"}
    with _Txn("transform") as txn:
        if action == "nudge":
            d = p.get("by", [0, 0, 0])  # cm, world axes
            loc = actor.get_actor_location()
            actor.set_actor_location(
                unreal.Vector(loc.x + d[0], loc.y + d[1], loc.z + d[2]), False, False)
        elif action == "resize":
            _ue.set_scale_for_dims(actor, p.get("dims"))
        elif action == "rotate":
            r = p.get("to", [0, 0, 0])  # [yaw, pitch, roll] deg (UE Rotator convention)
            # Rotator positional order is (roll, pitch, yaw) — use kwargs (bugs.md B1).
            actor.set_actor_rotation(
                unreal.Rotator(yaw=r[0], pitch=r[1], roll=r[2]), False)
        else:
            return {"error": f"unknown transform action '{action}'"}
        _ue.actor_subsystem().set_selected_level_actors([actor])
    op_id = _state.log_op(txn.op_id, "transform", f"{action} {target}",
                          f"ueb transform {target}")
    return {"transformed": target, "action": action, "op": op_id}


def _v_select(p):
    """Select actors by label or clear. params: labels:[...] | clear:true."""
    eas = _ue.actor_subsystem()
    if p.get("clear"):
        eas.set_selected_level_actors([])
        return {"selected": []}
    labels = p.get("labels", [])
    actors = [a for a in (_ue.find_by_label(l) for l in labels) if a]
    eas.set_selected_level_actors(actors)
    return {"selected": [a.get_actor_label() for a in actors]}


def _v_feel(p):
    """Relational perception — describe(actor) / distance_between / gap_between / is_aligned.
    Delegates to relational.py (ported math)."""
    return relational.feel(p)


def _v_view(p):
    """Camera by orbit + screenshot, or the top-down site map.
    action="map" (default "orbit"): return map data (height grid + labelled actor markers +
    paths + scatter regions) for the server to render — the grounding for absolute [x,y]."""
    if p.get("action") == "map":
        return _map_data(p)
    import math
    target = p.get("target", [0, 0, 0])
    if isinstance(target, str):
        t = _ue.find_by_label(target)
        if t is None:
            return {"error": f"no actor labelled '{target}'"}
        target = _ue.bounds(t)["center"]
    az = math.radians(p.get("azimuth", 45.0))
    el = math.radians(p.get("elevation", 25.0))
    dist = p.get("distance", 500.0)
    # outward unit vector (camera offset from target)
    ux = math.cos(el) * math.cos(az)
    uy = math.cos(el) * math.sin(az)
    uz = math.sin(el)
    cam = [target[0] + ux * dist, target[1] + uy * dist, target[2] + uz * dist]
    # look back at target → rotation
    yaw = math.degrees(math.atan2(-uy, -ux))
    pitch = math.degrees(math.asin(-uz))
    ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    # unreal.Rotator positional order is (roll, pitch, yaw) — use kwargs (bugs.md B1).
    ues.set_level_viewport_camera_info(unreal.Vector(*cam),
                                       unreal.Rotator(pitch=pitch, yaw=yaw, roll=0.0))
    result = {"camera": [round(v, 1) for v in cam],
              "look_at": [round(v, 1) for v in target],
              "rot": [round(yaw, 1), round(pitch, 1), 0.0]}
    if p.get("shot"):
        shot = _ue.screenshot(p.get("width", 1280), p.get("height", 720))
        result.update(shot)
    return result


def _v_asset(p):
    """Perception over the project's Content — packs | inventory | describe | find |
    whats_new. Read-only (no transaction/history/status). See asset.py."""
    return asset.handle(p)


def _v_landscape(p):
    """Terrain as a heightfield — create | shape | flatten | describe. Spatial verb: gets a
    status block, not undoable via history (see landscape.py / G12)."""
    return landscape.handle(p)


def _v_path(p):
    """Splines as intent — create | carve | describe | remove. Spatial verb. See path.py."""
    return pathmod.handle(p)


def _v_scatter(p):
    """Populations — create | describe | regenerate | remove. Spatial verb. See scatter.py."""
    return scattermod.handle(p)


def _map_data(p):
    """Assemble the top-down site map (SPEC-01 E3): a height grid over the terrain extent plus
    every labelled ueb actor, path, and scatter region — enough for the server to render a
    labelled site plan the agent reads absolute [x,y] off (derived, not divined)."""
    label = p.get("label", "terrain")
    meta = _state.landscapes.get(label)
    res = int(p.get("grid", 72))
    if meta is not None:
        ox, oy, oz = meta["origin"]
        sx, sy = meta["size"]
        extent = min(sx, sy) / 2.0
        feats = meta["features"]
        grid = []
        for j in range(res):                    # row-major, y ascending
            row = []
            ly = (j / (res - 1) - 0.5) * sy
            for i in range(res):
                lx = (i / (res - 1) - 0.5) * sx
                row.append(round(oz + terrain.height_at(lx, ly, feats, extent), 1))
            grid.append(row)
        bounds = {"x": [ox - sx / 2, ox + sx / 2], "y": [oy - sy / 2, oy + sy / 2]}
    else:
        grid, bounds = None, None

    # terrains render as the height field; scatter groups render as region outlines — so
    # neither belongs in the point-marker list (a scatter actor's AABB spans the whole stand).
    hide = set(_state.landscapes.keys()) | set(_state.scatters.keys())
    markers = []
    for a in _ue.ueb_actors():
        lbl = a.get_actor_label()
        if lbl in hide:
            continue
        b = _ue.bounds(a)
        if b["size"] == [0, 0, 0]:
            continue
        markers.append({"label": lbl, "x": round(b["center"][0], 1),
                        "y": round(b["center"][1], 1),
                        "bbox": [round(b["min"][0], 1), round(b["min"][1], 1),
                                 round(b["max"][0], 1), round(b["max"][1], 1)]})
    paths = [{"label": k, "points": [[pt[0], pt[1]] for pt in v["points"]],
              "width": v.get("width", 0)} for k, v in _state.paths.items()]
    scatters = [{"label": k, "region": v.get("region")} for k, v in _state.scatters.items()]
    return {"map": True, "label": label, "bounds": bounds, "grid": grid,
            "markers": markers, "paths": paths, "scatters": scatters}


def _v_history(p):
    """op: list | undo_to. undo_to issues N console TRANSACTION UNDOs (gaps.md G1)."""
    op = p.get("op", "list")
    if op == "list":
        return {"history": _state.history}
    if op == "undo_to":
        target = p.get("id")
        ids = [h["id"] for h in _state.history]
        if target not in ids:
            return {"error": f"op '{target}' not in history"}
        idx = ids.index(target)
        to_undo = _state.history[idx + 1:]      # everything AFTER the target
        _ue.undo(len(to_undo))
        _state.mark_undone(len(to_undo))
        return {"undone_to": target, "undone": [h["id"] for h in to_undo]}
    return {"error": f"unknown history op '{op}'"}


_VERBS = {
    "scene": _v_scene,
    "add": _v_add,
    "transform": _v_transform,
    "select": _v_select,
    "feel": _v_feel,
    "view": _v_view,
    "history": _v_history,
    "asset": _v_asset,
    "landscape": _v_landscape,
    "path": _v_path,
    "scatter": _v_scatter,
}
