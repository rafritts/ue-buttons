"""SPEC-06 — deixis: shared referents between the user and the agent.

The agent can't see; the user can't be expected to know actor labels for 400 scattered
instances. This module makes "this one" and "that thing over there" resolvable:

  selection()   the USER's live editor selection as full ueb-style entries. A foliage
                click lands on the level's InstancedFoliageActor — resolved down to its
                populated components (mesh, instance count, stand label, motion verdict),
                which the first live experiment proved is enough to diagnose (G39→G40).
  looking_at()  the editor viewport camera's forward ray, traced: "you're looking at X,
                N m away." Foliage hits resolve to (stand, instance_index) via the
                HitResult component + item — the per-instance read selection can't do.
  pie_where()   the same two questions for the PIE pawn: where the player is standing
                and what the player's camera is looking at, read from the GAME world
                (`play` is exempt from the B8 guard, so this works while the user plays).

Every entry carries `next` — ready-to-fire follow-up calls (the HATEOAS rule: a finding
that only describes is half-built).
"""
import math

import unreal

from . import _state
from . import _ue
from . import asset as assetmod
from . import foliage as foliagemod
from . import render as rendermod


# ── shared: attribute an actor/component/instance to what the USER would call it ──

def _spline_strips():
    """surface-strip actor label → owning spline label."""
    return {pd.get("surface_actor"): name for name, pd in _state.splines.items()
            if pd.get("surface_actor")}


def _stand_of(component):
    """The ueb foliage stand a component belongs to, from its ueb_scatter:<label> tag."""
    if component is None:
        return None
    try:
        tags = [str(t) for t in component.get_editor_property("component_tags")]
    except Exception:
        return None
    for t in tags:
        if t.startswith(foliagemod._FOLIAGE_TAG):
            return t[len(foliagemod._FOLIAGE_TAG):]
    return None


def _mesh_of(component):
    try:
        sm = component.get_editor_property("static_mesh")
        return sm.get_name() if sm else None
    except Exception:
        return None


def attribute(actor, component=None, item=None):
    """One hit/selection target → {what, label, …, next[]} in the user's vocabulary:
    a foliage instance, a ueb terrain, a trail strip, a placed actor, engine scaffolding."""
    if actor is None:
        return {"what": "nothing"}
    label = actor.get_actor_label()
    cls = actor.get_class().get_name()
    out = {"label": label, "class": cls}
    stand = _stand_of(component)
    if stand is not None:
        out["what"] = f"a foliage instance of stand '{stand}'"
        out["stand"] = stand
        if item is not None and item >= 0:
            out["instance_index"] = item
        mesh = _mesh_of(component)
        if mesh:
            out["mesh"] = mesh
        out["next"] = [f"feel op=render_state target={stand}",
                       f"foliage op=describe label={stand}"]
        return out
    if label in _state.terrains:
        out["what"] = "the ueb terrain"
        out["next"] = [f"terrain op=describe label={label}"]
        return out
    strips = _spline_strips()
    if label in strips:
        out["what"] = f"the surface strip of spline '{strips[label]}'"
        out["next"] = [f"spline op=describe label={strips[label]}"]
        return out
    if _ue.UEB_TAG in [str(t) for t in actor.tags]:
        out["what"] = "a placed ueb actor"
        out["next"] = [f"feel op=describe target={label}"]
        return out
    types = _ue._engine_ground_types()
    if types and isinstance(actor, types):
        out["what"] = "engine scaffolding (the template ground plane / HLOD)"
        return out
    out["what"] = "an untracked (non-ueb) actor"
    out["next"] = [f"feel op=describe target={label}"]
    return out


# ── selection-as-deixis: select op=user ─────────────────────────────────────────

def _ifa_entry(a):
    """A foliage click selects the whole InstancedFoliageActor; resolve it to the
    populated components — that resolution is most of the value (SPEC-06)."""
    comps = []
    for c in a.get_components_by_class(unreal.InstancedStaticMeshComponent):
        n = c.get_instance_count()
        if n == 0:
            continue
        mesh = _mesh_of(c)
        entry = {"mesh": mesh, "instances": n}
        stand = _stand_of(c)
        if stand:
            entry["stand"] = stand
        sm = None
        try:
            sm = c.get_editor_property("static_mesh")
        except Exception:
            pass
        if sm is not None:
            kind, note = assetmod._mesh_motion(sm)
            if kind is not None:
                entry["motion"] = kind
                entry["motion_note"] = note
        comps.append(entry)
    comps.sort(key=lambda e: -e["instances"])
    stands = sorted({e["stand"] for e in comps if e.get("stand")})
    return {"label": a.get_actor_label(), "class": "InstancedFoliageActor",
            "what": "the level's foliage container — a foliage click selects ALL of it, "
                    "resolved per component below",
            "components": comps, "stands": stands,
            "next": [f"feel op=render_state target={s}" for s in stands]
                    + ["feel op=looking_at  (to narrow to the ONE instance under the "
                       "user's viewport crosshair)"]}


def _actor_entry(a):
    e = attribute(a)
    b = _ue.bounds(a)
    if b["size"] != [0, 0, 0]:
        e["dims_cm"] = [round(v, 1) for v in b["size"]]
        e["at"] = [round(v, 1) for v in b["center"]]
    meshes, worst = set(), (None, None)
    for c in a.get_components_by_class(unreal.StaticMeshComponent):
        sm = None
        try:
            sm = c.get_editor_property("static_mesh")
        except Exception:
            pass
        if sm is None:
            continue
        meshes.add(sm.get_name())
        kind, note = assetmod._mesh_motion(sm)
        if assetmod._MOTION_RANK[kind] > assetmod._MOTION_RANK[worst[0]]:
            worst = (kind, note)
    if meshes:
        e["meshes"] = sorted(meshes)
    if worst[0] is not None:
        e["motion"] = worst[0]
        e["motion_note"] = worst[1]
    return e


def selection():
    """The user's live editor selection, resolved (select op=user)."""
    sel = _ue.actor_subsystem().get_selected_level_actors()
    if not sel:
        return {"selected": [],
                "note": "nothing is selected in the editor — ask the user to click the "
                        "thing ('select it for me') and re-issue select op=user"}
    entries = [(_ifa_entry(a) if isinstance(a, unreal.InstancedFoliageActor)
                else _actor_entry(a)) for a in sel]
    return {"selected": [a.get_actor_label() for a in sel], "entries": entries}


# ── camera-as-deixis: feel op=looking_at / play op=where ───────────────────────

_RAY_CM = 1_000_000.0     # 10 km — past that, "nothing" is the honest answer


def _ray_aabb(start, direction, bmin, bmax):
    """Slab test: t (cm along the ray) where it enters the AABB, or None."""
    tmin, tmax = 0.0, _RAY_CM
    for i in range(3):
        d = direction[i]
        if abs(d) < 1e-9:
            if start[i] < bmin[i] or start[i] > bmax[i]:
                return None
            continue
        t1, t2 = (bmin[i] - start[i]) / d, (bmax[i] - start[i]) / d
        if t1 > t2:
            t1, t2 = t2, t1
        tmin, tmax = max(tmin, t1), min(tmax, t2)
        if tmin > tmax:
            return None
    return tmin


def _foliage_ifas(world=None):
    if world is None:
        return [a for a in _ue.all_actors()
                if isinstance(a, unreal.InstancedFoliageActor)]
    return list(unreal.GameplayStatics.get_all_actors_of_class(
        world, unreal.InstancedFoliageActor))


def _foliage_along_ray(start, direction, max_t, world=None):
    """Nearest ueb foliage instance the ray passes through, or None. Foliage instances
    carry NoCollision (G46) so no trace can ever hit one — 'which tree' is answered by
    ray-vs-instance-AABB MATH over the stands' components instead (instance transforms +
    mesh bounds are ground truth; rotation is ignored, fine at deixis precision).
    Components are pruned by their bounding sphere before instances are walked."""
    best = None
    for a in _foliage_ifas(world):
        for c in a.get_components_by_class(unreal.InstancedStaticMeshComponent):
            stand = _stand_of(c)
            n = c.get_instance_count()
            if stand is None or n == 0:
                continue
            try:
                co, _, crad = unreal.SystemLibrary.get_component_bounds(c)
                t = sum((getattr(co, ax) - start[i]) * direction[i]
                        for i, ax in enumerate("xyz"))
                near = [start[i] + direction[i] * max(t, 0.0) for i in range(3)]
                if math.dist(near, (co.x, co.y, co.z)) > crad:
                    continue
            except Exception:
                pass
            sm = None
            try:
                sm = c.get_editor_property("static_mesh")
            except Exception:
                pass
            if sm is None:
                continue
            mb = sm.get_bounds()
            mo, me = mb.origin, mb.box_extent
            for i in range(n):
                tr = c.get_instance_transform(i, True)
                loc, s = tr.translation, tr.scale3d
                ctr = (loc.x + mo.x * s.x, loc.y + mo.y * s.y, loc.z + mo.z * s.z)
                ext = (abs(me.x * s.x), abs(me.y * s.y), abs(me.z * s.z))
                t = _ray_aabb(start, direction,
                              [ctr[k] - ext[k] for k in range(3)],
                              [ctr[k] + ext[k] for k in range(3)])
                if t is not None and 1.0 < t < max_t and (best is None or t < best[0]):
                    best = (t, stand, sm.get_name(), i,
                            [round(loc.x, 1), round(loc.y, 1), round(loc.z, 1)])
    return best


def _trace_full(world, start, direction):
    """Visibility-channel trace returning the FULL HitResult dict (component + item are
    what resolve a foliage hit to one instance). Keys read defensively — to_dict() key
    names drift across engine versions."""
    end = (start[0] + direction[0] * _RAY_CM, start[1] + direction[1] * _RAY_CM,
           start[2] + direction[2] * _RAY_CM)
    hr = unreal.SystemLibrary.line_trace_single(
        world, unreal.Vector(*start), unreal.Vector(*end),
        unreal.TraceTypeQuery.ECC_VISIBILITY, True, unreal.Array(unreal.Actor),
        unreal.DrawDebugTrace.NONE, True)
    if not hr:
        return None
    d = hr.to_dict()
    loc = d.get("location") or d.get("impact_point")
    item = d.get("item", d.get("hit_item", -1))
    return {"location": loc,
            "actor": d.get("hit_actor") or d.get("actor"),
            "component": d.get("hit_component") or d.get("component"),
            "item": int(item) if item is not None else -1}


def _ray_answer(world, start, direction, game_world=None):
    hit = _trace_full(world, start, direction)
    max_t = (math.dist(start, (hit["location"].x, hit["location"].y, hit["location"].z))
             if hit is not None and hit["location"] is not None else _RAY_CM)
    # G46: foliage has no collision — a tree between the camera and the traced hit is
    # invisible to the trace. The math pass wins whenever an instance sits NEARER.
    fol = _foliage_along_ray(start, direction, max_t, world=game_world)
    if fol is not None:
        t, stand, mesh, idx, iloc = fol
        dist_m = round(t / 100.0, 1)
        return {"looking_at": {"what": f"a foliage instance of stand '{stand}'",
                               "stand": stand, "mesh": mesh, "instance_index": idx,
                               "instance_at": iloc,
                               "next": [f"feel op=render_state target={stand}",
                                        f"foliage op=describe label={stand}"]},
                "distance_m": dist_m,
                "resolved_by": "ray-vs-instance-bounds math (foliage carries no "
                               "collision — G46 — so no trace can hit it)",
                "verdict": f"looking at a '{mesh}' of stand '{stand}' "
                           f"(instance {idx}), {dist_m} m away"}
    if hit is None or hit["location"] is None:
        return {"looking_at": {"what": "nothing"},
                "verdict": "nothing within 10 km along the forward ray (sky)"}
    loc = hit["location"]
    pt = [round(loc.x, 1), round(loc.y, 1), round(loc.z, 1)]
    dist_m = round(max_t / 100.0, 1)
    at = attribute(hit["actor"], hit["component"], hit["item"])
    return {"looking_at": at, "hit_point": pt, "distance_m": dist_m,
            "verdict": f"looking at {at.get('what', '?')}"
                       + (f" — '{at['label']}'" if at.get("label") else "")
                       + f", {dist_m} m away"}


def looking_at():
    """What the EDITOR viewport camera points at (feel op=looking_at). The trace is the
    render's own ground truth — same provenance discipline as framing/visible."""
    cam = rendermod._camera()
    loc, fwd = cam[0], cam[1]
    out = _ray_answer(_ue.editor_world(), (loc.x, loc.y, loc.z), (fwd.x, fwd.y, fwd.z))
    out["camera"] = {"at": [round(loc.x, 1), round(loc.y, 1), round(loc.z, 1)],
                     "basis": "editor perspective viewport "
                              "(get_level_viewport_camera_info)"}
    return out


def _game_world():
    try:
        gw = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
    except Exception:
        gw = None
    if gw is None:
        try:
            gw = unreal.EditorLevelLibrary.get_game_world()
        except Exception:
            gw = None
    return gw


def pie_where():
    """Where the PIE pawn stands + what the player camera looks at (play op=where).
    Reads the GAME world — usable mid-Play while the user is walking the level."""
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.is_in_play_in_editor():
        return {"error": "not in Play — op=where reads the PIE pawn (start Play, or ask "
                         "while the user is playing)"}
    gw = _game_world()
    if gw is None:
        return {"error": "could not resolve the PIE game world"}
    pawn = unreal.GameplayStatics.get_player_pawn(gw, 0)
    if pawn is None:
        return {"error": "no player pawn in the game world"}
    ploc = pawn.get_actor_location()
    out = {"standing": [round(ploc.x, 1), round(ploc.y, 1), round(ploc.z, 1)],
           "pawn": pawn.get_class().get_name()}
    cm = unreal.GameplayStatics.get_player_camera_manager(gw, 0)
    if cm is not None:
        cloc = cm.get_camera_location()
        fwd = cm.get_camera_rotation().get_forward_vector()
        ray = _ray_answer(gw, (cloc.x, cloc.y, cloc.z), (fwd.x, fwd.y, fwd.z),
                          game_world=gw)
        out.update(ray)
        out["note"] = ("labels are the PIE world's runtime copies — map them back to "
                       "editor actors by position, not name")
    return out
