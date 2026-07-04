"""`foliage` — populations, not actors (SPEC-01 E5; SPEC-05 rename of `scatter`).

NATIVE: wraps UE's Foliage system — the editor's Foliage mode, `InstancedFoliageActor`,
minted `FoliageType` assets. `op=paint` is UE's own tool name for exactly this act.
(Cousin: PCG is 5.x's modern procedural scatter, but its 5.8 Python surface is thin where
Foliage's is proven — revisit against the build, not memory: SPEC-05 R2.)

A forest is a population with rules, not thousands of placement decisions. The agent declares
the rules; a seeded PRNG makes it reproducible; clearances protect the intent already placed.
The whole population is instanced foliage — never thousands of actors (which would poison
scene/undo).

Rendering (G14): the first cut built one `HierarchicalInstancedStaticMeshComponent` per
variant via the outer-constructor trick — the instance data was correct but NOTHING RENDERED,
because editor Python can't register a hand-constructed component with the render scene (no
`register_component`). The fix routes instances through the editor's own foliage subsystem:
`InstancedFoliageActor.add_instances(world, FoliageType, transforms)`. That path creates a
properly-registered `FoliageInstancedStaticMeshComponent` (real culling, per-mesh materials,
Nanite) — so the population actually draws. Each stand gets its own namespaced
`FoliageType_InstancedStaticMesh` assets (under `/Game/UEB_Foliage`) so its components are
distinct; those components are tagged `ueb_scatter:<label>` so `remove`/`reseed` can clear
exactly this population and nothing else. Foliage lives in the level's IFA, not a ueb actor,
so it never pollutes `outliner`/`feel` — the "populations, not actors" intent survives the swap.

No numpy: sampling is a seeded jittered grid in pure Python; ground z + slope come from world
traces so instances conform to the real terrain. Spatial verb — status block, not history-
undoable; teardown is `remove`.
"""
import math
import random

import unreal

from . import _state
from . import _ue
from . import heightfield
from . import asset
from . import rules as rulesmod

_FOLIAGE_DIR = "/Game/UEB_Foliage"     # where per-stand FoliageType assets live
# Component-tag prefix identifying a stand's foliage components. The STRING predates the
# scatter->foliage rename and is saved into levels — changing it would orphan every
# existing stand, so the old spelling stays as opaque persisted data (SPEC-05 pragmatism).
_FOLIAGE_TAG = "ueb_scatter:"


def handle(p):
    fn = {"paint": _paint, "describe": _describe, "reseed": _reseed,
          "remove": _remove}.get(p.get("op", "paint"))
    if fn is None:
        return {"error": f"unknown foliage op '{p.get('op')}'. known: "
                         "paint|describe|reseed|remove"}
    return fn(p)


# ── mesh family resolution ───────────────────────────────────────────────────────
def _pack_of(pkg_path):
    """/Game/<Pack>/... → <Pack>."""
    parts = pkg_path.split("/")
    return parts[2] if len(parts) > 2 else "?"


def _resolve_meshes(specs, pack=None):
    """["Pine_Tree", "Black_Alder:0.3"] → [{family, weight, variants:[paths], pivot}].

    G31: a family name that resolves across MULTIPLE packs is ambiguous, not a bigger
    palette — "Rock" once silently pulled 48 variants from two packs, most dims-blind.
    Same honesty as `add` on ambiguous short names: error with pack-attributed candidates
    and take a `pack=` scope (an exact variant name that exists in one pack stays fine)."""
    out = []
    for spec in specs:
        name, _, w = spec.partition(":")
        weight = float(w) if w else 1.0
        variants = _family_variants(name, pack)
        if not variants:
            where = f" in pack '{pack}'" if pack else ""
            raise ValueError(f"no static-mesh variants for family '{name}'{where}")
        packs = sorted({_pack_of(v) for v in variants})
        if len(packs) > 1:
            per = {pk: [v.rsplit("/", 1)[-1] for v in variants if _pack_of(v) == pk]
                   for pk in packs}
            raise ValueError(
                f"family '{name}' is ambiguous — it resolves across {len(packs)} packs: "
                + "; ".join(f"{pk} ({len(vs)}: {', '.join(vs[:4])}"
                            + (", …" if len(vs) > 4 else "") + ")"
                            for pk, vs in per.items())
                + ". Scope with pack=<name> or pass explicit variant names.")
        out.append({"family": name, "weight": weight, "variants": variants})
    return out


def _family_variants(name, pack=None):
    """All static-mesh asset paths whose inferred family == name (or an exact name match),
    optionally scoped to one /Game/<pack> root."""
    root = f"/Game/{pack}" if pack else "/Game"
    paths = []
    for ad in asset._assets_under(root, [asset.STATIC_MESH]):
        n = asset._name(ad)
        if asset._family_of(n) == name or n == name:
            paths.append(asset._pkg(ad))
    return sorted(paths)


# ── clearance predicates ─────────────────────────────────────────────────────────
def _build_clearances(p):
    """Assemble reject-tests for a candidate (x,y). Default (SPEC-01): every paint clears
    existing PATHS by width/2 + margin and existing BUILDINGS by footprint + margin, so a
    path reads as going *through* the trees, not carved out afterwards. `clear_of` adds
    explicit path/actor labels and regions."""
    rules = p.get("rules") or {}
    margin = rules.get("clear_margin", 300.0)
    tests = []

    # existing paths (auto + explicit) — reject within width/2 + margin of the polyline
    from . import spline as splinemod
    explicit = rules.get("clear_of", [])
    path_labels = set(_state.splines.keys())
    for lbl in explicit:
        if isinstance(lbl, str) and lbl in _state.splines:
            path_labels.add(lbl)
    for lbl in path_labels:
        pdata = _state.splines[lbl]
        poly, _cum = splinemod._sample_polyline([[x, y] for x, y, _ in pdata["points"]])
        half = pdata.get("width", 300.0) / 2.0 + margin
        tests.append(("path:" + lbl, _near_polyline_test(poly, half)))

    # existing buildings/actors — reject within footprint + margin. Scatter populations are
    # foliage (in the level IFA, not ueb actors), so they never appear here — only real
    # placed geometry does; substrates are excluded (you paint ONTO a terrain, and a spline
    # SURFACE strip's AABB spans the whole route — the polyline test already clears paths).
    subs = _ue.substrate_labels()
    for a in _ue.ueb_actors():
        lbl = a.get_actor_label()
        if lbl in subs:
            continue
        b = _ue.bounds(a)
        if b["size"] == [0, 0, 0]:
            continue
        x0, y0 = b["min"][0] - margin, b["min"][1] - margin
        x1, y1 = b["max"][0] + margin, b["max"][1] + margin
        tests.append(("actor:" + lbl, _in_box_test(x0, y0, x1, y1)))

    # explicit regions
    for item in explicit:
        if isinstance(item, dict) and item.get("kind"):
            tests.append(("region", _in_region_test(item, margin)))
    return tests


def _near_polyline_test(poly, dist):
    def t(x, y):
        for a, b in zip(poly, poly[1:]):
            if _dist_seg(x, y, a, b) <= dist:
                return True
        return False
    return t


def _in_box_test(x0, y0, x1, y1):
    return lambda x, y: x0 <= x <= x1 and y0 <= y <= y1


def _in_region_test(region, margin):
    return lambda x, y: heightfield.region_inset(x, y, region) >= -margin


def _dist_seg(px, py, a, b):
    ax, ay = a; bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


# ── sampling ─────────────────────────────────────────────────────────────────────
def _region_bbox(region):
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
    raise ValueError(f"unknown region kind '{kind}'")


def _terrain_normal(x, y, d=100.0):
    """Ground z at (x,y) and surface normal (from neighbour traces), for slope + align."""
    z = _ue.trace_ground(x, y)
    if z is None:
        return None, None, 0.0
    zx1 = _ue.trace_ground(x + d, y); zx0 = _ue.trace_ground(x - d, y)
    zy1 = _ue.trace_ground(x, y + d); zy0 = _ue.trace_ground(x, y - d)
    if None in (zx1, zx0, zy1, zy0):
        return z, unreal.Vector(0, 0, 1), 0.0
    gx = (zx1 - zx0) / (2 * d); gy = (zy1 - zy0) / (2 * d)
    n = unreal.Vector(-gx, -gy, 1.0)
    slope = math.degrees(math.atan2(math.hypot(gx, gy), 1.0))
    return z, n, slope


def _sample_points(region, spacing, rng):
    """Seeded jittered grid over the region bbox → candidate [x,y], only those inside the
    region. Guarantees roughly `spacing`-separated points without a full Poisson pass."""
    x0, y0, x1, y1 = _region_bbox(region)
    pts = []
    y = y0
    while y <= y1:
        x = x0
        while x <= x1:
            jx = x + (rng.random() - 0.5) * spacing
            jy = y + (rng.random() - 0.5) * spacing
            if region.get("kind") == "terrain" or heightfield.in_region(jx, jy, region):
                pts.append((jx, jy))
            x += spacing
        y += spacing
    return pts


# ── foliage backend (G14: registered instances that actually render) ──────────────
def _sanitize(s):
    return "".join(ch if ch.isalnum() else "_" for ch in s)


def _ifa_fismcs():
    """Every foliage instanced-mesh component across the level's InstancedFoliageActors."""
    out = []
    for a in _ue.all_actors():
        if isinstance(a, unreal.InstancedFoliageActor):
            out.extend(a.get_components_by_class(unreal.InstancedStaticMeshComponent))
    return out


def motion_census():
    """G40: the level-wide motion census — aggregate foliage instances by motion verdict
    and call out meshes whose WPO breaks under instancing. Returns one warning line for
    the status block, or None when the forest is motion-clean (silence, not a report:
    this is the warning channel). Cheap after first classification — verdicts cache per
    material and the meshes are already loaded by the level."""
    total, bad = 0, {}
    for c in _ifa_fismcs():
        n = c.get_instance_count()
        if n == 0:
            continue
        total += n
        mesh = c.get_editor_property("static_mesh")
        if mesh is None:
            continue
        kind, _note = asset._mesh_motion(mesh)
        if kind in ("pivot_wpo", "wpo", "wpo_suspect"):
            agg = bad.setdefault(kind, [0, set()])
            agg[0] += n
            agg[1].add(mesh.get_name())
    if not bad:
        return None
    verdict = {
        "pivot_wpo": "FLOAT rigidly — pivot-anchored WPO breaks under instancing (G40)",
        "wpo": "MOVE (unmasked WPO)",
        "wpo_suspect": "likely move (displacement wired, WPO pin unreadable)"}
    parts = []
    for kind in ("pivot_wpo", "wpo", "wpo_suspect"):
        if kind in bad:
            n, names = bad[kind]
            shown = sorted(names)
            parts.append(f"{n}/{total} foliage instances {verdict[kind]}: "
                         + ", ".join(shown[:4]) + (", …" if len(shown) > 4 else ""))
    return "motion: " + "; ".join(parts)


def _clear_tagged(tag):
    """Empty every foliage component carrying `tag` (Python can't destroy the component, but a
    cleared FISMC has zero instances → nothing drawn). Returns how many were cleared."""
    cleared = 0
    for c in _ifa_fismcs():
        if tag in [str(t) for t in c.get_editor_property("component_tags")]:
            c.clear_instances()
            cleared += 1
    return cleared


# G46: the FoliageType default is NoCollision — the PIE pawn walks through trunks.
# rules.collision governs it per paint:
#   "auto" (default)  tree-scale variants (mesh taller than the threshold) get BlockAll
#                     bodies; understory stays collision-free (17k grass bodies aren't free)
#   "block" / "none"  force it for the whole stand
# Scope of the fix: instance BODIES block physics/objects (the pawn stops at trunks).
# The VISIBILITY channel stays ECR_IGNORE — FoliageInstancedStaticMeshComponent forces it
# by engine design, and that is load-bearing here: ground traces during paint/drape must
# never land instances on treetops. "Which tree am I looking at" is deixis' ray-vs-bounds
# math pass, not a trace, so nothing is lost.
_COLLIDE_MIN_HEIGHT_CM = 250.0   # pawn-scale: shorter than this reads as walk-over/through


def _wants_collision(mode, mesh_path):
    if mode == "block":
        return True
    if mode == "none":
        return False
    m = _ue.load_asset(mesh_path)   # auto: height from the mesh's own bounds (ground truth)
    try:
        h = m.get_bounds().box_extent.z * 2.0
    except Exception:
        return False
    return h >= _COLLIDE_MIN_HEIGHT_CM


def _foliage_type_for(label, idx, mesh_path, collide=False):
    """A per-stand FoliageType_InstancedStaticMesh asset (namespaced by label+variant) with
    its mesh set. Recreated fresh each build so it never carries stale settings/instances."""
    name = f"FT_{_sanitize(label)}__{idx}"
    full = f"{_FOLIAGE_DIR}/{name}"
    if unreal.EditorAssetLibrary.does_asset_exist(full):
        unreal.EditorAssetLibrary.delete_asset(full)
    atools = unreal.AssetToolsHelpers.get_asset_tools()
    ft = atools.create_asset(name, _FOLIAGE_DIR, unreal.FoliageType_InstancedStaticMesh,
                             unreal.FoliageType_InstancedStaticMeshFactory())
    ft.set_editor_property("mesh", _ue.load_asset(mesh_path))
    if collide:
        # Writing the raw struct sets the NAME components will copy, but never runs the
        # profile-application path (collision_enabled stays NO_COLLISION) — the created
        # components get set_collision_profile_name() after the add, which does.
        bi = ft.get_editor_property("body_instance")
        bi.set_editor_property("collision_profile_name", "BlockAll")
        bi.set_editor_property("collision_enabled", unreal.CollisionEnabled.QUERY_AND_PHYSICS)
        ft.set_editor_property("body_instance", bi)
    return ft, full


def _add_tagged(world, ft, transforms, tag):
    """Add instances through the foliage subsystem (which registers the component so it draws)
    and tag the freshly-created component(s) so `remove` can find exactly this stand's foliage.

    Diff on `get_path_name()`, NOT `get_name()`: World Partition shards foliage into one
    InstancedFoliageActor per grid cell, and component names restart at _0 inside each IFA — so
    a plain-name before/after diff collides across cells and silently skips (fails to tag) new
    components. The path name is globally unique. A single add may also touch more than one cell,
    so tag every genuinely-new component, not just the first."""
    before = {c.get_path_name() for c in _ifa_fismcs()}
    unreal.InstancedFoliageActor.add_instances(world, ft, transforms)
    for c in _ifa_fismcs():
        if c.get_path_name() in before:
            continue
        existing = [str(t) for t in c.get_editor_property("component_tags")]
        if tag not in existing:
            c.set_editor_property("component_tags",
                                  [unreal.Name(tag)] + [unreal.Name(t) for t in existing])


# ── create ───────────────────────────────────────────────────────────────────────
def _spacing_for(region, density, rules):
    if rules.get("min_spacing_cm"):
        return float(rules["min_spacing_cm"])
    # density_per_100m2: 100 m² = 1e6 cm². spacing ≈ sqrt(area_per_instance).
    d = max(0.01, float(density or 5.0))
    return math.sqrt(1_000_000.0 / d)


def _canopy_notes(meshes, spacing, jit):
    """G28: spacing the agent fabricated below the measured canopy width ⇒ wall-to-wall
    interpenetration (the 'ultra clipped' 1/10 playtest). Check the requested spacing
    against the widest cached footprint among the scattered variants (at max scale jitter)
    and WARN with the numbers — the fix is derived, not divined. Reads the dims cache only
    (never forces mesh loads mid-paint); unmeasured variants are named as a blind spot."""
    widest, widest_fam, unmeasured, total = 0.0, None, 0, 0
    for m in meshes:
        for vp in m["variants"]:
            total += 1
            d = _state.cached_dims(vp)
            if d is None:
                unmeasured += 1
                continue
            w = max(d["dims_cm"][0], d["dims_cm"][1])
            if w > widest:
                widest, widest_fam = w, m["family"]
    notes = []
    scale_hi = max(jit) if jit else 1.0
    eff = widest * scale_hi
    if widest and spacing < eff * 0.8:
        notes.append(f"min spacing ≈{round(spacing)}cm is under the widest canopy "
                     f"({widest_fam} ≈{round(widest)}cm × {scale_hi} jitter = "
                     f"{round(eff)}cm) — neighbours WILL interpenetrate and read as "
                     f"clipped geometry (G28); use min_spacing_cm ≥ {round(eff)} or "
                     f"lower the density")
    if unmeasured:
        notes.append(f"{unmeasured}/{total} scattered variants have no measured dims — "
                     f"the canopy-vs-spacing check is partial; asset inventory "
                     f"measure=true first to make it complete")
    return notes


def _paint(p):
    label = p.get("label", "foliage")
    tag = _FOLIAGE_TAG + label
    live = any(tag in [str(t) for t in c.get_editor_property("component_tags")]
               and c.get_instance_count() > 0 for c in _ifa_fismcs())
    if label in _state.foliage_stands or live:
        return {"error": f"foliage stand '{label}' already exists (remove it first)"}
    region = p.get("region")
    if not region:
        return {"error": "paint requires region={kind:circle|rect|polygon|terrain, ...}"}
    if region.get("kind") == "terrain":
        meta = _state.terrains.get(p.get("terrain", "terrain"))
        if meta is None:
            return {"error": "region kind 'terrain' needs a terrain (create one first)"}
        ox, oy, _ = meta["origin"]; sx, sy = meta["size"]
        region = {"kind": "rect", "at": [ox, oy], "size": [sx, sy]}
    try:
        meshes = _resolve_meshes(p.get("meshes", []), p.get("pack"))
    except ValueError as e:
        return {"error": str(e)}
    if not meshes:
        return {"error": "paint requires meshes=[family, ...]"}

    seed = int(p.get("seed", 1337))
    rules = p.get("rules") or {}
    if rules.get("collision", "auto") not in ("auto", "block", "none"):
        return {"error": f"unknown rules.collision '{rules['collision']}'. "
                         "known: auto|block|none"}
    # SPEC-07 firing point 1 — painting IS instancing: a breaks-severity pairing
    # (R1: pivot-anchored WPO) refuses BEFORE planting; force=true overrides and the
    # census keeps flagging the stand.
    refusal, gate_notes = rulesmod.gate(
        [v for m in meshes for v in m["variants"]], "instanced",
        force=bool(p.get("force")),
        reissue=f"foliage op=paint label={label} (same args)")
    if refusal:
        return refusal
    result = _generate(label, region, meshes, seed, rules, p)
    if gate_notes:
        result["notes"] = result.get("notes", []) + gate_notes
    return result


def _generate(label, region, meshes, seed, rules, p):
    rng = random.Random(seed)
    spacing = _spacing_for(region, p.get("density_per_100m2"), rules)
    candidates = _sample_points(region, spacing, rng)
    clearances = _build_clearances(p)
    max_slope = rules.get("max_slope_deg", 35.0)
    align = rules.get("align_to_slope", False)
    jit = rules.get("scale_jitter", [1.0, 1.0])
    yaw_random = rules.get("yaw_random", True)

    variant_paths = [v for m in meshes for v in m["variants"]]

    # weighted family picker
    fam_weights = [(m, m["weight"]) for m in meshes]
    total_w = sum(w for _, w in fam_weights)

    placed = 0
    per_variant = {}
    variant_transforms = {vp: [] for vp in variant_paths}   # foliage adds per variant in a batch
    rejected = {"region": 0, "slope": 0, "clear": 0, "no_ground": 0}
    for (x, y) in candidates:
        blocked = False
        for _name, test in clearances:
            if test(x, y):
                rejected["clear"] += 1; blocked = True; break
        if blocked:
            continue
        z, normal, slope = _terrain_normal(x, y)
        if z is None:
            rejected["no_ground"] += 1; continue
        if slope > max_slope:
            rejected["slope"] += 1; continue
        # pick family (weighted), then a random variant within it
        r = rng.random() * total_w
        fam = fam_weights[0][0]
        acc = 0.0
        for m, w in fam_weights:
            acc += w
            if r <= acc:
                fam = m; break
        vp = rng.choice(fam["variants"])
        s = jit[0] + rng.random() * (jit[1] - jit[0])
        yaw = rng.uniform(0, 360) if yaw_random else 0.0
        pitch = roll = 0.0
        if align and normal is not None:
            pitch = math.degrees(math.atan2(normal.x, normal.z))
            roll = math.degrees(math.atan2(normal.y, normal.z))
        t = unreal.Transform()
        t.set_editor_property("translation", unreal.Vector(x, y, z))
        t.set_editor_property("rotation",
                              unreal.Rotator(pitch=pitch, yaw=yaw, roll=roll).quaternion())
        t.set_editor_property("scale3d", unreal.Vector(s, s, s))
        variant_transforms[vp].append(t)
        per_variant[vp] = per_variant.get(vp, 0) + 1
        placed += 1

    # Commit the population as registered foliage — one FoliageType asset + one component per
    # variant that actually got instances. This is the step HISM couldn't do: draw (G14).
    world = _ue.editor_world()
    tag = _FOLIAGE_TAG + label
    _clear_tagged(tag)                                   # drop any orphaned empties for this label
    collision_mode = rules.get("collision", "auto")
    blocking, walk_through, blocked_paths = [], [], set()
    ft_paths = []
    for idx, vp in enumerate(variant_paths):
        tlist = variant_transforms.get(vp)
        if not tlist:
            continue
        collide = _wants_collision(collision_mode, vp)
        (blocking if collide else walk_through).append(vp.rsplit("/", 1)[-1])
        if collide:
            blocked_paths.add(vp)
        ft, full = _foliage_type_for(label, idx, vp, collide)
        ft_paths.append(full)
        _add_tagged(world, ft, tlist, tag)
    # G46: apply the profile ON the created components — the PrimitiveComponent call is
    # what actually flips collision_enabled + channel responses (the FT struct write
    # alone leaves every instance body inert).
    if blocked_paths:
        for c in _ifa_fismcs():
            if tag not in [str(t) for t in c.get_editor_property("component_tags")]:
                continue
            mesh = c.get_editor_property("static_mesh")
            if mesh and mesh.get_path_name().split(".")[0] in blocked_paths:
                c.set_collision_profile_name("BlockAll")

    _state.foliage_stands[label] = {
        "region": region,
        "meshes": [m["family"] for m in meshes],
        "seed": seed, "rules": rules, "count": placed,
        "per_family": _fold_families(per_variant, meshes),
        "density_per_100m2": p.get("density_per_100m2"),
        "terrain": p.get("terrain", "terrain"),
        "meshes_spec": p.get("meshes", []),
        "foliage_types": ft_paths,
        "force": bool(p.get("force")),   # SPEC-07: a forced stand must survive reseed
    }
    out = {"painted": label, "instances": placed, "species": len(meshes),
           "per_family": _state.foliage_stands[label]["per_family"],
           "seed": seed, "rejected": rejected, "foliage_types": len(ft_paths),
           "undoable": False,
           "collision": {"mode": collision_mode, "blocking": blocking,
                         "walk_through": walk_through},
           "note": "instanced foliage (registered) — renders in the viewport"}
    # G39: a population that will MOVE (WPO wind/displacement) is announced at author
    # time — a whole-mesh-bobbing understory must never paint silently again.
    notes = _canopy_notes(meshes, spacing, jit) + asset.motion_notes(variant_paths)
    # G46: a tree-scale stand painted collision-free is a playtest trap — say so with
    # the ready fix, at author time.
    if collision_mode == "none" and \
            any(_wants_collision("auto", vp) for vp in variant_paths):
        notes.append("collision=none on tree-scale meshes — the PIE pawn walks through "
                     "trunks; repaint with rules.collision='auto' to give them BlockAll "
                     "bodies (G46)")
    if notes:
        out["notes"] = notes
    return out


def _fold_families(per_variant, meshes):
    fam_of = {}
    for m in meshes:
        for vp in m["variants"]:
            fam_of[vp] = m["family"]
    out = {}
    for vp, c in per_variant.items():
        f = fam_of.get(vp, "?")
        out[f] = out.get(f, 0) + c
    return out


def _describe(p):
    label = p.get("label", "foliage")
    s = _state.foliage_stands.get(label)
    if s is None:
        return {"error": f"no foliage stand labelled '{label}'"}
    return {"label": label, "instances": s["count"], "region": s["region"],
            "seed": s["seed"], "rules": s["rules"], "per_family": s["per_family"],
            "species": s["meshes"]}


def _reseed(p):
    """Same rules, new dice — the human's 'reroll that stand' button."""
    label = p.get("label", "foliage")
    s = _state.foliage_stands.get(label)
    if s is None:
        return {"error": f"no foliage stand labelled '{label}'"}
    # SPEC-07: gate BEFORE the remove — a palette that now refuses (R1) must not
    # silently delete the stand it fails to replace.
    try:
        gm = _resolve_meshes(s["meshes_spec"], None)
    except ValueError:
        gm = None
    if gm:
        refusal, _gn = rulesmod.gate([v for m in gm for v in m["variants"]],
                                     "instanced", force=s.get("force", False),
                                     reissue=f"foliage op=reseed label={label}")
        if refusal:
            refusal["note"] = "stand left untouched — the reseed was refused before removal"
            return refusal
    _remove({"label": label})
    newp = {"label": label, "region": s["region"], "meshes": s["meshes_spec"],
            "density_per_100m2": s["density_per_100m2"], "rules": s["rules"],
            "terrain": s["terrain"], "seed": p.get("seed", s["seed"] + 1),
            "force": s.get("force", False)}
    return _paint(newp)


def _remove(p):
    """Clear exactly this scatter's foliage (components tagged ueb_scatter:<label>) and delete
    its FoliageType assets. Works even after a runtime reimport wiped _state — the tag lives on
    the component (saved with the level), so the population is recoverable by tag alone."""
    label = p.get("label", "foliage")
    s = _state.foliage_stands.get(label)
    tag = _FOLIAGE_TAG + label
    cleared = _clear_tagged(tag)
    ft_paths = list((s or {}).get("foliage_types", []))
    if not ft_paths and unreal.EditorAssetLibrary.does_directory_exist(_FOLIAGE_DIR):
        prefix = f"FT_{_sanitize(label)}__"
        for a in unreal.EditorAssetLibrary.list_assets(_FOLIAGE_DIR, recursive=False):
            if prefix in a:
                ft_paths.append(a.split(".")[0])
    for fp in ft_paths:
        if unreal.EditorAssetLibrary.does_asset_exist(fp):
            try:
                unreal.EditorAssetLibrary.delete_asset(fp)
            except Exception:
                pass
    _state.foliage_stands.pop(label, None)
    if s is None and cleared == 0:
        return {"error": f"no foliage stand labelled '{label}'"}
    return {"removed": label, "components_cleared": cleared, "undoable": False}
