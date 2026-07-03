"""The M1 verb surface — one handler per verb, routed by `handle`.

Auto-status rides on every MUTATING verb (SPEC-00). Read-only / nav verbs neither log to
history nor push a transaction nor carry a status block — the same three-way
classification blender-buttons uses to keep history 1:1 with the undo stack (gaps.md G1).
"""
import json

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
from . import render as rendermod
from . import validate as validatemod

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

# Auto-follow camera (G17): after every mutating verb, aim the viewport at what was just
# touched so the human always sees the agent's hands. Default ON; the flag lives in
# never-reloaded _state so a hot-reload can't silently flip it. Camera moves are
# perception-side — never logged, never a transaction (must not touch the shared undo stack).
if not hasattr(_state, "follow"):
    _state.follow = True


def _level_guard():
    """G23: the op log + declared intents describe ONE level's arrangement. On the first
    dispatch after a level change, clear both — op001 from a dead level must never stamp a
    fresh level's status blocks, and undo_to can never cross a level boundary. (A save-as
    rename counts as a change — conservative and documented.) Actor/foliage registries have
    their own lifecycle (`scene op=reconcile`, G16)."""
    if not hasattr(_state, "level_stamp"):
        _state.level_stamp = [None]
    lvl = _ue.level_name()
    prev = _state.level_stamp[0]
    _state.level_stamp[0] = lvl
    if prev is None or prev == lvl:
        return None
    n_ops, n_int = len(_state.history), len(_state.intents)
    _state.history.clear()
    _state._undone.clear()
    _state.intents.clear()
    _state.drift[0] = 0.0
    _state.engine_grounds_memo = None
    if n_ops or n_int:
        return (f"level changed ({prev} → {lvl}) — cleared {n_ops} logged op(s) and "
                f"{n_int} declared intent(s) from the old level (G23); "
                f"scene op=reconcile to check the registries")
    return None


def _unstringify(params):
    """B7: the MCP tool layer types union-contract params (label-or-[x,y,z]) as scalars,
    so a list/dict arrives as its string repr and duck-typing downstream never sees the
    structure. Recover it centrally: any string value that LOOKS like a JSON array/object
    and parses becomes the parsed value. A real label/name can't be caught — none starts
    with '[' or '{' and parses as JSON."""
    for k, v in list(params.items()):
        if isinstance(v, str) and v[:1] in ("[", "{"):
            try:
                params[k] = json.loads(v)
            except ValueError:
                pass
    return params


def handle(verb, params):
    fn = _VERBS.get(verb)
    if fn is None:
        return {"error": f"unknown verb '{verb}'. known: {sorted(_VERBS)}"}
    params = _unstringify(params)
    # B8: during PIE the editor world reads as None/empty — a verb that runs then sees a
    # void level: mutations silently no-op and reconcile GC's every live registry entry.
    # The verb surface targets the EDITOR world only; refuse until Play stops. One exempt
    # op: scene op=pie_census reads the GAME world by design (G36) and ends Play itself.
    if (unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor()
            or _ue.editor_world() is None):
        if verb == "scene" and params.get("op") == "pie_census":
            return _pie_census(params)
        return {"error": "the editor is in PIE (Play) — the verb surface reads and mutates "
                         "the EDITOR world, and during Play that world reads as empty "
                         "(mutations would no-op; reconcile would GC live registries — B8). "
                         "Stop Play and re-issue."}
    level_note = _level_guard()
    result = fn(params)
    if level_note and isinstance(result, dict) and "error" not in result:
        result.setdefault("notes", []).append(level_note)
    if (verb in MUTATING or verb in STATUS_ONLY or verb in SPATIAL) \
            and isinstance(result, dict) and "error" not in result:
        result["status"] = _status_block(verb, params, result)
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


# ── auto-status: the REPL block (SPEC-02) ───────────────────────────────────────
# Every mutating verb returns, in order: result text (the json head, rendered by the
# server) → warnings → the three forced senses (feel delta, validate line, render line) →
# a periodic re-ground recap → the status block. This turns call-and-response into a REPL:
# the agent acts and, in the same round-trip, SEES what changed, what's now broken, and
# whether it will actually DRAW — it never operates blind and can never mistake silence for
# success (SPEC-02/03; blender-buttons SPEC-16). The block itself is a single-object
# spotlight; relational defects (penetration, z-fight) and renderability can't live there,
# which is exactly why validate and render are their own forced channels.

def _focus_label(verb, params, result):
    """The actor/subject this op acted on — what the forced senses and the block describe."""
    if verb == "add":
        return result.get("added")
    if verb == "transform":
        return result.get("transformed") or params.get("target")
    if verb == "select":
        sel = result.get("selected") or []
        return sel[-1] if sel else None
    if verb in SPATIAL:
        return result.get("label") or params.get("label")
    return None


def _warnings(result):
    """Pull the dedicated warning channels out of the result (and OFF the json head, so
    each is surfaced exactly once, ahead of the block where it can't be lost): a no-op
    that changed nothing, a degraded success, and generic postcondition notes."""
    out = []
    for key in ("no_op_warning", "degraded_warning"):
        w = result.pop(key, None)
        if w:
            out.append(w)
    for n in (result.pop("notes", None) or []):
        out.append(n)
    return out


def _status_block(verb, params, result):
    focus = _focus_label(verb, params, result)
    lines = []

    # 1. warnings channel — ahead of everything, ⚠-marked, never lost.
    for w in _warnings(result):
        lines.append("⚠ " + w)

    # 2 & 3. the two forced senses. They run on GEOMETRY/PLACEMENT ops — a `select`
    # rearranges nothing to validate, and a spatial (terrain/population) edit isn't an
    # actor the per-actor floor can check, so it says so rather than faking a clean pass.
    if verb in MUTATING:
        fd = validatemod.feel_delta(focus)
        if fd:
            lines.append(fd)
        # Delta scope only — an unresolved focus gets B4's attributed "nothing to check"
        # line, never a whole-scene sweep masquerading as this op's delta.
        v = validatemod.run_validate([focus] if focus else [])
        if v.get("line"):
            lines.append(("" if v.get("passed") else "⚠ ") + v["line"])
        # Sense 3 — the renderability floor (SPEC-03): will the delta actually DRAW.
        rl = rendermod.render_line([focus] if focus else [])
        if rl:
            lines.append(rl)
    elif verb in SPATIAL:
        fd = result.get("feel") or validatemod.feel_delta(focus)
        if fd:
            lines.append(fd)
        lines.append("validate: OFF for this edit — the actor floor checks placed actors "
                     "(add/transform), not the terrain/population itself; `validate op=run` "
                     "to sweep placed actors against it")
        # Sense 3 for populations — the motivating case (a scatter correct in every data
        # probe that draws nothing). Terrain/path render-walk is the next increment.
        if verb == "scatter" and focus:
            lines.append(rendermod.population_line(focus))
    elif verb in STATUS_ONLY:
        fd = validatemod.feel_delta(focus)
        if fd:
            lines.append(fd)

    # 4. periodic re-ground — enough has changed that a stale mental model is a liability.
    if verb in MUTATING or verb in SPATIAL:
        rg = validatemod.accrue_drift(verb)
        if rg:
            lines.append("── re-ground (significant changes since the last checkpoint) ──")
            lines.append(f"  scene: {rg['actor_count']} placed actor(s): {rg['actors']}")
            if rg["declared_holding"]:
                lines.append(f"  intended contacts holding: {', '.join(rg['declared_holding'])}")
            if rg["declared_vanished"]:
                lines.append(f"  ⚠ intended contacts VANISHED: {', '.join(rg['declared_vanished'])}")
            lines.append("  re-read anything you haven't felt in a while before building on it.")

    # 4b. auto-follow camera (G17) — aim the viewport at what was just touched so the human
    # always sees the agent's hands. OFF announces itself (same honesty as validate/render).
    if verb in MUTATING or verb in SPATIAL:
        if _state.follow:
            _follow_camera(focus)

    # 5. the block itself — a single-object spotlight on the acted-on actor.
    lines += _block_lines(result, focus)
    return "\n".join(lines)


def _follow_camera(focus):
    """Frame the acted-on actor (or the region a spatial edit touched) in the editor
    viewport. Distance is sized to the bounds so the whole thing fits; a fixed 3/4 azimuth +
    35° downward pitch reads as a natural over-the-shoulder view. Positions the human's
    viewport only (no capture — there is no screenshot verb); never logged, never a
    transaction. This is camera courtesy for the human's OWN screen, not perception."""
    import math
    actor = _ue.find_by_label(focus) if focus else None
    if actor is None:
        sel = _ue.actor_subsystem().get_selected_level_actors()
        actor = sel[-1] if sel else None
    if actor is None:
        return
    b = _ue.bounds(actor)
    if b["size"] == [0, 0, 0]:
        return
    center = b["center"]
    radius = max(max(b["size"]) / 2.0, 50.0)
    dist = max(radius * 2.4, 300.0)              # fit with margin (fov≈90 → half-angle 45)
    az, el = math.radians(135.0), math.radians(35.0)
    ux, uy, uz = math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)
    cam = [center[0] + ux * dist, center[1] + uy * dist, center[2] + uz * dist]
    yaw = math.degrees(math.atan2(-uy, -ux))
    pitch = math.degrees(math.asin(-uz))
    ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    ues.set_level_viewport_camera_info(unreal.Vector(*cam),
                                       unreal.Rotator(pitch=pitch, yaw=yaw, roll=0.0))


def _block_lines(result, focus):
    eas = _ue.actor_subsystem()
    sel = eas.get_selected_level_actors()
    sel_labels = [a.get_actor_label() for a in sel]
    # Bounds always describe the ACTED-ON actor, even if the viewport-active one lags
    # (blender-buttons G76). Fall back to the viewport-active selection when there's no
    # name-addressed focus (e.g. a spatial edit whose subject isn't a spotlightable actor).
    acted = _ue.find_by_label(focus) if focus else None
    vp_active = sel[-1] if sel else None
    show = acted or vp_active
    lines = ["── ue status ───────────────────────────────",
             f"  level:      {_ue.level_name()}",
             f"  selected:   {sel_labels}"]
    if acted is not None and vp_active is not None and \
            acted.get_actor_label() != vp_active.get_actor_label():
        lines.append(f"  acted_on:   {acted.get_actor_label()}  ⟵ bounds below are THIS actor")
        lines.append(f"  vp_active:  {vp_active.get_actor_label()}  (viewport-active lags)")
    if show is not None:
        b = _ue.bounds(show)
        sz = [round(v, 1) for v in b["size"]]
        bx = [round(b['min'][0], 1), round(b['max'][0], 1)]
        by = [round(b['min'][1], 1), round(b['max'][1], 1)]
        bz = [round(b['min'][2], 1), round(b['max'][2], 1)]
        label = show.get_actor_label()
        prefix = "  active:    " if acted is None else "  bounds of: "
        lines.append(f"{prefix} {label}  dims: {sz} cm")
        lines.append(f"              bounds: x={bx} y={by} z={bz}")
    else:
        lines.append("  active:     (none)")
    lines.append(f"  last_action: {_state.last_op()}")
    lines.append("────────────────────────────────────────────")
    return lines


# ── verbs ───────────────────────────────────────────────────────────────────
def _pie_census(p):
    """G36: game truth. The editor view and the PIE view of a map can disagree COMPLETELY —
    template-copied always-loaded actors (lights, sky, PlayerStart) whose descriptors never
    resolve at runtime render Play as an unlit void while every editor-side read says fine.
    Two-step because begin_play is asynchronous:
      call 1 (editor): snapshot the always-loaded expectation, request Play, return.
      call 2 (in PIE — exempt from the B8 guard): census the GAME world per class, diff
              against the snapshot, END Play, and name who is missing."""
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.is_in_play_in_editor():
        expect = {}
        for a in _ue.all_actors():
            try:
                if a.get_editor_property("is_spatially_loaded"):
                    continue        # streamed actors depend on pawn position — not judged
            except Exception:
                continue
            cls = a.get_class().get_name()
            # WP machinery + HLOD proxies legitimately differ between editor and PIE
            # (HLODs swap in only when their source cells stream OUT) — not game truth.
            if cls.startswith(("WorldPartition", "WorldDataLayers", "HLOD")) \
                    or cls in ("WorldSettings", "Brush", "LevelBounds"):
                continue
            expect.setdefault(cls, []).append(a.get_actor_label())
        _state.pie_census_expect = {"level": _ue.level_name(), "classes": expect}
        les.editor_request_begin_play()
        return {"pie": "starting",
                "expected_always_loaded": {k: len(v) for k, v in expect.items()},
                "note": "PIE spin-up is asynchronous — call scene op=pie_census again in "
                        "~2 s; that call censuses the game world and ends Play"}
    snap = getattr(_state, "pie_census_expect", None)
    if snap is None:
        les.editor_request_end_play()
        return {"error": "no census snapshot — Play was started outside pie_census. "
                         "Play is being stopped; re-issue scene op=pie_census."}
    gw = None
    for getter in ("get_game_world",):
        try:
            gw = getattr(unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem), getter)()
        except Exception:
            gw = None
    if gw is None:
        try:
            gw = unreal.EditorLevelLibrary.get_game_world()
        except Exception:
            gw = None
    if gw is None:
        les.editor_request_end_play()
        return {"error": "could not resolve the PIE game world; Play stopped"}
    game = {}
    for a in unreal.GameplayStatics.get_all_actors_of_class(gw, unreal.Actor):
        game.setdefault(a.get_class().get_name(), []).append(a.get_actor_label())
    les.editor_request_end_play()
    _state.pie_census_expect = None
    missing = {}
    for cls, labels in snap["classes"].items():
        present = game.get(cls, [])
        gone = [l for l in labels if l not in present]
        # fall back to count comparison when PIE renamed labels
        if gone and len(present) >= len(labels):
            gone = []
        if gone:
            missing[cls] = gone
    out = {"level": snap["level"],
           "expected_always_loaded": {k: len(v) for k, v in snap["classes"].items()},
           "in_game": {k: len(v) for k, v in sorted(game.items())
                       if k in snap["classes"]},
           "missing_at_runtime": missing,
           "pie": "ended"}
    if missing:
        out["verdict"] = ("BROKEN AT GAME TIME — these always-loaded actors never load in "
                          "PIE (the G36 template defect): delete and respawn them fresh, "
                          "then save")
    else:
        out["verdict"] = "game world agrees with the editor's always-loaded set"
    return out


def _v_scene(p):
    """Actor tree grouped by type, counts, level name. Scoped to ueb-spawned actors by
    default (gaps.md G7); pass include_all:true to see the whole level. Untracked count
    is always reported so the engine scaffolding is acknowledged, not hidden.

    op="streaming" (SPEC-03 link 1): the WorldPartition residency picture — partition status,
    data layers + effective runtime state, per-actor is_spatially_loaded/grid.
    op="reconcile" (SPEC-03, closes G16): diff the ueb registry against the editor's own
    tally — clean/dirty/orphaned with attribution; GCs orphaned registry entries."""
    op = p.get("op")
    if op == "streaming":
        return rendermod.streaming_report()
    if op == "reconcile":
        return validatemod.reconcile(gc=p.get("gc", True))
    if op == "pie_census":
        return _pie_census(p)
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
    out = {"level": _ue.level_name(),
           "scope": "all" if include_all else "ueb",
           "count": sum(len(v) for v in groups.values()),
           "untracked": untracked,
           "actors": {k: sorted(v) for k, v in groups.items()}}
    # G22: the template's stowaway ground plane is acknowledged, not hidden — an agent
    # reading `scene` learns which ground its traces will answer to.
    proxies = _ue.engine_landscape_actors()
    if proxies:
        authored = any(_ue.find_by_label(l) is not None for l in _state.landscapes)
        out["engine_ground"] = (
            f"{len(proxies)} engine Landscape actor(s) form a template ground plane at z≈0"
            + ("; ground traces IGNORE it while your ueb terrain exists" if authored
               else "; with no ueb terrain it IS the ground every trace answers")
            + ("; currently HIDDEN (G37)" if landscape.template_hidden() else ""))
    return out


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
            # +GROUND_SEAT (G21): a deliberate hair above the trace — reads as resting,
            # never as coplanar-with-ground, so the placer and the z-fight band can't fight.
            target = [target[0], target[1], gz + half_z + validatemod.GROUND_SEAT]
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
    place, snap = _ground_flag(p.get("place") or {})
    yaw = p.get("yaw")
    facing = p.get("facing")

    if p.get("what") == "player_start":
        # G35 — before the label-unique check: relocate-or-create means re-running against
        # the existing start (same label) is legal, not a collision.
        if p.get("place") is None:
            snap = True                      # a start must stand ON the ground by default
        return _add_player_start(p, label, place, snap, yaw, facing)

    if _ue.find_by_label(label) is not None:
        return {"error": f"label '{label}' already exists (labels must be unique)"}

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


def _add_player_start(p, label, place, snap, yaw, facing):
    """G35: "where does the player drop in?" as a first-class placement. RELOCATE-or-create:
    the template level already ships a PlayerStart, and a second one silently wins or loses
    by priority — so an existing start is moved, never shadowed. Seated by the shared
    placement tail (capsule bottom on the traced ground), tagged ueb so scene/feel/view(map)
    see it, and facing/yaw give the spawn direction (bearing = UE yaw)."""
    w = _ue.editor_world()
    existing = list(unreal.GameplayStatics.get_all_actors_of_class(w, unreal.PlayerStart))
    holder = _ue.find_by_label(label)
    if holder is not None and holder not in existing:
        return {"error": f"label '{label}' already exists (labels must be unique)"}
    with _Txn("add") as txn:
        if existing:
            actor = holder if holder in existing else existing[0]
            relocated = True
        else:
            actor = _ue.actor_subsystem().spawn_actor_from_class(
                unreal.PlayerStart, unreal.Vector(0.0, 0.0, 0.0))
            relocated = False
        actor.set_actor_label(label)
        tags = list(actor.tags)
        if unreal.Name(_ue.UEB_TAG) not in tags:
            tags.append(unreal.Name(_ue.UEB_TAG))
            actor.tags = tags
        target = _place_actor(actor, place, yaw=yaw, snap_ground=snap, facing=facing)
        # The pawn spawns at the actor LOCATION, and the AABB includes editor-only sprite
        # components (~2.6× the capsule) — so the shared bounds-centre/bounds-min seat puts
        # the spawn point half a metre off the resolved point and floats the capsule ~40 cm.
        # Reseat by what actually matters: capsule centred ON the point, bottom at grade.
        cap = actor.get_component_by_class(unreal.CapsuleComponent)
        if cap is not None:
            z = actor.get_actor_location().z
            if snap:
                gz = _ue.trace_ground(target[0], target[1], ignore=actor)
                if gz is not None:
                    z = gz + cap.get_scaled_capsule_half_height() + validatemod.GROUND_SEAT
            target = [target[0], target[1], z]
            actor.set_actor_location(unreal.Vector(*target), False, False)
        _ue.actor_subsystem().set_selected_level_actors([actor])
    rot = actor.get_actor_rotation()
    op_id = _state.log_op(txn.op_id, "add",
                          f"player_start '{label}' at {[round(v) for v in target]}",
                          f"ueb add {label}")
    out = {"added": label, "kind": "player_start", "relocated": relocated,
           "at": [round(v, 1) for v in target],
           "facing_bearing_deg": round(rot.yaw % 360.0, 1), "op": op_id}
    if len(existing) > 1:
        out["warning"] = (f"{len(existing)} PlayerStarts in the level — the engine picks by "
                          f"priority; moved '{actor.get_actor_label()}', the others still "
                          "compete. Delete the extras or relocate them too.")
    return out


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
    if not is_bp:
        # G39: surface WPO/animation at author time — a mesh whose material moves it
        # (wind, plugin displacement) must say so in the same round-trip that placed it.
        motion = asset.motion_notes([path])
        if motion:
            out["notes"] = motion
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
    """Relational perception — describe(actor) / distance_between / gap_between / is_aligned,
    plus render_state (SPEC-03): the on-demand deep-dive behind the block's one-line render
    summary — walks the full gating chain for one actor/population + the fix. Delegates to
    relational.py (spatial math) / render.py (render chain)."""
    op = p.get("op")
    if op == "render_state":
        return rendermod.render_state(p.get("target"))
    # SPEC-03 computed visibility (link 8): framing/occlusion as NUMBERS off the editor
    # viewport camera — never a screenshot. Read-only, like the rest of feel.
    if op == "framing":
        return rendermod.framing(p.get("target"), p.get("fov", rendermod.EDITOR_FOV_DEG))
    if op == "visible":
        return rendermod.visible(p.get("target"), p.get("fov", rendermod.EDITOR_FOV_DEG))
    return relational.feel(p)


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


def _v_validate(p):
    """The correctness floor as a verb (SPEC-02). Read-only / registry-only — it IS
    perception, so it carries no status block of its own.
      op="run" (targets, verbose): sweep the whole scene (or targets) — the on-demand,
        uncapped tier of the always-on floor. Verdict + one finding per line, each w/ its fix.
      op="expect" (a, b, reason, check=penetration|ground, max_depth): declare a contact
        INTENDED — the only way to quiet a laden finding. z_fight is intent-free (rejected).
      op="forget" (a, b, check): retire a declaration (re-arms the finding).
      op="intended": list the live declared-intent registry."""
    return validatemod.handle(p)


def _v_history(p):
    """op: list | undo | undo_to.
      undo (n=1): "undo that" — issue N raw editor undos on the SHARED transaction stack,
        newest first, regardless of who made the edit. The editor's undo is shared with the
        human on purpose, so this reverses the last thing that happened — an agent op OR a
        human's own mistake ("can you undo that?"). Does NOT touch our 1:1 history counting
        (that's what undo_to is for); this is the blunt, human-facing button.
      undo_to (id): rewind exactly to one of OUR logged ops (count kept 1:1 with the stack).
    """
    op = p.get("op", "list")
    if op == "list":
        return {"history": _state.history}
    if op == "undo":
        n = int(p.get("n", 1))
        _ue.undo(n)
        # Deliberately does NOT touch _state.history: this can reverse a HUMAN edit that was
        # never in our log, and trimming our history then would corrupt undo_to's counting.
        # The shared stack is intended (a human wants "undo that" to just work); undo_to is
        # the precise, history-aware path.
        return {"undone": n, "note": f"issued {n} editor undo(s) on the shared stack "
                                     f"(reverses the last change, agent or human)"}
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
    "history": _v_history,
    "asset": _v_asset,
    "landscape": _v_landscape,
    "path": _v_path,
    "scatter": _v_scatter,
    "validate": _v_validate,
}
