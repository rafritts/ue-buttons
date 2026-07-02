"""`scatter` — populations, not actors (SPEC-01 E5).

A forest is a population with rules, not thousands of placement decisions. The agent declares
the rules; a seeded PRNG makes it reproducible; clearances protect the intent already placed.
One actor holds one HierarchicalInstancedStaticMeshComponent per mesh variant — the whole
population is a single labelled actor (never thousands, which would poison scene/undo).

No numpy: sampling is a seeded jittered grid in pure Python; ground z + slope come from world
traces so instances conform to the real terrain. Spatial verb — status block, not history-
undoable; teardown is `remove`.
"""
import math
import random

import unreal

from . import _state
from . import _ue
from . import terrain as terrain_mod
from . import asset


def handle(p):
    fn = {"create": _create, "describe": _describe, "regenerate": _regenerate,
          "remove": _remove}.get(p.get("action", "create"))
    if fn is None:
        return {"error": f"unknown scatter action '{p.get('action')}'. known: "
                         "create|describe|regenerate|remove"}
    return fn(p)


# ── mesh family resolution ───────────────────────────────────────────────────────
def _resolve_meshes(specs):
    """["Pine_Tree", "Black_Alder:0.3"] → [{family, weight, variants:[paths], pivot}]."""
    out = []
    for spec in specs:
        name, _, w = spec.partition(":")
        weight = float(w) if w else 1.0
        variants = _family_variants(name)
        if not variants:
            raise ValueError(f"no static-mesh variants for family '{name}'")
        out.append({"family": name, "weight": weight, "variants": variants})
    return out


def _family_variants(name):
    """All static-mesh asset paths whose inferred family == name (or a substring match)."""
    paths = []
    for ad in asset._assets_under("/Game", [asset.STATIC_MESH]):
        n = asset._name(ad)
        if asset._family_of(n) == name or n == name:
            paths.append(asset._pkg(ad))
    return sorted(paths)


# ── clearance predicates ─────────────────────────────────────────────────────────
def _build_clearances(p):
    """Assemble reject-tests for a candidate (x,y). Default (SPEC-01): every scatter clears
    existing PATHS by width/2 + margin and existing BUILDINGS by footprint + margin, so a
    path reads as going *through* the trees, not carved out afterwards. `clear_of` adds
    explicit path/actor labels and regions."""
    rules = p.get("rules") or {}
    margin = rules.get("clear_margin", 300.0)
    tests = []

    # existing paths (auto + explicit) — reject within width/2 + margin of the polyline
    from . import path as pathmod
    explicit = rules.get("clear_of", [])
    path_labels = set(_state.paths.keys())
    for lbl in explicit:
        if isinstance(lbl, str) and lbl in _state.paths:
            path_labels.add(lbl)
    for lbl in path_labels:
        pdata = _state.paths[lbl]
        poly, _cum = pathmod._sample_polyline([[x, y] for x, y, _ in pdata["points"]])
        half = pdata.get("width", 300.0) / 2.0 + margin
        tests.append(("path:" + lbl, _near_polyline_test(poly, half)))

    # existing buildings/actors — reject within footprint + margin
    own_scatter_actors = {v.get("actor_label") for v in _state.scatters.values()}
    terrains = set(_state.landscapes.keys())
    for a in _ue.ueb_actors():
        lbl = a.get_actor_label()
        if lbl in terrains or lbl in own_scatter_actors:
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
    return lambda x, y: terrain_mod.region_inset(x, y, region) >= -margin


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
            if region.get("kind") == "landscape" or terrain_mod.in_region(jx, jy, region):
                pts.append((jx, jy))
            x += spacing
        y += spacing
    return pts


# ── create ───────────────────────────────────────────────────────────────────────
def _spacing_for(region, density, rules):
    if rules.get("min_spacing_cm"):
        return float(rules["min_spacing_cm"])
    # density_per_100m2: 100 m² = 1e6 cm². spacing ≈ sqrt(area_per_instance).
    d = max(0.01, float(density or 5.0))
    return math.sqrt(1_000_000.0 / d)


def _create(p):
    label = p.get("label", "scatter")
    if label in _state.scatters or _ue.find_by_label(label) is not None:
        return {"error": f"scatter '{label}' already exists"}
    region = p.get("region")
    if not region:
        return {"error": "scatter requires region={kind:circle|rect|polygon|landscape, ...}"}
    if region.get("kind") == "landscape":
        meta = _state.landscapes.get(p.get("terrain", "terrain"))
        if meta is None:
            return {"error": "region kind 'landscape' needs a terrain (create one first)"}
        ox, oy, _ = meta["origin"]; sx, sy = meta["size"]
        region = {"kind": "rect", "at": [ox, oy], "size": [sx, sy]}
    try:
        meshes = _resolve_meshes(p.get("meshes", []))
    except ValueError as e:
        return {"error": str(e)}
    if not meshes:
        return {"error": "scatter requires meshes=[family, ...]"}

    seed = int(p.get("seed", 1337))
    rules = p.get("rules") or {}
    result = _generate(label, region, meshes, seed, rules, p)
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

    # one HISM per variant across all families
    actor = _ue.actor_subsystem().spawn_actor_from_class(
        unreal.Actor, unreal.Vector(0, 0, 0))
    actor.set_actor_label(label)
    actor.tags = [unreal.Name(_ue.UEB_TAG)]
    variant_paths = [v for m in meshes for v in m["variants"]]
    hisms = {}
    for vp in variant_paths:
        h = unreal.HierarchicalInstancedStaticMeshComponent(actor)
        mesh = unreal.EditorAssetLibrary.load_asset(vp)
        h.set_static_mesh(mesh)
        hisms[vp] = h

    # weighted family picker
    fam_weights = [(m, m["weight"]) for m in meshes]
    total_w = sum(w for _, w in fam_weights)

    placed = 0
    per_variant = {}
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
        hisms[vp].add_instance(t, True)
        per_variant[vp] = per_variant.get(vp, 0) + 1
        placed += 1

    _state.scatters[label] = {
        "actor_label": label, "region": region,
        "meshes": [m["family"] for m in meshes],
        "seed": seed, "rules": rules, "count": placed,
        "per_family": _fold_families(per_variant, meshes),
        "density_per_100m2": p.get("density_per_100m2"),
        "terrain": p.get("terrain", "terrain"),
        "meshes_spec": p.get("meshes", []),
    }
    return {"scattered": label, "instances": placed, "species": len(meshes),
            "per_family": _state.scatters[label]["per_family"],
            "seed": seed, "rejected": rejected, "undoable": False}


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
    label = p.get("label", "scatter")
    s = _state.scatters.get(label)
    if s is None:
        return {"error": f"no scatter labelled '{label}'"}
    return {"label": label, "instances": s["count"], "region": s["region"],
            "seed": s["seed"], "rules": s["rules"], "per_family": s["per_family"],
            "species": s["meshes"]}


def _regenerate(p):
    """Same rules, new dice — the human's 'reroll that stand' button."""
    label = p.get("label", "scatter")
    s = _state.scatters.get(label)
    if s is None:
        return {"error": f"no scatter labelled '{label}'"}
    _remove({"label": label})
    newp = {"label": label, "region": s["region"], "meshes": s["meshes_spec"],
            "density_per_100m2": s["density_per_100m2"], "rules": s["rules"],
            "terrain": s["terrain"], "seed": p.get("seed", s["seed"] + 1)}
    return _create(newp)


def _remove(p):
    label = p.get("label", "scatter")
    if label not in _state.scatters:
        return {"error": f"no scatter labelled '{label}'"}
    a = _ue.find_by_label(label)
    if a is not None:
        _ue.actor_subsystem().destroy_actor(a)
    _state.scatters.pop(label, None)
    return {"removed": label}
