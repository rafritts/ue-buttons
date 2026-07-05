"""`pcg` — UE's PCG framework as an intent verb (SPEC-10).

NATIVE: wraps the engine's Procedural Content Generation system. A ueb-tagged PCGVolume
sized to a surface carries a code-authored palette graph; `generate` fires the graph's
`PCGComponent` and the graph populates the volume with instanced meshes (ISM components
on the volume actor). Ops mirror the component's own API — generate / regenerate /
cleanup — plus the read-only describe / palette.

BOUNDARIES (SPEC-10): terrain carves, spline routes, pcg populates. `pcg` never sculpts
geometry and never authors networks (roads/rivers are `spline`'s); it samples a surface
and spawns assets onto it.

Palette graphs are code-authored: duplicate a stock PCG graph template into /Game/UEB_PCG,
tune its node settings in Python, save. No node editor, no user_parameters (5.8's stock
graphs expose none). The /Game copy is the asset of record — the user can open it in the
PCG editor at any time; only OUR authoring path is code.

INVARIANTS (each violation produced a real zero-instances failure in the spike):
  1. the volume must be TALL — a thin box yields zero instances (the sampler ray-casts
     over the Z extent). ±6000 cm worked; ±1000 gave nothing.
  2. spawn the volume at its FINAL transform, then generate — moving a generated volume
     and regenerating leaves stale state that produces zero.
  3. drive the PCGComponent directly — there is no PCGSubsystem in 5.8 Python.
  4. never mutate a shared /Game/UEB_PCG palette asset per call — per-grove variation
     (seed) rides the component, not the graph.

Spatial verb: status block, not history-undoable; teardown is op=cleanup.
"""
import time

import unreal

from . import _state
from . import _ue
from . import asset

_PCG_DIR = "/Game/UEB_PCG"                  # where materialized palette graphs live

# The volume box, unscaled, is ±100 cm — so scale3d = half_extents / 100.
_UNSCALED_HALF_CM = 100.0
# The sampler ray-casts the full Z extent; a thin volume yields ZERO (invariant 1).
_MIN_Z_HALF_CM = 6000.0
_Z_HEADROOM_CM = 2000.0


# ── palette (code-authored graphs) ────────────────────────────────────────────────
def _tune_mixed_sparse(graph):
    """Cut every surface sampler's density 8× — reproduces the proven 44k-instance
    mixed forest (331k stock seedlings → ~44k) so a grove never lands as wall-to-wall
    undergrowth. Relative tree/seedling ratio is preserved (scale, not clamp)."""
    for node in graph.nodes:
        s = node.get_settings()
        if isinstance(s, unreal.PCGSurfaceSamplerSettings):
            cur = s.get_editor_property("points_per_squared_meter")
            s.set_editor_property("points_per_squared_meter", cur * 0.125)


PALETTE = {
    "mixed_sparse": {
        "source": "/PCG/GraphTemplates/TPL_Showcase_SimpleForest",
        "tune": _tune_mixed_sparse,
        "meshes": "stock SimpleForest (PCG_Tree_01..03, PCG_Seedling_01, PCG_Boulder_02)",
        "density_note": "stock density cut 8x -> ~44k instances over a 300 m surface",
    },
}


def _palette_list():
    return [{"name": n, "source": e["source"], "meshes": e["meshes"],
             "density_note": e["density_note"]} for n, e in sorted(PALETTE.items())]


def _materialize(name):
    """Ensure /Game/UEB_PCG/<name> exists: duplicate the stock source, tune it, save.
    Idempotent — the /Game copy is the asset of record. Returns (path, error)."""
    dest = f"{_PCG_DIR}/{name}"
    if unreal.EditorAssetLibrary.does_asset_exist(dest):
        return dest, None
    entry = PALETTE[name]
    src = entry["source"]
    if _ue.load_asset(src) is None:
        return None, (f"palette source '{src}' for '{name}' will not load — the PCG "
                      "plugin's graph templates may be unavailable in this project")
    if unreal.EditorAssetLibrary.duplicate_asset(src, dest) is None:
        return None, f"could not duplicate '{src}' -> '{dest}'"
    graph = _ue.load_asset(dest)
    try:
        entry["tune"](graph)
    except Exception as e:
        return None, f"tuning '{name}' failed: {e}"
    unreal.EditorAssetLibrary.save_asset(dest)
    return dest, None


# ── registry (never-reloaded _state — guarded init, same pattern as _state.follow) ──
def _reg():
    if not hasattr(_state, "pcg_volumes"):
        _state.pcg_volumes = {}     # {label: {graph, on, seed, region, actor_name, counts}}
    return _state.pcg_volumes


def _hydrate():
    """Adopt ueb PCGVolume actors absent from the registry (G61) — the LEVEL outlives
    the session, and terrains already rehydrate on open while groves silently vanished
    from perception (regenerate refused, roster undercounted). Everything the ops need
    lives ON the actor: the graph asset (palette name = its basename under /Game/UEB_PCG),
    the component's seed, the live instance count, the actor bounds. `on` and `region`
    are not recoverable — `on` falls back to the sole registered terrain, region to None
    (display-only after generation; the volume is already sized)."""
    reg = _reg()
    terrains = sorted(_state.terrains)
    for a in _ue.ueb_actors():
        if not isinstance(a, unreal.PCGVolume):
            continue
        label = a.get_actor_label()
        if label in reg:
            continue
        comp = a.pcg_component
        g = comp.get_graph()
        gpath = g.get_path_name().split(".")[0] if g else None
        gname = (gpath[len(_PCG_DIR) + 1:] if gpath and gpath.startswith(_PCG_DIR + "/")
                 else gpath)
        b = _ue.bounds(a)
        reg[label] = {"graph": gname, "on": terrains[0] if len(terrains) == 1 else "?",
                      "seed": int(comp.get_editor_property("seed")),
                      "region": None, "actor_name": a.get_path_name(),
                      "coverage": {"x": [round(b["min"][0], 1), round(b["max"][0], 1)],
                                   "y": [round(b["min"][1], 1), round(b["max"][1], 1)]},
                      "wind_off": False, "pending": False,
                      "instances": _instance_total(a), "counts": {}}


def _unknown_label(label):
    """Unknown-label error WITH the next legal moves (G60): the live grove labels and
    the ready-to-fire commands, mirroring the unknown-graph error's palette list."""
    groves = sorted(_reg())
    return {"error": f"no pcg grove labelled '{label}'", "groves": groves,
            "next": ([f"pcg op=describe label={groves[0]}", "pcg op=describe   (every grove)"]
                     if groves else
                     [f"pcg op=generate graph=<palette name> label={label}",
                      "pcg op=palette   (lists the palette graphs)"])}


# ── dispatch ──────────────────────────────────────────────────────────────────────
def handle(p):
    _hydrate()      # G61: adopt level-resident groves after a restart (terrain.py:238 twin)
    fn = {"generate": _generate, "regenerate": _regenerate, "cleanup": _cleanup,
          "describe": _describe, "palette": _palette}.get(p.get("op", "generate"))
    if fn is None:
        return {"error": f"unknown pcg op '{p.get('op')}'. known: "
                         "generate|regenerate|cleanup|describe|palette"}
    return fn(p)


def _palette(p):
    return {"palette": _palette_list()}


# ── volume geometry ─────────────────────────────────────────────────────────────
def _region_bbox(region):
    """XY bbox (minx, miny, maxx, maxy) of a placement region — reuses foliage's region
    vocabulary (circle/rect/polygon). The volume is a box, so a circle/polygon region
    clips to its bounding box."""
    kind = region.get("kind")
    if kind == "circle":
        ax, ay = region["at"]; r = region["radius"]
        return ax - r, ay - r, ax + r, ay + r
    if kind == "rect":
        ax, ay = region["at"]; w, h = region["size"]
        return ax - w / 2, ay - h / 2, ax + w / 2, ay + h / 2
    if kind == "polygon":
        xs = [x for x, _ in region["points"]]; ys = [y for _, y in region["points"]]
        return min(xs), min(ys), max(xs), max(ys)
    raise ValueError(f"unknown region kind '{kind}' (circle|rect|polygon)")


def _volume_transform(surface_bounds, region):
    """(location Vector, scale3d Vector, coverage) for a tall box covering the surface
    AABB in XY (clipped by region if given) and spanning its Z with generous headroom."""
    mn, mx = surface_bounds["min"], surface_bounds["max"]
    x0, y0, x1, y1 = mn[0], mn[1], mx[0], mx[1]
    if region:
        rx0, ry0, rx1, ry1 = _region_bbox(region)
        x0, y0, x1, y1 = max(x0, rx0), max(y0, ry0), min(x1, rx1), min(y1, ry1)
        if x1 <= x0 or y1 <= y0:
            raise ValueError("region does not overlap the surface AABB — nothing to grow "
                             "on; widen the region or drop it to cover the whole surface")
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    hx, hy = max((x1 - x0) / 2.0, 1.0), max((y1 - y0) / 2.0, 1.0)
    z_span = mx[2] - mn[2]
    hz = max(_MIN_Z_HALF_CM, z_span / 2.0 + _Z_HEADROOM_CM)
    cz = (mn[2] + mx[2]) / 2.0
    loc = unreal.Vector(cx, cy, cz)
    scale = unreal.Vector(hx / _UNSCALED_HALF_CM, hy / _UNSCALED_HALF_CM,
                          hz / _UNSCALED_HALF_CM)
    return loc, scale, {"x": [round(x0, 1), round(x1, 1)], "y": [round(y0, 1), round(y1, 1)]}


# ── census + motion audit ────────────────────────────────────────────────────────
def _volume_isms(vol):
    return vol.get_components_by_class(unreal.InstancedStaticMeshComponent)


def _instance_total(vol):
    return sum(c.get_instance_count() for c in _volume_isms(vol))


def _settle(vol, budget_s=30.0):
    """Poll the volume's instance total until stable across two reads (bounded). By the
    time this runs (the COLLECT call, a dispatch after the fire), the editor has ticked
    and generation has landed; the poll just guards a residual in-flight tail. Returns the
    settled total.

    Note: PCG generate/cleanup are ASYNCHRONOUS — they advance only when the editor ticks,
    which cannot happen inside a single blocking dispatch (Python holds the game thread).
    So a fresh generate is fired in one call and its census collected in the next (the G30
    job pattern, mirroring `play op=census`)."""
    prev, cur, t0 = -1, _instance_total(vol), time.time()
    while cur != prev and (time.time() - t0) < budget_s:
        prev = cur
        cur = _instance_total(vol)
    return cur


def _census_and_motion(vol, wind_off, apply=True):
    """Walk the volume's ISM components -> per-mesh census with a motion verdict. When
    apply=True, also apply the G58 WPO-disable cure: a pivot_wpo mesh (G40 rigid float
    under instancing) gets world_position_offset_disable_distance=1 on its component;
    wind_off forces the disable on ALL components. Plain wpo (wind sway) is left live but
    reported. apply=False is the read-only path (describe): classify, never mutate."""
    agg = {}     # mesh_name -> {count, motion, comps:[component]}
    for c in _volume_isms(vol):
        n = c.get_instance_count()
        if n == 0:
            continue
        mesh = c.get_editor_property("static_mesh")
        if mesh is None:
            continue
        name = mesh.get_name()
        rec = agg.get(name)
        if rec is None:
            kind, _note = asset._mesh_motion(mesh)
            rec = agg[name] = {"count": 0, "motion": kind, "comps": []}
        rec["count"] += n
        rec["comps"].append(c)
    stilled = 0
    if apply:
        for name, rec in agg.items():
            if wind_off or rec["motion"] == "pivot_wpo":
                for c in rec["comps"]:
                    c.set_editor_property("world_position_offset_disable_distance", 1)
                    stilled += 1
    census = [{"mesh": name, "count": rec["count"], "motion": rec["motion"] or "none"}
              for name, rec in sorted(agg.items(), key=lambda kv: -kv[1]["count"])]
    return census, stilled


def _motion_notes(census, wind_off, stilled):
    notes = []
    pivot = [c["mesh"] for c in census if c["motion"] == "pivot_wpo"]
    moving = [c["mesh"] for c in census if c["motion"] in ("wpo", "wpo_suspect")]
    if pivot:
        if wind_off:
            notes.append(f"pivot-anchored WPO on {', '.join(pivot)} — WPO disabled on the "
                         "whole grove (rules.wind='off'); renders planted (G58/G40)")
        else:
            notes.append(f"pivot-anchored WPO on {', '.join(pivot)} would float rigidly "
                         "when instanced (G40) — WPO auto-disabled on those components so "
                         "they render planted (G58)")
    elif wind_off and stilled:
        notes.append("rules.wind='off' — WPO disabled on the whole grove: renders static "
                     "(no sway)")
    if moving and not wind_off:
        notes.append(f"{', '.join(moving)} carry live WPO (wind sway) — left animating; "
                     "pass rules={\"wind\":\"off\"} to still the grove (G58)")
    return notes


# ── ops ───────────────────────────────────────────────────────────────────────────
# generate/regenerate are TWO-CALL (the G30 job pattern; PCG runs async — see _settle):
# the first call fires the graph and returns "generating"; the next call with the same
# label COLLECTS the settled census and applies the WPO cure. Mirrors `play op=census`.

def _fire_stub(label, graph, on, coverage, verb, still=False):
    """The "generating" return — phase-1 fire, OR a phase-2 collect that found generation
    still in flight (still=True). Either way the move is the same: call the same op again
    to collect (NOT re-fire — the graph is already running). Never finalizes a census."""
    lead = ("generation hasn't finished yet (the graph is still running on the editor's "
            "ticks) — nothing was re-fired" if still else
            "PCG generates asynchronously (it advances on the editor's next tick, which a "
            "single blocking call can't force). The volume is spawned and firing")
    return {"label": label, "graph": graph, "on": on, "coverage": coverage,
            "pcg": "generating", "undoable": False,
            "note": f"{lead} — call the same op again in ~2 s to collect the census.",
            "next": [f"pcg op={verb} label={label}   (again, ~2 s — collects the census + "
                     "stills any pivot-WPO meshes)",
                     f"pcg op=cleanup label={label}"]}


def _collect(label, meta, verb, extra_notes=None):
    """Phase-2: collect the census once generation has LANDED. Gate on the component's own
    `generated` flag (True only when the graph finished; probed live) — a blocking dispatch
    holds the game thread, so instance counts can't advance mid-call and a naive poll would
    finalize whatever partial total it happened to catch. If still in flight, keep pending
    and return the "call again" stub instead of recording a partial census."""
    vol = _ue.find_by_label(label)
    if not isinstance(vol, unreal.PCGVolume):
        _reg().pop(label, None)
        return {"error": f"the volume for '{label}' vanished before its census — "
                         f"pcg op=generate to rebuild"}
    comp = vol.pcg_component
    if not comp.get_editor_property("generated"):
        stub = _fire_stub(label, meta["graph"], meta["on"], meta.get("coverage"), verb,
                          still=True)
        if extra_notes:
            stub["notes"] = list(extra_notes)
        return stub
    wind_off = bool(meta.get("wind_off"))
    total = _settle(vol)
    census, stilled = _census_and_motion(vol, wind_off)
    meta.update({"pending": False, "instances": total,
                 "counts": {c["mesh"]: c["count"] for c in census}})
    out = {"label": label, "graph": meta["graph"], "on": meta["on"], "census": census,
           "instances": total, "coverage": meta.get("coverage"), "seed": meta.get("seed"),
           "undoable": False,
           "next": [f"pcg op=regenerate label={label} seed=<n>",
                    f"pcg op=cleanup label={label}"]}
    notes = list(extra_notes or [])
    notes += _motion_notes(census, wind_off, stilled)
    # Invariant 5: zero instances is a WARNING, never a silent success. `generated` is
    # True here, so generation genuinely finished empty — the cause is the surface, not timing.
    if total == 0:
        out["degraded_warning"] = (
            f"grove '{label}' finished generating with 0 instances — the surface '{meta['on']}'"
            " likely has no collision the sampler can ray-cast (the volume is auto-sized "
            f"tall, so Z headroom isn't the cause). pcg op=cleanup label={label} and grow on "
            "a collidable surface.")
    if notes:
        out["notes"] = notes
    return out


def _mismatch_notes(p, meta, keys):
    """Warn when a collect call re-passes params that differ from the pending grove's — the
    grove is already firing with the ORIGINAL params, so the new values are ignored."""
    notes = []
    for k in keys:
        if k in p and p[k] is not None and p[k] != meta.get(k):
            notes.append(f"'{k}={p[k]}' was ignored — grove '{p.get('label')}' is already "
                         f"generating with {k}={meta.get(k)} (pcg op=cleanup then generate "
                         "to change it)")
    return notes


def _generate(p):
    label = p.get("label", "pcg")
    meta = _reg().get(label)
    # Phase 2: a pending grove of this label → collect its census.
    if meta is not None and meta.get("pending"):
        return _collect(label, meta, "generate",
                        _mismatch_notes(p, meta, ("graph", "on", "region")))

    graph = p.get("graph")
    if not graph:
        return {"error": "generate requires graph=<palette name>",
                "palette": [e["name"] for e in _palette_list()],
                "next": "pcg op=palette lists each entry's meshes + density"}
    if graph not in PALETTE:
        return {"error": f"unknown graph '{graph}'",
                "palette": [e["name"] for e in _palette_list()],
                "next": "pcg op=palette lists the available palette graphs"}
    if meta is not None or _ue.find_by_label(label) is not None:
        return {"error": f"label '{label}' already exists (labels are unique across "
                         "ueb actors) — pcg op=cleanup label=" + label + " first, or "
                         "pcg op=regenerate to re-run it"}

    on = p.get("on", "terrain")
    surface = _ue.find_by_label(on)
    if surface is None:
        return {"error": f"no actor labelled '{on}' to grow on",
                "next": "outliner op=census lists the labels on= can reference"}
    sb = _ue.bounds(surface)
    if sb["size"] == [0, 0, 0]:
        return {"error": f"'{on}' has zero bounds — nothing to sample a surface from"}

    region = p.get("region")
    try:
        loc, scale, coverage = _volume_transform(sb, region)
    except ValueError as e:
        return {"error": str(e)}

    path, err = _materialize(graph)
    if err:
        return {"error": err}

    rules = p.get("rules") or {}
    if rules.get("wind", "on") not in ("on", "off"):
        return {"error": f"unknown rules.wind '{rules['wind']}'. known: on|off"}
    wind_off = rules.get("wind") == "off"
    seed = p.get("seed")

    # Invariant 2: spawn AT the final transform, set scale BEFORE any generate.
    eas = _ue.actor_subsystem()
    vol = eas.spawn_actor_from_class(unreal.PCGVolume, loc)
    vol.set_actor_label(label)
    vol.set_actor_scale3d(scale)
    vol.tags = [unreal.Name(_ue.UEB_TAG)]     # scope tag: outliner/feel/level see it (G7)

    comp = vol.pcg_component
    comp.set_graph(_ue.load_asset(path))
    if seed is not None:
        comp.set_editor_property("seed", int(seed))    # per-grove reroll, shared graph untouched
    comp.generate(True)
    _reg()[label] = {"graph": graph, "on": on, "seed": seed, "region": region,
                     "actor_name": vol.get_path_name(), "coverage": coverage,
                     "wind_off": wind_off, "pending": True, "instances": None,
                     "counts": {}}
    return _fire_stub(label, graph, on, coverage, "generate")


def _regenerate(p):
    label = p.get("label", "pcg")
    meta = _reg().get(label)
    vol = _ue.find_by_label(label)
    if meta is None or vol is None:
        return _unknown_label(label)
    if not isinstance(vol, unreal.PCGVolume):
        return {"error": f"'{label}' is not a PCGVolume"}
    # Phase 2: a re-fired grove of this label → collect its census.
    if meta.get("pending"):
        return _collect(label, meta, "regenerate", _mismatch_notes(p, meta, ("region",)))

    rules = p.get("rules") or {}
    if rules.get("wind", "on") not in ("on", "off"):
        return {"error": f"unknown rules.wind '{rules['wind']}'. known: on|off"}
    wind_off = rules.get("wind", "off" if meta.get("wind_off") else "on") == "off"
    seed = p.get("seed", meta.get("seed"))
    comp = vol.pcg_component
    if seed is not None:
        comp.set_editor_property("seed", int(seed))
    comp.generate(True)     # invariant 2: never move the volume between generates
    meta.update({"seed": seed, "wind_off": wind_off, "pending": True})
    return _fire_stub(label, meta["graph"], meta["on"], meta.get("coverage"), "regenerate")


def _cleanup(p):
    """Full reversal: cleanup the component, destroy the volume (which owns the generated
    ISM components), unregister."""
    label = p.get("label", "pcg")
    meta = _reg().get(label)
    vol = _ue.find_by_label(label)
    if meta is None and vol is None:
        return _unknown_label(label)
    # A label that resolves to a non-PCGVolume actor is not this verb's to tear down —
    # error rather than falsely report a teardown (matches regenerate's guard).
    if vol is not None and not isinstance(vol, unreal.PCGVolume):
        return {"error": f"'{label}' is not a PCGVolume — pcg op=cleanup won't touch it"}
    removed = 0
    if vol is not None:
        removed = _instance_total(vol)
        try:
            vol.pcg_component.cleanup(True)
        except Exception:
            pass
        _ue.actor_subsystem().destroy_actor(vol)
    _reg().pop(label, None)
    return {"label": label, "removed_instances": removed, "removed": True,
            "undoable": False}


def _describe(p):
    """Read-only census re-counted live from the volume. label omitted → every grove."""
    label = p.get("label")
    reg = _reg()
    if label is None:
        groves = []
        for lbl, meta in sorted(reg.items()):
            vol = _ue.find_by_label(lbl)
            live = _instance_total(vol) if isinstance(vol, unreal.PCGVolume) else 0
            groves.append({"label": lbl, "graph": meta["graph"], "on": meta["on"],
                           "instances": live, "recorded": meta.get("instances"),
                           "seed": meta.get("seed")})
        return {"groves": groves, "count": len(groves)}
    meta = reg.get(label)
    vol = _ue.find_by_label(label)
    if meta is None or not isinstance(vol, unreal.PCGVolume):
        return _unknown_label(label)
    census, _stilled = _census_and_motion(vol, meta.get("wind_off", False), apply=False)
    out = {"label": label, "graph": meta["graph"], "on": meta["on"],
           "census": census, "instances": _instance_total(vol),
           "coverage": meta.get("coverage"), "seed": meta.get("seed")}
    if meta.get("pending"):
        out["note"] = ("this grove is still generating (fired, not yet collected) — "
                       f"pcg op=generate label={label} again to settle its census + "
                       "still any pivot-WPO meshes")
    return out
