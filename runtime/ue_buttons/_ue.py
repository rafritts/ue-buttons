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
