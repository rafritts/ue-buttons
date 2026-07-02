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
    return list(actor.get_components_by_class(unreal.PrimitiveComponent))


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
