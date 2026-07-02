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


def spawn_basic_shape(shape, location):
    """Spawn a BasicShapes actor at a world location (cm). Returns the actor. Caller
    sets label + scale inside the surrounding transaction."""
    path = BASIC_SHAPES[shape]
    mesh = unreal.EditorAssetLibrary.load_asset(path)
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
    mesh = unreal.EditorAssetLibrary.load_asset(mesh_path)
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


def trace_ground(x, y, ignore=None, top=200000.0, bottom=-200000.0):
    """World z of the ground directly under (x, y), or None if nothing is beneath the ray.

    Delegates to Epic EditorToolset's `SceneTools._trace_world` (M2 eval: adopt as a hidden
    backend — it's a physics-aware world query that beats what we'd hand-roll against RC,
    and unlike raw KismetSystemLibrary line traces it actually hits WorldPartition landscape
    proxies). `ignore` is a single actor OR an iterable of actors excluded from the trace
    — so a caller can hit the SUBSTRATE beneath by ignoring every placed actor (gaps.md
    G18), not just skip self."""
    from editor_toolset.toolsets.scene import SceneTools
    if ignore is None:
        ignore_list = []
    elif isinstance(ignore, (list, tuple, set)):
        ignore_list = [a for a in ignore if a is not None]
    else:
        ignore_list = [ignore]
    hit = SceneTools._trace_world(
        editor_world(), unreal.Vector(x, y, top), unreal.Vector(x, y, bottom), ignore_list)
    return None if hit is None else hit.z


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


def _win_to_wsl(path):
    """C:\\Users\\... → /mnt/c/Users/... so the WSL server can read the NTFS file."""
    p = path.replace("\\", "/")
    if len(p) > 1 and p[1] == ":":
        return f"/mnt/{p[0].lower()}{p[2:]}"
    return p


def screenshot(width=1280, height=720):
    """Trigger a high-res viewport screenshot. ASYNC — UE writes the PNG on a later
    frame, so we return the expected path and let the WSL server poll /mnt/c for it
    (SPEC-00 risk note). Filename is unique per call via the op counter."""
    import os
    from . import _state
    saved = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_saved_dir())
    shots = os.path.join(saved, "Screenshots")
    name = f"ueb_{_state.next_shot_id()}.png"
    full = os.path.normpath(os.path.join(shots, name))
    unreal.AutomationLibrary.take_high_res_screenshot(width, height, full)
    return {"screenshot_win": full, "screenshot_wsl": _win_to_wsl(full), "async": True}
