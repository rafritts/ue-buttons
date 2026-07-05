"""SPEC-04 — level lifecycle: save / new / open / clear.

The ueb registries live in the editor Python process, NOT in the level (SPEC-03), and
every op here changes which level those registries are supposed to describe. Hence the
two laws this module enforces:

- the dirty guard: `new`/`open` never silently discard unsaved level work — they refuse
  and report what's dirty; `save=true` (save first) or `force=true` (explicit discard)
  are the only ways through. blender-buttons' history-desync wipe of a 27-op build is
  the cautionary tale; a whole level doubly so.
- reconcile rides every transition: `new`/`open`/`clear` run SPEC-03's reconcile so the
  registries can never describe a level that is no longer loaded (the G16 phantom,
  structurally closed). The op-log/intents side is `_level_guard` (G23) in verbs.py,
  which fires on the same dispatch because the level name changed under it.

`op=new` also bakes the G36 cure: `new_level_from_template` copies the template's
always-loaded env actors (sun/sky/fog/PlayerStart) with descriptors that never load in
PIE — a level that reads perfect in the editor and Plays as an unlit void. The cure,
proven live on L1, is to delete the copies and respawn the set fresh.
"""
import unreal

from . import _state
from . import _ue
from . import terrain as terrainmod
from . import foliage as foliagemod
from . import pcg as pcgmod
from . import validate as validatemod

_WP_TEMPLATE = "/Engine/Maps/Templates/OpenWorld"

# The template's always-loaded environment set (the G36 offenders) — deleted and
# respawned fresh by op=new, and deliberately NOT ueb-tagged: they are the level's
# scaffolding (op=clear keeps them), not part of any arrangement.
_ENV_CLASSES = (unreal.DirectionalLight, unreal.SkyLight, unreal.SkyAtmosphere,
                unreal.VolumetricCloud, unreal.ExponentialHeightFog, unreal.PlayerStart)


def handle(p):
    op = p.get("op")
    if op == "save":
        return _save(p)
    if op == "new":
        return _new(p)
    if op == "open":
        return _open(p)
    if op == "clear":
        return _clear(p)
    return {"error": f"unknown level op '{op}'. known: streaming|save|new|open|clear"}


# ── shared ───────────────────────────────────────────────────────────────────────
def _les():
    return unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)


def _pkg_name():
    w = _ue.editor_world()
    return w.get_package().get_name() if w else "?"


def _untitled(pkg):
    return pkg.startswith("/Temp/")


def _dirty_maps():
    return [pk.get_name() for pk in
            unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages()]


def _dirty_content():
    return [pk.get_name() for pk in
            unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()]


def _guard(p):
    """The SPEC-04 dirty guard for ops that abandon the current level. Guards on dirty
    MAP packages (the work a transition would discard); dirty content (authored MIs,
    FoliageTypes) is reported for context but never blocks — abandoning the level
    doesn't lose it."""
    if p.get("force"):
        return None
    maps = _dirty_maps()
    if not maps:
        return None
    if p.get("save"):
        res = _save({"path": p.get("save_path")})
        return res if "error" in res else None
    out = {"error": "the current level has UNSAVED changes — refusing to discard them "
                    "silently (SPEC-04 dirty guard)",
           "dirty_maps": maps,
           "next": "level op=save to keep the work (path='/Game/Maps/<Name>' if the level "
                   "is Untitled), or save=true to save-and-proceed in one call "
                   "(save_path= if Untitled), or force=true to discard it explicitly"}
    content = _dirty_content()
    if content:
        out["dirty_content_fyi"] = content
    return out


def _restamp(clear_log):
    """Keep verbs._level_guard's stamp honest across a lifecycle op: a save-as RENAMES
    the level without changing its arrangement (the op log must survive), while
    new/open swap the arrangement out entirely (the log dies here, reported on this
    op's own result — not one dispatch later by the guard)."""
    if hasattr(_state, "level_stamp"):
        _state.level_stamp[0] = _ue.level_name()
    else:
        _state.level_stamp = [_ue.level_name()]
    if not clear_log:
        return None
    n_ops, n_int = len(_state.history), len(_state.intents)
    _state.history.clear()
    _state._undone.clear()
    _state.intents.clear()
    _state.drift[0] = 0.0
    _state.last_dispatch = None
    return (f"{n_ops} logged op(s) + {n_int} declared intent(s) cleared — they "
            "described the previous level's arrangement (G23)")


def _transition_reconcile():
    """Reconcile-on-transition (never optional): GC registry entries orphaned by the
    level change, then rehydrate terrain meta and pcg groves for actors living in the
    NEWLY loaded level, and reassert the G37/B15 template hide+sink."""
    rec = validatemod.reconcile(gc=True)
    _state.engine_grounds_memo = None    # ground attribution changed (B3/G22)
    terrainmod._hydrate()
    # B16: reassert the template hide/sink HERE, unconditionally — _hydrate only reaches
    # its own reassert when the registry was empty, and a same-labeled terrain surviving
    # the transition (every level names its terrain "terrain") skips it, leaving the
    # incoming level's white z=0 plane rendering AND answering physics (B15).
    if _state.terrains:
        terrainmod.set_template_hidden(True)
    pcgmod._hydrate()
    orphaned = rec.get("orphaned", [])
    return {"orphaned_gcd": len(orphaned),
            "detail": [f"{o['kind']}:{o['label']}" for o in orphaned],
            "rehydrated_terrains": sorted(_state.terrains),
            "rehydrated_groves": sorted(getattr(_state, "pcg_volumes", {}))}


# ── save ─────────────────────────────────────────────────────────────────────────
def _save(p):
    """Save the current level (+ external actor packages and dirty content). An unsaved
    Untitled needs a destination: path='/Game/Maps/<Name>' (save-as; also works to
    save-as an already-named level)."""
    world = _ue.editor_world()
    pkg = _pkg_name()
    path = p.get("path")
    before = {"maps": _dirty_maps(), "content": _dirty_content()}
    if _untitled(pkg) and not path:
        return {"error": f"the level is an unsaved '{_ue.level_name()}' with no home — "
                         "pass path='/Game/Maps/<Name>' to give it one (save-as)"}
    if path:
        if not unreal.EditorLoadingAndSavingUtils.save_map(world, path):
            return {"error": f"editor refused to save the map as '{path}'"}
    # sweep the rest: WP external actor packages ride the map flag; authored content
    # (FoliageTypes, material instances) rides the content flag (default on — saving
    # never loses work).
    unreal.EditorLoadingAndSavingUtils.save_dirty_packages(
        True, bool(p.get("content", True)))
    _restamp(clear_log=False)    # a rename must not cost the op log
    out = {"level": _pkg_name(),
           "saved_maps": before["maps"] or ([path] if path else []),
           "saved_content": before["content"] if p.get("content", True) else []}
    if path and path != pkg:
        out["was"] = pkg
    left = _dirty_maps() + (_dirty_content() if p.get("content", True) else [])
    if left:
        out["still_dirty"] = left
    return out


# ── new ──────────────────────────────────────────────────────────────────────────
def _new(p):
    """Fresh level at path= — a clone of the World-Partition Open World template (never a
    non-WP blank: a blank map silently loses streaming/data layers/the residency the
    render sense reads), with the G36 env-set cure applied and the result saved."""
    path = p.get("path")
    if not path:
        return {"error": "op=new needs path='/Game/Maps/<Name>' — where the new level "
                         "will be saved"}
    g = _guard(p)
    if g:
        return g
    old = _pkg_name()
    template = p.get("template", _WP_TEMPLATE)
    if not _les().new_level_from_template(path, template):
        return {"error": f"editor refused new_level_from_template('{path}', '{template}')"}
    env = _rebuild_env()
    unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, False)
    return {"level": _pkg_name(), "was": old, "template": template,
            "environment": env, "state_reset": _restamp(clear_log=True),
            "reconcile": _transition_reconcile(), "saved": True}


def _rebuild_env():
    """The G36 cure: the template's copied always-loaded env actors never load in PIE
    (unlit void + origin spawn while every editor read says fine). Delete the copies,
    respawn the set fresh — same recipe that fixed L1 live. play op=census is the
    mechanical proof afterward."""
    eas = _ue.actor_subsystem()
    removed = []
    for a in list(_ue.all_actors()):
        if isinstance(a, _ENV_CLASSES):
            removed.append(a.get_actor_label())
            eas.destroy_actor(a)

    spawned = []

    def sp(cls, label, z=0.0):
        a = eas.spawn_actor_from_class(cls, unreal.Vector(0.0, 0.0, z))
        a.set_actor_label(label)
        spawned.append(label)
        return a

    sun = sp(unreal.DirectionalLight, "sun", z=5000.0)
    sun.set_actor_rotation(unreal.Rotator(roll=0.0, pitch=-45.0, yaw=45.0), False)
    sc = sun.get_component_by_class(unreal.DirectionalLightComponent)
    sc.set_editor_property("mobility", unreal.ComponentMobility.MOVABLE)
    sc.set_editor_property("atmosphere_sun_light", True)

    sky = sp(unreal.SkyLight, "sky_light", z=5000.0)
    kc = sky.get_component_by_class(unreal.SkyLightComponent)
    kc.set_editor_property("mobility", unreal.ComponentMobility.MOVABLE)
    kc.set_editor_property("real_time_capture", True)

    sp(unreal.SkyAtmosphere, "sky_atmosphere")
    sp(unreal.VolumetricCloud, "clouds")
    fog = sp(unreal.ExponentialHeightFog, "height_fog")
    fog.get_component_by_class(unreal.ExponentialHeightFogComponent) \
       .set_editor_property("fog_density", 0.02)
    sp(unreal.PlayerStart, "player_start", z=100.0)

    return {"g36_cure": "template env set deleted, respawned fresh",
            "removed": removed, "spawned": spawned,
            "proof": "play op=census after building — game world must equal editor set"}


# ── open ─────────────────────────────────────────────────────────────────────────
def _open(p):
    path = p.get("path")
    if not path:
        return {"error": "op=open needs path='/Game/Maps/<Name>'"}
    if not unreal.EditorAssetLibrary.does_asset_exist(path):
        return {"error": f"no level asset at '{path}'",
                "next": "level op=new path=... to create one"}
    g = _guard(p)
    if g:
        return g
    old = _pkg_name()
    if not _les().load_level(path):
        return {"error": f"editor refused to load '{path}'"}
    return {"level": _pkg_name(), "was": old,
            "state_reset": _restamp(clear_log=True),
            "reconcile": _transition_reconcile()}


# ── clear ────────────────────────────────────────────────────────────────────────
def _clear(p):
    """Wipe MY arrangement, keep the map: every ueb-tagged actor (terrains, spline
    strips, placed actors) and every ueb_scatter-tagged foliage population — engine
    scaffolding untouched, the G37 template ground restored. The transition-scale state
    reset (op log, intents) that _level_guard does on a level CHANGE happens inline
    here, because the level name doesn't change under a clear.

    THE INVARIANT (learned live, first MCP clear): an UNSAVED clear must be fully
    undone by reopening the level from disk. So clear touches ONLY level-scoped state —
    never terrain disk meta (pruning it orphaned the reopened valley's heightfield) and
    never content assets (deleting FoliageTypes would leave a reopened forest's
    instances pointing at nothing; asset deletion doesn't reopen-undo). Stale meta is
    harmless (_hydrate adopts only labels whose actor exists); orphaned FT assets are
    recreated fresh by the next paint of the same label."""
    eas = _ue.actor_subsystem()

    # foliage: clear instances by component tag only — registered stands and
    # unregistered debris die the same way (the tag lives on the component).
    stands = {label: meta.get("count", "?")
              for label, meta in sorted(_state.foliage_stands.items())}
    _state.foliage_stands.clear()
    swept = 0
    for c in foliagemod._ifa_fismcs():
        tags = [str(t) for t in c.get_editor_property("component_tags")]
        if c.get_instance_count() > 0 and \
                any(t.startswith(foliagemod._FOLIAGE_TAG) for t in tags):
            c.clear_instances()
            swept += 1

    # every ueb-tagged actor: placed actors, spline surface strips, terrain meshes.
    actors = {}
    for a in list(_ue.ueb_actors()):
        cls = a.get_class().get_name()
        actors[cls] = actors.get(cls, 0) + 1
        eas.destroy_actor(a)

    # registries + the G37 template ground (disk meta deliberately untouched — see
    # the invariant above).
    n_splines = len(_state.splines)
    _state.splines.clear()
    n_terrains = len(_state.terrains)
    _state.terrains.clear()
    # pcg groves: the volume actor (destroyed above by the ueb-tag sweep) owns its
    # generated instances, so the sweep already tore them down; just drop the registry.
    groves = getattr(_state, "pcg_volumes", {})
    n_groves = len(groves)
    groves.clear()
    shown = terrainmod.set_template_hidden(False)

    # op log / intents: they describe the arrangement that just ceased to exist.
    reset = _restamp(clear_log=True)

    out = {"cleared": {"actors": actors, "foliage_stands": stands,
                       "foliage_components_swept": swept,
                       "splines": n_splines, "terrains": n_terrains,
                       "pcg_groves": n_groves},
           "state_reset": f"{reset} — the editor's own Ctrl+Z stack is the human's; "
                          "don't undo across a clear",
           "reconcile": _transition_reconcile()}
    if shown:
        out["template_ground"] = (f"restored {shown} engine template Landscape actor(s) "
                                  "as the visible ground (G37)")
    return out
