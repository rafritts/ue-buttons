"""The M1 verb surface — one handler per verb, routed by `handle`.

Auto-status rides on every MUTATING verb (SPEC-00). Read-only / nav verbs neither log to
history nor push a transaction nor carry a status block — the same three-way
classification blender-buttons uses to keep history 1:1 with the undo stack (gaps.md G1).
"""
import unreal

from . import _state
from . import _ue
from . import relational

# Verbs that mutate the world: they log an op, run inside a ueb:<id> transaction, and get
# the status block appended. Everything else is a pure read / navigation.
MUTATING = {"add", "transform"}
# `select` mutates editor selection (not the world) — it refreshes status but is NOT
# logged/undoable (matches blender-buttons: selection is not a geometry op).
STATUS_ONLY = {"select"}
# `history` with op=undo_to mutates but manages its own undo accounting — never logs
# itself (would desync the 1:1 count) and never nests a transaction.


def handle(verb, params):
    fn = _VERBS.get(verb)
    if fn is None:
        return {"error": f"unknown verb '{verb}'. known: {sorted(_VERBS)}"}
    result = fn(params)
    if verb in MUTATING or verb in STATUS_ONLY:
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


def _v_add(p):
    """Spawn a primitive with exact cm dims and relational placement.
    params: what, dims:[x,y,z], label, place:{...} (see relational.resolve_placement)."""
    shape = p.get("what", "cube")
    if shape not in _ue.BASIC_SHAPES:
        return {"error": f"unknown shape '{shape}'. known: {sorted(_ue.BASIC_SHAPES)}"}
    dims = p.get("dims", [100, 100, 100])
    label = p.get("label")
    if not label:
        return {"error": "add requires a unique 'label'"}
    if _ue.find_by_label(label) is not None:
        return {"error": f"label '{label}' already exists (labels must be unique)"}

    place = p.get("place") or {}
    with _Txn("add") as txn:
        # Spawn at origin, scale to dims, then resolve placement from the now-known size.
        actor = _ue.spawn_basic_shape(shape, [0, 0, 0])
        actor.set_actor_label(label)
        _ue.set_scale_for_dims(actor, dims)
        loc = relational.resolve_placement(actor, place)
        actor.set_actor_location(unreal.Vector(*loc), False, False)
        _ue.actor_subsystem().set_selected_level_actors([actor])
    op_id = _state.log_op(txn.op_id, "add", f"{shape} '{label}' {dims}cm",
                          f"ueb add {label}")
    return {"added": label, "shape": shape, "dims": dims, "op": op_id}


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
    """Camera by orbit + screenshot.
    params: azimuth, elevation (deg), distance (cm), target ([x,y,z] or label),
            shot:true to capture, width, height.
    Orbit: camera sits distance away from target on the (az,el) direction and looks back
    at it. az measured from +X toward +Y; el up from the ground plane."""
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
}
