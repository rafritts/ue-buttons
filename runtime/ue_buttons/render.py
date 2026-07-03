"""SPEC-03 — render legibility: the third forced sense (UE edition).

Ports blender-buttons' render-gating doctrine (`extension/lint.py`, `objects.py`,
`common.py`) to UE: answer "will this draw, is it framed, is it big enough" as NUMBERS
and BOOLEANS computed from the state that produces the frame — never by reading a render
back. The image is for the human; LLM vision self-confirms and launders the very mistake
you're checking for (blender-buttons `render.py` header). So the render sense verifies
WITHOUT a frame, and never WITH one.

The single most important steal is architectural, not a verb: **renderability is a filter
at the SOURCE of every physical read**, so a non-renderable actor can never silently
poison a spatial answer (blender-buttons G147 — a hidden mesh chosen as a support
surface). `is_renderable()` below is that predicate; the validate floor consumes it to
fill its reserved `[N excluded]` slot, and never lets a skipped actor go unnamed.

This module is the SPINE the spec (docs/SPEC-03) names as build-order-critical: the
source-filter predicate + the gating-chain walk + the `render:` status line (Sense 3) +
the `[N excluded]` handshake with SPEC-02. Three links have no reliable UE-Python binding
and are DEFERRED — but NAMED on the line rather than silently skipped (the spec's own
discipline: a floor is never silent about its own blind spots):

  • link 1  Resident (full WorldPartition cell / data-layer residency) — needs the
            WorldPartitionSubsystem; this editor's World exposes no `get_world_partition`,
            so residency is reported only as the coarse actor `is_spatially_loaded` hint.
  • link 2  Registered (has a scene proxy — the G14 HISM lesson) — no Python binding
            (`is_registered` / `is_render_state_created` are absent on PrimitiveComponent).
            The scatter path already FORCES registration by routing through the foliage
            subsystem (scatter.py G14); `was_recently_rendered` exists but is unreliable in
            a non-focused editor viewport, so registration is not gated here yet.
  • link 8  On-screen size + the camera family (framing / occlusion / visible-surface) —
            `GameplayStatics.project_world_to_screen` is present; this is the next
            increment, folded into `view` (view framing / view visible).

Everything here was probed live against UE 5.8 before being coded (derived, not divined):
`is_temporarily_hidden_in_editor()`, component `is_visible()` / `visible` /
`hidden_in_game`, `min_draw_distance` / `ld_max_draw_distance` / `bounds_scale` via
`get_editor_property`, `get_num_materials` / `get_material(i)`, StaticMesh
`get_num_triangles(0)` / `get_num_lods()` / `nanite_settings.enabled`.
"""
import math

import unreal

from . import _ue
from . import _state

# The engine's fallback materials — their presence in a slot is the "someone forgot to
# assign" tell (blender-buttons flags `"no material slot"`, lint.py:345). BasicShapeMaterial
# is a REAL material (the M1 primitive path uses it), so it must NOT be on this list.
_DEFAULT_MATERIALS = {
    "/Engine/EngineMaterials/DefaultMaterial.DefaultMaterial",
    "/Engine/EngineMaterials/WorldGridMaterial.WorldGridMaterial",
}

# The render floor can be turned off, but silence-because-off must never read as
# silence-because-drawing — so an OFF floor announces itself on every block (SPEC-03).
RENDER_FLOOR = True


def _prop(obj, name, default=None):
    """get_editor_property that never raises — some flags exist on the default object but
    not as instance attributes (probed: `bounds_scale`, `min_draw_distance`)."""
    try:
        return obj.get_editor_property(name)
    except Exception:
        return default


def _prim_components(actor):
    """RENDERABLE primitives only: editor-only components (a PlayerStart's sprite/arrow)
    never draw at runtime, and shape components (its capsule) are collision wireframes —
    judging their visibility flags nags 'component visibility off' on actors that are
    perfectly healthy gameplay markers (G35)."""
    return [c for c in actor.get_components_by_class(unreal.PrimitiveComponent)
            if not bool(_prop(c, "is_editor_only", False))
            and not isinstance(c, unreal.ShapeComponent)]


# ── the gating chain, per primitive component ──────────────────────────────────
# A primitive draws IFF every hard link holds. Each check returns (ok, detail) — ok False
# is a break; detail is the human-facing reason + fix. Ordered cheapest/most-common first
# (SPEC-03 §"the gating chain"): shown → bounded → in-range → materialised → render-data.

def _link_shown(c, actor):
    """viewport_visible and render_visible are DIFFERENT flags and are never conflated
    (blender-buttons objects.py:1126-1131) — checking one while trusting the other is the
    exact miss that made this spec. Report which channel is off."""
    editor_hidden = actor.is_temporarily_hidden_in_editor()
    comp_visible = bool(c.is_visible())
    game_hidden = bool(_prop(c, "hidden_in_game", False)) or bool(_prop(actor, "hidden", False))
    if editor_hidden and not comp_visible:
        return False, "hidden in editor AND not render-visible → unhide (both channels)"
    if editor_hidden:
        return False, "hidden in the editor viewport → unhide (Show/H); draws at runtime"
    if not comp_visible:
        return False, "component visibility off → set visible=true"
    if game_hidden:
        return False, "hidden_in_game → clears in editor but WON'T render at runtime → unset hidden_in_game"
    return True, None


def _link_bounded(c, actor):
    b = _ue.bounds(actor)
    if b["size"] == [0, 0, 0] or all(s == 0 for s in b["size"]):
        return False, "zero-extent world bounds (no footprint to draw) → check mesh/scale"
    return True, None


def _link_in_range(c, actor):
    """Cull-distance sanity. Full camera-relative culling is link 8 (deferred); here we
    flag only unambiguous misconfigurations that cull regardless of viewpoint: a near-cull
    (min_draw_distance > 0 hides it when close) or a max-cull smaller than the object's own
    size (it culls before you could ever resolve it)."""
    min_d = _prop(c, "min_draw_distance", 0.0) or 0.0
    ld_max = _prop(c, "ld_max_draw_distance", 0.0) or 0.0
    if min_d and min_d > 0:
        return False, f"min_draw_distance={round(min_d,1)}cm — culls when the camera is close → set 0"
    if ld_max and ld_max > 0:
        span = max(_ue.bounds(actor)["size"] or [0])
        if ld_max < span:
            return False, (f"max_draw_distance={round(ld_max,1)}cm < the object's own "
                           f"{round(span,1)}cm span — culls before it resolves → raise/clear it")
    return True, None


def _link_materialised(c):
    """Every slot resolves to a real material; flag a null slot or an engine default
    substituting (the "forgot to assign" tell). Only meaningful on mesh components."""
    if not hasattr(c, "get_num_materials"):
        return True, None
    try:
        n = c.get_num_materials()
    except Exception:
        return True, None
    for i in range(n):
        m = c.get_material(i)
        if m is None:
            return False, f"material slot {i} is empty → assign a material"
        if m.get_path_name() in _DEFAULT_MATERIALS:
            return False, (f"slot {i} is the engine DEFAULT material (unassigned — renders "
                           f"as flat grey) → assign the intended material")
        # G32(b): a non-surface domain (decal/UI/post-process) on a mesh slot passes the
        # null check but renders wrong or not at all — the "materialised: ok" white lie.
        try:
            base = m.get_base_material()
            dom = base.get_editor_property("material_domain") if base else None
        except Exception:
            dom = None
        if dom is not None and dom != unreal.MaterialDomain.MD_SURFACE:
            return False, (f"slot {i} material domain is {str(dom).split('.')[-1]} — not a "
                           "surface material; it won't render on a mesh → assign a "
                           "surface-domain material (asset describe vets one)")
    return True, None


def _link_render_data(c):
    """LOD0 has geometry. Only StaticMeshComponent carries a queryable mesh; other
    primitives (foliage handled separately) pass rather than false-flag."""
    if not isinstance(c, unreal.StaticMeshComponent):
        return True, None
    sm = _prop(c, "static_mesh", None)
    if sm is None:
        return False, "no static mesh assigned → set a mesh"
    try:
        tris = sm.get_num_triangles(0)
    except Exception:
        tris = None
    if tris == 0:
        return False, "mesh LOD0 has 0 triangles (empty render data) → reimport/repair the mesh"
    return True, None


_HARD_LINKS = ("shown", "bounded", "in_range", "materialised", "render_data")


def _walk_component(c, actor):
    """All hard-link verdicts for one primitive component. Returns
    {name: {ok, detail}, ...} plus draws:bool and the ordered list of breaks."""
    checks = {
        "shown": _link_shown(c, actor),
        "bounded": _link_bounded(c, actor),
        "in_range": _link_in_range(c, actor),
        "materialised": _link_materialised(c),
        "render_data": _link_render_data(c),
    }
    links = {k: {"ok": ok, "detail": d} for k, (ok, d) in checks.items()}
    breaks = [(k, checks[k][1]) for k in _HARD_LINKS if not checks[k][0]]
    return {"links": links, "draws": not breaks, "breaks": breaks}


def walk_actor(actor):
    """Walk the gating chain for an actor. An actor DRAWS iff it has ≥1 primitive component
    that passes every hard link. Reports the first break on the best (fewest-breaks)
    component, so the fix named is the one nearest to making it draw. `resident` rides
    along as the coarse WP hint (link 1, partial)."""
    comps = _prim_components(actor)
    resident = _prop(actor, "is_spatially_loaded", True)
    if not comps:
        if list(actor.get_components_by_class(unreal.PrimitiveComponent)):
            # Only editor-only sprites / collision shapes: a gameplay MARKER (PlayerStart).
            # Nothing is supposed to draw at runtime, so nothing is broken (G35).
            return {"label": actor.get_actor_label(), "draws": True, "comps": 0,
                    "resident": resident, "first_break": None, "marker": True,
                    "components": []}
        return {"label": actor.get_actor_label(), "draws": False, "comps": 0,
                "resident": resident, "first_break": ("bounded", "no primitive component to draw"),
                "components": []}
    walked = [(c, _walk_component(c, actor)) for c in comps]
    drawing = [w for _, w in walked if w["draws"]]
    best = min(walked, key=lambda cw: len(cw[1]["breaks"]))
    first_break = None if drawing else best[1]["breaks"][0]
    return {
        "label": actor.get_actor_label(),
        "draws": bool(drawing),
        "comps": len(comps),
        "resident": resident,
        "first_break": first_break,
        "components": [{"name": c.get_name(), **w} for c, w in walked],
    }


# ── the source-filter predicate (the architectural steal) ──────────────────────

def is_renderable(actor):
    """The renderability gate consumed at the source of every physical read (SPEC-03) and
    by the validate floor's `[N excluded]` slot. True iff the actor draws by the reliably
    computable hard links. A non-renderable actor must never silently answer a trace or a
    spatial check as if it were part of the scene."""
    try:
        return walk_actor(actor)["draws"]
    except Exception:
        return True   # never let a predicate error EXCLUDE an actor (fail open, but loud elsewhere)


def excluded_actors(actors):
    """The subset of `actors` that are NOT renderable — what the floor skipped. The floor
    names these rather than pretending it saw them."""
    return [a for a in actors if not is_renderable(a)]


# ── Sense 3: the render line for the status block ──────────────────────────────

def render_line(labels):
    """The `render:` status line — Sense 3, sibling of the validate line. Report by
    exception: `render: DRAWS` when the touched delta is clean, the first break + its fix
    when not, and `render: OFF — floor is down` when disabled (silence-because-off can
    never read as silence-because-drawing). Delta-scoped to the acted-on label(s)."""
    if not RENDER_FLOOR:
        return "render: OFF — floor is down"
    actors = [_ue.find_by_label(l) for l in labels if l]
    actors = [a for a in actors if a is not None]
    if not actors:
        return None
    findings = []
    for a in actors:
        w = walk_actor(a)
        if not w["draws"]:
            link, detail = w["first_break"]
            findings.append(f"{w['label']}: {link} — {detail}")
    if not findings:
        return "render: DRAWS"
    shown = "; ".join(findings[:4])
    more = "" if len(findings) <= 4 else f" …(+{len(findings)-4}; feel op=render_state to walk one)"
    return "⚠ render: " + shown + more


def render_state(target):
    """The on-demand deep-dive behind the one-line summary — `feel op=render_state
    target=…`. Walks the full chain for one actor (or scatter population) and returns the
    per-link verdict + the fix. As `feel` is the detail behind the spatial line, this is
    the detail behind the render line."""
    if target in _state.scatters:
        return population_state(target)
    a = _ue.find_by_label(target)
    if a is None:
        return {"error": f"no actor or population labelled '{target}'"}
    w = walk_actor(a)
    lines = []
    for comp in w["components"]:
        for name in _HARD_LINKS:
            lk = comp["links"][name]
            mark = "ok" if lk["ok"] else "BREAK"
            lines.append(f"{comp['name']}.{name}: {mark}"
                         + (f" — {lk['detail']}" if lk["detail"] else ""))
    return {"target": target, "draws": w["draws"], "resident": w["resident"],
            "comps": w["comps"], "chain": lines,
            "deferred": ["registered (link2: no binding)", "on-screen size (link8: view increment)"],
            "verdict": "DRAWS" if w["draws"] else f"WILL NOT DRAW — {w['first_break'][0]}"}


# ── scatter populations (the motivating case: 6,236 reported, nothing drew) ─────

def population_state(label):
    """Walk a scatter population's foliage: total instances and whether their components
    are visible. This is the exact blindness that made the spec — a population correct in
    every data probe that draws nothing. Registration is guaranteed by scatter's foliage
    path (G14), so the catchable failures here are 0-instances and hidden components."""
    from . import scatter as scattermod
    tag = scattermod._SCATTER_TAG + label
    total, comps, hidden = 0, 0, 0
    for c in scattermod._ifa_fismcs():
        if tag not in [str(t) for t in c.get_editor_property("component_tags")]:
            continue
        comps += 1
        total += c.get_instance_count()
        if not c.is_visible():
            hidden += 1
    if comps == 0:
        return {"target": label, "kind": "population", "draws": False, "instances": 0,
                "components": 0, "verdict": "WILL NOT DRAW — no registered foliage components "
                "(nothing was committed) → regenerate"}
    draws = total > 0 and hidden < comps
    verdict = "DRAWS" if draws else (
        "WILL NOT DRAW — 0 instances placed → widen region/relax rules" if total == 0
        else f"WILL NOT DRAW — all {comps} components hidden → unhide foliage")
    return {"target": label, "kind": "population", "draws": draws, "instances": total,
            "components": comps, "hidden_components": hidden, "verdict": verdict}


def population_line(label):
    """The Sense-3 line for a scatter edit: the population walked as it was committed."""
    if not RENDER_FLOOR:
        return "render: OFF — floor is down"
    st = population_state(label)
    if st.get("draws"):
        return f"render: DRAWS — population '{label}' {st['instances']} instances / {st['components']} comps"
    return "⚠ render: " + f"population '{label}' — {st['verdict']}"


# ── link 1: streaming / residency (SPEC-03 §"scene gains streaming/residency") ──────
# The collection-scoped blindness the surface most lacks: a build correct by every per-actor
# metric that renders as nothing because its population lives in an unloaded data layer or an
# unstreamed WP cell. `WorldPartitionBlueprintLibrary` is the reachable entry point (the
# WorldPartitionSubsystem is a *world* subsystem, which Python's get_editor/engine_subsystem
# can't fetch). Honest scope: this reports partition status + data-layer effective runtime
# states + per-actor residency (is_spatially_loaded / runtime_grid) — all reliably testable.
# GATING an actor non-renderable on an assigned data layer's Unloaded state is NOT wired: the
# dogfood map is partitioned but has zero data layers, so the DataLayerAsset→instance
# resolution call can't be derived against anything real yet (derived, not divined). Wire it
# the day a map ships a data layer; until then residency is the is_spatially_loaded hint.

def _data_layer_manager():
    try:
        return unreal.WorldPartitionBlueprintLibrary.get_data_layer_manager(_ue.editor_world())
    except Exception:
        return None


def _spatially_loaded(actor):
    try:
        return bool(actor.is_spatially_loaded)
    except Exception:
        return True


def streaming_report():
    """The WorldPartition streaming/residency picture: is the world partitioned, its data
    layers + effective runtime state, and per-ueb-actor residency. On a non-partitioned map,
    says so plainly (everything is always resident) — silence-because-N/A never reads as a
    clean streaming state."""
    dlm = _data_layer_manager()
    partitioned = dlm is not None
    layers = []
    if partitioned:
        try:
            for di in dlm.get_data_layer_instances():
                try:
                    st = str(dlm.get_data_layer_instance_effective_runtime_state(di)).split(".")[-1]
                except Exception:
                    st = "?"
                layers.append({"layer": str(di), "effective_state": st})
        except Exception:
            pass
    bounds = None
    try:
        b = unreal.WorldPartitionBlueprintLibrary.get_editor_world_bounds()
        if getattr(b, "is_valid", False):
            bounds = {"min": [round(b.min.x, 1), round(b.min.y, 1), round(b.min.z, 1)],
                      "max": [round(b.max.x, 1), round(b.max.y, 1), round(b.max.z, 1)]}
    except Exception:
        pass
    actors = []
    for a in _ue.ueb_actors():
        try:
            grid = str(a.get_editor_property("runtime_grid"))
            grid = None if grid in ("None", "") else grid
        except Exception:
            grid = None
        actors.append({"label": a.get_actor_label(), "resident": _spatially_loaded(a),
                       "runtime_grid": grid})
    unloaded = [l for l in layers if l["effective_state"].upper() not in ("ACTIVATED", "?")]
    note = ("world-partitioned; residency would gate on data-layer runtime state, but this "
            "map has no data layers → every placed actor is resident"
            if partitioned and not layers else
            "world-partitioned" if partitioned else
            "not world-partitioned — everything is always resident (streaming N/A)")
    return {"partitioned": partitioned, "world_bounds": bounds,
            "data_layers": layers, "data_layer_count": len(layers),
            "unloaded_layers": unloaded, "actors": actors, "note": note}


# ── link 8: computed visibility — the camera family (SPEC-03 §computed visibility) ──
# blender-buttons computes framing / occlusion / size entirely from matrix math + raycasts
# over the evaluated geometry — NEVER a screenshot (world_to_camera_view, common.py:545;
# _occlusion_fraction, introspect.py:524). Ported: project the world AABB through the editor
# perspective viewport camera to answer "is it framed, is it big enough, is it actually
# seen" as numbers. This distinguishes, without a frame, the four cases the surface couldn't
# tell apart in Level 1: sub-pixel vs off-frustum vs occluded vs genuinely absent.
#
# Provenance (SPEC-20 / G22/G36): a coverage % is meaningless without its reference — it
# shifts silently with resolution/FOV — so every framing number states the viewport it was
# projected against (resolution + FOV) and reads the ACTUAL editor viewport camera. UE's
# editor perspective viewport FOV is not queryable via the Python subsystems, so it defaults
# to the editor's 90° and is OVERRIDABLE + always stamped, never hidden.

EDITOR_FOV_DEG = 90.0   # UE editor perspective viewport default (horizontal); stamped in provenance


def _camera(hfov_deg=EDITOR_FOV_DEG):
    """The live editor perspective-viewport camera — the render's own ground truth (G36).
    Returns (loc, fwd, rgt, up, (w,h), hfov_deg)."""
    ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    loc, rot = ues.get_level_viewport_camera_info()
    vp = ues.get_level_viewport_size()
    w, h = (vp.x or 1920), (vp.y or 1080)
    return (loc, rot.get_forward_vector(), rot.get_right_vector(), rot.get_up_vector(),
            (w, h), hfov_deg)


def _corner_pts(b):
    """The 8 world-space AABB corners as [x,y,z]."""
    xs = (b["min"][0], b["max"][0]); ys = (b["min"][1], b["max"][1]); zs = (b["min"][2], b["max"][2])
    return [[x, y, z] for x in xs for y in ys for z in zs]


def _provenance(cam):
    loc, fwd, _, _, (w, h), hfov = cam
    return {"camera": [round(loc.x, 1), round(loc.y, 1), round(loc.z, 1)],
            "resolution": [w, h], "fov_h_deg": hfov,
            "basis": "editor perspective viewport (get_level_viewport_camera_info); FOV is "
                     "the editor default unless overridden — every coverage % is relative to it"}


def framing(target, hfov_deg=EDITOR_FOV_DEG):
    """Project a target's world AABB through the editor viewport camera → screen coverage,
    clipping, and behind-camera, all as numbers (blender-buttons camera_coverage). frac_w/
    frac_h are the 'too small to see' and 'is it framed' figures; est_px_* is the sub-pixel
    tell. Never renders a frame."""
    a = _ue.find_by_label(target)
    if a is None:
        return {"error": f"no actor labelled '{target}'"}
    b = _ue.bounds(a)
    if b["size"] == [0, 0, 0]:
        return {"error": f"'{target}' has zero extent — nothing to frame"}
    cam = _camera(hfov_deg)
    loc, fwd, rgt, up, (w, h), hfov = cam
    aspect = w / float(h)
    th = math.tan(math.radians(hfov) / 2.0)
    tv = th / aspect
    us, vs, depths = [], [], []
    for p in _corner_pts(b):
        vx, vy, vz = p[0] - loc.x, p[1] - loc.y, p[2] - loc.z
        depth = vx * fwd.x + vy * fwd.y + vz * fwd.z
        depths.append(depth)
        if depth > 1e-3:
            rx = vx * rgt.x + vy * rgt.y + vz * rgt.z
            uy = vx * up.x + vy * up.y + vz * up.z
            us.append(((rx / depth) / th + 1) / 2.0)      # frame fraction, 0=left 1=right
            vs.append((1 - (uy / depth) / tv) / 2.0)      # 0=top 1=bottom
    in_front = any(d > 0 for d in depths)
    if not us:      # every corner behind the camera
        return {"target": target, "in_front": False, "on_frame": False,
                "verdict": "OFF-FRAME — entirely behind the camera → aim the editor viewport at it",
                "provenance": _provenance(cam)}
    umin, umax, vmin, vmax = min(us), max(us), min(vs), max(vs)
    frac_w, frac_h = round(umax - umin, 4), round(vmax - vmin, 4)
    est_px_w, est_px_h = round(frac_w * w, 1), round(frac_h * h, 1)
    clipped = [e for e, cond in (("left", umin < 0), ("right", umax > 1),
                                 ("top", vmin < 0), ("bottom", vmax > 1)) if cond]
    on_frame = umax > 0 and umin < 1 and vmax > 0 and vmin < 1
    partly_behind = any(d <= 0 for d in depths)
    if not on_frame:
        verdict = "OFF-FRAME — projects outside the viewport → recentre the camera"
    elif est_px_w < 1 or est_px_h < 1:
        verdict = f"SUB-PIXEL — ~{est_px_w}×{est_px_h}px, too small to see → move closer or scale up"
    elif clipped:
        verdict = f"CLIPPED on {'/'.join(clipped)} — spills past the frame edge"
    else:
        verdict = "FRAMED"
    return {"target": target, "in_front": in_front, "on_frame": on_frame,
            "frac_w": frac_w, "frac_h": frac_h, "est_px": [est_px_w, est_px_h],
            "clipped": clipped, "partly_behind_camera": partly_behind,
            "verdict": verdict, "provenance": _provenance(cam)}


def visible(target, hfov_deg=EDITOR_FOV_DEG):
    """Is the target actually SEEN from the viewport, or hidden behind other geometry — a
    raycast question, not a render (blender-buttons _occlusion_fraction). Traces from the
    camera to sampled points on the target's AABB, ignoring the target itself; a hit on
    OTHER geometry nearer than the point = occluded. Composes with framing: off-frame or
    sub-pixel is reported first (occlusion of an unframed thing is moot)."""
    fr = framing(target, hfov_deg)
    if "error" in fr:
        return fr
    a = _ue.find_by_label(target)
    b = _ue.bounds(a)
    cam = _camera(hfov_deg)
    loc = cam[0]
    start = (loc.x, loc.y, loc.z)
    pts = [b["center"]] + _corner_pts(b)
    occluded, total, behind = 0, 0, 0
    for p in pts:
        dpt = math.dist(start, p)
        if dpt < 1.0:
            continue
        total += 1
        hit = _ue.trace_hit(start, p, ignore=[a])
        if hit is not None:
            dhit = math.dist(start, (hit.x, hit.y, hit.z))
            if dhit < dpt - 5.0:        # other geometry in the way (5cm noise floor)
                occluded += 1
    frac = round(occluded / total, 3) if total else 1.0
    seen = fr["on_frame"] and frac < 1.0
    if not fr["on_frame"]:
        verdict = "NOT SEEN — " + fr["verdict"]
    elif frac >= 1.0:
        verdict = "NOT SEEN — fully occluded behind other geometry"
    elif frac > 0:
        verdict = f"PARTLY SEEN — {int(frac*100)}% of sampled points occluded"
    else:
        verdict = "SEEN — clear line of sight from the viewport"
    return {"target": target, "seen": seen, "occluded_fraction": frac,
            "samples": total, "framing": fr["verdict"], "verdict": verdict,
            "provenance": _provenance(cam)}
