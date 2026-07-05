"""Thin wrappers over the `unreal` API — the only module that touches editor internals.

All distances are centimetres (UE native — never converted). Reloadable: holds no
state, so a hot-reload is harmless. Conventions (SPEC-00): +X forward, +Y right, +Z up,
rotation as yaw/pitch/roll degrees.
"""
import unreal

# BasicShapes meshes are 100 cm cubes/… → half-extent 50. dims_cm / 100 = scale factor.
BASIC_SHAPES = {
    "cube": "/Engine/BasicShapes/Cube",
    "sphere": "/Engine/BasicShapes/Sphere",
    "cylinder": "/Engine/BasicShapes/Cylinder",
    "cone": "/Engine/BasicShapes/Cone",
    "plane": "/Engine/BasicShapes/Plane",
}
NATIVE_EXTENT_CM = 50.0  # half-size of a BasicShapes mesh at scale 1

# Every ueb-spawned actor carries this tag, so perception (scene/feel) can scope to our
# arrangement instead of the engine's scaffolding (gaps.md G7: Open World maps ship ~135
# Landscape/HLOD actors with sprawling AABBs). Tags live on the actor → survive restart.
UEB_TAG = "ueb"


def actor_subsystem():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)


def editor_world():
    # G3: UnrealEditorSubsystem, not the deprecated EditorLevelLibrary.get_editor_world.
    return unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()


def all_actors():
    return actor_subsystem().get_all_level_actors()


def ueb_actors():
    """Actors this runtime spawned (carry UEB_TAG) — the default perception scope."""
    return [a for a in all_actors() if UEB_TAG in [str(t) for t in a.tags]]


def find_by_label(label):
    """First actor whose label == `label`, or None. Rescan every call (G-labels): the
    user can rename in-editor at any time, so a cached map would go stale. O(n) is fine
    at M1 scene sizes."""
    for a in all_actors():
        if a.get_actor_label() == label:
            return a
    return None


def bounds(actor):
    """World-space AABB in cm as a plain dict. `get_actor_bounds(only_colliding=False)`
    returns (origin, box_extent); we expand to min/max/size/center so the relational
    math never re-derives it. Zero-extent (non-spatial) actors are the caller's problem
    to filter (gaps.md G2)."""
    origin, extent = actor.get_actor_bounds(False)
    cx, cy, cz = origin.x, origin.y, origin.z
    ex, ey, ez = extent.x, extent.y, extent.z
    return {
        "center": [cx, cy, cz],
        "size": [ex * 2, ey * 2, ez * 2],
        "min": [cx - ex, cy - ey, cz - ez],
        "max": [cx + ex, cy + ey, cz + ez],
    }


def support_point(actor, b=None):
    """Where the actor meets the ground: [x, y, base_z]. Normally the AABB centre/min-z;
    for a capsule-only gameplay marker (PlayerStart) it is the CAPSULE's axis and bottom —
    the editor sprite/arrow components inflate the AABB ~40 cm past (and off-centre of)
    the capsule, so raw bounds read as 'buried' on a perfectly seated start and trace the
    grade half a metre from where the pawn actually stands (G35)."""
    cap = actor.get_component_by_class(unreal.CapsuleComponent)
    if cap is not None and actor.get_component_by_class(unreal.StaticMeshComponent) is None:
        loc = actor.get_actor_location()
        return [loc.x, loc.y, loc.z - cap.get_scaled_capsule_half_height()]
    b = b if b is not None else bounds(actor)
    return [b["center"][0], b["center"][1], b["min"][2]]


def load_asset(path):
    """EditorAssetLibrary.load_asset with a fallback: freshly created-and-saved assets
    (e.g. GeometryScript-baked static meshes) can sit in the registry while
    EditorAssetLibrary still refuses them until an editor restart; unreal.load_asset
    resolves them fine. Prefer this everywhere over the raw call."""
    m = unreal.EditorAssetLibrary.load_asset(path)
    if m is None:
        try:
            m = unreal.load_asset(path)
        except Exception:
            m = None
    return m


def spawn_basic_shape(shape, location):
    """Spawn a BasicShapes actor at a world location (cm). Returns the actor. Caller
    sets label + scale inside the surrounding transaction."""
    path = BASIC_SHAPES[shape]
    mesh = load_asset(path)
    loc = unreal.Vector(location[0], location[1], location[2])
    actor = actor_subsystem().spawn_actor_from_object(mesh, loc)
    actor.tags = [unreal.Name(UEB_TAG)]     # scope tag for perception (gaps.md G7)
    return actor


def set_scale_for_dims(actor, dims_cm):
    """Scale a freshly-spawned BasicShapes actor so its world size == dims_cm."""
    s = unreal.Vector(dims_cm[0] / 100.0, dims_cm[1] / 100.0, dims_cm[2] / 100.0)
    actor.set_actor_scale3d(s)


# ── project-asset spawning (SPEC-01 E2) ─────────────────────────────────────────
def spawn_static_mesh(mesh_path, location):
    """Spawn a project StaticMesh actor at a world location (cm), tagged ueb. Placed at
    NATIVE scale — marketplace dims are placement information, not a resize invitation."""
    mesh = load_asset(mesh_path)
    if not isinstance(mesh, unreal.StaticMesh):
        raise ValueError(f"'{mesh_path}' is not a StaticMesh ({type(mesh).__name__})")
    actor = actor_subsystem().spawn_actor_from_object(
        mesh, unreal.Vector(location[0], location[1], location[2]))
    actor.tags = [unreal.Name(UEB_TAG)]
    return actor


def spawn_blueprint(class_path, location):
    """Spawn a Blueprint actor from its generated class at a world location (cm). A prebuilt
    cabin BP comes in as ONE actor — one thing to relate to (SPEC-01)."""
    cls = unreal.EditorAssetLibrary.load_blueprint_class(class_path)
    if cls is None:
        raise ValueError(f"'{class_path}' has no Blueprint class")
    actor = actor_subsystem().spawn_actor_from_class(
        cls, unreal.Vector(location[0], location[1], location[2]))
    actor.tags = [unreal.Name(UEB_TAG)]
    return actor


def native_size(actor):
    """World-space size (cm) of an actor at its current scale — used to derive a scale
    factor when the caller explicitly overrides dims on an arbitrary mesh."""
    return bounds(actor)["size"]


def pivot_to_center_delta(actor):
    """Vector (world AABB center − actor location). Zero for centered-pivot BasicShapes,
    but a base-pivot tree/wall has its centre well above (and off from) its origin. Callers
    that want the *bounds centre* at a target must set location = target − this delta
    (gaps.md G4). Read it AFTER scale+rotation so it reflects the actor's real footprint."""
    c = bounds(actor)["center"]
    loc = actor.get_actor_location()
    return [c[0] - loc.x, c[1] - loc.y, c[2] - loc.z]


def _ignore_list(ignore):
    """Normalize the `ignore` arg (None | actor | iterable-of-actors) → a clean list."""
    if ignore is None:
        return []
    if isinstance(ignore, (list, tuple, set)):
        return [a for a in ignore if a is not None]
    return [ignore]


def trace_hit(start, end, ignore=None):
    """Physics-aware world ray trace start→end (both [x,y,z] cm), returning the hit point
    as an `unreal.Vector` or None. Same EditorToolset backend as `trace_ground` (hits WP
    landscape proxies; raw KismetSystemLibrary line traces don't). `ignore` excludes actors
    — pass the target to test what's BETWEEN the camera and it (SPEC-03 occlusion)."""
    from editor_toolset.toolsets.scene import SceneTools
    return SceneTools._trace_world(editor_world(), unreal.Vector(*start),
                                   unreal.Vector(*end), _ignore_list(ignore))


def _trace_with_actor(start, end, ignore):
    """Like trace_hit, but returns (location, hit_actor) so the caller can ATTRIBUTE the
    hit (B3: 'z=0.0' was a legitimate hit on the WRONG ground — attribution is the cure).
    Same visibility-channel trace the SceneTools backend runs."""
    arr = unreal.Array(unreal.Actor)
    arr.extend(ignore or [])
    hr = unreal.SystemLibrary.line_trace_single(
        editor_world(), unreal.Vector(*start), unreal.Vector(*end),
        unreal.TraceTypeQuery.ECC_VISIBILITY, True, arr, unreal.DrawDebugTrace.NONE, True)
    if not hr:
        return None, None
    d = hr.to_dict()
    return d["location"], (d.get("hit_actor") or d.get("actor"))


# The engine-scaffolding classes that form the template's collidable ground plane at z=0
# (B3/G22): the Landscape tree AND its WorldPartitionHLOD proxies — probed live, the actual
# z=0 hit on a fresh Open World map is `WorldPartitionHLOD` (HLOD0_Instancing/...), not the
# LandscapeStreamingProxy itself.
_ENGINE_GROUND_CLASSES = ("LandscapeProxy", "WorldPartitionHLOD")


def _engine_ground_types():
    return tuple(c for c in (getattr(unreal, n, None) for n in _ENGINE_GROUND_CLASSES) if c)


def engine_landscape_actors():
    """Every engine-scaffolding ground actor (Landscape tree + WP HLOD proxies). A 'blank'
    Open World template ships ~65 of them — a real collidable ground plane at z=0 that wins
    any trace whose true authored surface lies below zero (bugs.md B3 / gaps.md G22)."""
    types = _engine_ground_types()
    return [a for a in all_actors() if isinstance(a, types)] if types else []


def _engine_grounds_memo(refresh=False):
    """Per-level memo of the engine ground actors (a full-actor scan per trace would tax
    a paint's ~50k traces). HLOD actors stream in/out, so callers refresh when a hit actor
    isn't covered; the level guard clears it on level change."""
    from . import _state
    lvl = level_name()
    memo = getattr(_state, "engine_grounds_memo", None)
    if not refresh and memo is not None and memo[0] == lvl:
        return memo[1]
    acts = engine_landscape_actors()
    _state.engine_grounds_memo = (lvl, acts)
    return acts


def _authored_terrain_exists():
    from . import _state
    from . import terrain
    terrain._hydrate()
    return any(find_by_label(l) is not None for l in _state.terrains)


def substrate_labels():
    """Every label that is a SUBSTRATE, not a placed actor: terrains, foliage stands, spline
    labels, spline surface strips, and pcg grove volumes (deliberately tall — SPEC-10
    invariant 1 — so the ground lint would read them as buried, B11). Shared by validate's
    neighbor pool, foliage's clearance builder, and the map's marker filter — one
    definition, no drift."""
    from . import _state
    subs = (set(_state.terrains) | set(_state.foliage_stands) | set(_state.splines)
            | set(getattr(_state, "pcg_volumes", {})))
    for pd in _state.splines.values():
        sa = pd.get("surface_actor")
        if sa:
            subs.add(sa)
    # The registries die with the session but the LEVEL outlives it (the G47 relaunch
    # taught this): a reopened level's terrain read as a floating actor. Class is the
    # durable tell — the runtime spawns ueb DynamicMeshActors ONLY as terrains and
    # spline surface strips, and ueb PCGVolumes only as grove volumes, so every one
    # of them is a substrate.
    for a in ueb_actors():
        if isinstance(a, (unreal.DynamicMeshActor, unreal.PCGVolume)):
            subs.add(a.get_actor_label())
    return subs


def trace_ground(x, y, ignore=None, top=200000.0, bottom=-200000.0):
    """World z of the ground directly under (x, y), or None if nothing is beneath the ray.

    Delegates to Epic EditorToolset's `SceneTools._trace_world` (M2 eval: adopt as a hidden
    backend — it's a physics-aware world query that beats what we'd hand-roll against RC,
    and unlike raw KismetSystemLibrary line traces it actually hits WorldPartition landscape
    proxies). `ignore` is a single actor OR an iterable of actors excluded from the trace
    — so a caller can hit the SUBSTRATE beneath by ignoring every placed actor (gaps.md
    G18), not just skip self.

    B3/G22 attribution loop: when the winning hit is ENGINE scaffolding (the template
    Landscape / its WP HLOD proxies) while an authored ueb terrain exists, the scaffolding
    family is excluded and the ray re-fired — the template's z=0 plane must never shadow
    the authored ground. With no ueb terrain the engine plane honestly IS the ground."""
    ig = _ignore_list(ignore)
    types = _engine_ground_types()
    for attempt in range(3):
        loc, actor = _trace_with_actor((x, y, top), (x, y, bottom), ig)
        if loc is None:
            return None
        if (not types or actor is None or not isinstance(actor, types)
                or not _authored_terrain_exists()):
            return loc.z
        # engine ground answered: exclude the whole family (refresh the memo if it missed
        # this very actor — HLODs stream) and retrace
        grounds = _engine_grounds_memo(refresh=(attempt > 0))
        ig = ig + grounds
    return loc.z    # still scaffolding after retries — honest fallback, never None


def undo(n=1):
    """Drive the editor's undo from Python — the ONLY verified path (probed live 2026-07-02):
    the console command `TRANSACTION UNDO`. No `unreal.*` undo primitive exists. Each call
    pops one transaction off the shared stack; keeping our history 1:1 with that stack is
    what makes counting undos correct (gaps.md G1)."""
    world = editor_world()
    for _ in range(max(0, n)):
        unreal.SystemLibrary.execute_console_command(world, "TRANSACTION UNDO")


def level_name():
    world = editor_world()
    return world.get_name() if world else "?"


def package_name():
    """Full package path of the current editor level, e.g. '/Game/Maps/UEB_PCGForest'
    (or '/Temp/Untitled_0' for an unsaved level). Unlike level_name(), this is unique
    across folders — the right key for per-level persisted state (B17)."""
    world = editor_world()
    return world.get_package().get_name() if world else "?"


