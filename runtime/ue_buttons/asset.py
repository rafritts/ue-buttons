"""`asset` — perception over the project's Content (SPEC-01 E1).

Answers "what can I build with, and how big is it?" at build-planning altitude, one rung
above Epic's path-level queries. Read-only: no transaction, no history, no status block.

All dimensions are centimetres (UE native). The expensive step is loading a StaticMesh to
read its real bounds/pivot/materials — registry *tags* give Nanite/triangles/collision for
free, but not size. Measured dims are cached in `_state.dims_cache` (survives handler
hot-reload) and invalidated when `whats_new` sees the registry change.
"""
import json
import os
import re

import unreal

from . import _state
from . import _ue

STATIC_MESH = "StaticMesh"
SKELETAL_MESH = "SkeletalMesh"
BLUEPRINT = "Blueprint"

# The pack roots the test palette installed under /Game (SPEC-01). `packs` reports
# whatever /Game roots actually exist, not this list — but a short human character line
# is keyed off it where known.
_PACK_CHARACTER = {
    "Megaplant_Library": "trees & shrubs (use SM variants; skeletal ignored)",
    "GV_FreeShrubsPack": "undergrowth meshes",
    "RockEnv_Pack": "rocks & cliffs",
    "Rock_Collection_04": "rocks & cliffs",
    "Modular_Rural_Cabin": "modular wall kit on a 4 m grid + prebuilt cabin BPs",
    "KiteDemo": "terrain-grade landscape materials",
    "ParagonProps": "stylized props (hamlet clutter)",
    "Fab": "surface materials (Megascans)",
}

_SNAPSHOT_NAME = "ueb_asset_snapshot.json"
_DIMS_CACHE_NAME = "ueb_dims_cache.json"

# How many uncached meshes a single `inventory(measure=True)` call will load. Keeps each
# RC call well under the transport timeout so measurement never blocks the bridge (G9).
_MEASURE_BUDGET = 60


# ── registry helpers ────────────────────────────────────────────────────────────
def _ar():
    return unreal.AssetRegistryHelpers.get_asset_registry()


def _class_name(ad):
    """Short class name of an AssetData, across the 5.x asset-class API shuffle."""
    try:
        return str(ad.get_class_path().asset_name)
    except Exception:
        return str(ad.get_editor_property("asset_class_path").asset_name)


def _pkg(ad):
    return str(ad.get_editor_property("package_name"))


def _name(ad):
    return str(ad.get_editor_property("asset_name"))


def _assets_under(root, class_names=None):
    f = unreal.ARFilter(package_paths=[unreal.Name(root)], recursive_paths=True,
                        class_names=class_names or [])
    return _ar().get_assets(f)


def _game_roots():
    """Top-level /Game/<Root> folders (the packs)."""
    paths = unreal.EditorAssetLibrary.list_assets("/Game", recursive=False,
                                                  include_folder=True)
    return sorted({p.rstrip("/").split("/")[-1] for p in paths if p.endswith("/")})


# ── family inference ─────────────────────────────────────────────────────────────
# Families are what an agent plans with ("place a Pine_Tree"); variants are what paint
# randomises over (Pine_Tree_01..05). Strip trailing variant numbers and metric size
# suffixes so SM_Pine_Tree_01 and Wall_Window_2_4m collapse onto their family stems.
_SIZE_SUFFIX = re.compile(r"_\d+(?:_\d+)?m$", re.IGNORECASE)   # _4m, _2_4m, _8m
_VARIANT_SUFFIX = re.compile(r"_\d+$")                          # _01, _2
_SM_PREFIX = re.compile(r"^(SM|S)_", re.IGNORECASE)


def _family_of(name):
    stem = _SM_PREFIX.sub("", name)
    prev = None
    while stem != prev:                 # peel repeatedly: Foo_01_4m → Foo
        prev = stem
        stem = _SIZE_SUFFIX.sub("", stem)
        stem = _VARIANT_SUFFIX.sub("", stem)
    return stem or name


# ── mesh measurement (the expensive, cached step) ────────────────────────────────
def _pivot_class(mn_z, mx_z):
    """Where the local origin sits in the mesh's z-range decides how placement grounds it.
    base (origin at the foot — trees, walls) vs center (origin mid-height — some props).
    Getting this wrong buries trees to their waist (SPEC-01's #1 predictable bug)."""
    zr = mx_z - mn_z
    if zr <= 0.01:
        return "other"
    frac = (0.0 - mn_z) / zr             # 0 → origin at min z, 0.5 → centred
    if frac < 0.15:
        return "base"
    if 0.35 <= frac <= 0.65:
        return "center"
    return "other"


def _saved_path(name):
    saved = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_saved_dir())
    return os.path.normpath(os.path.join(saved, name))


def _hydrate_cache():
    """Load the on-disk dims cache into _state once per session (G9). Measured dims are
    expensive (a mesh load each), so persisting them means the cost is paid once ever, not
    once per editor launch."""
    if _state.dims_cache_loaded[0]:
        return
    _state.dims_cache_loaded[0] = True
    path = _saved_path(_DIMS_CACHE_NAME)
    if os.path.exists(path):
        try:
            with open(path) as f:
                _state.dims_cache.update(json.load(f))
        except Exception:
            pass


def _save_cache():
    try:
        with open(_saved_path(_DIMS_CACHE_NAME), "w") as f:
            json.dump(_state.dims_cache, f)
    except Exception:
        pass


def _measure_mesh(path, load=True):
    """Return cached dims/pivot/materials for a StaticMesh, measuring (a mesh load) only if
    uncached and `load` is True. Returns None if unmeasured-and-not-loading, or if the
    asset isn't a StaticMesh (skeletal/other are inventoried from the registry only)."""
    hit = _state.cached_dims(path)
    if hit is not None:
        return hit
    if not load:
        return None
    m = _ue.load_asset(path)
    if not isinstance(m, unreal.StaticMesh):
        return None
    bb = m.get_bounding_box()
    mn, mx = bb.min, bb.max
    slots = [str(s.material_slot_name) for s in m.static_materials]
    measured = {
        "dims_cm": [round(mx.x - mn.x, 1), round(mx.y - mn.y, 1), round(mx.z - mn.z, 1)],
        "local_z": [round(mn.z, 1), round(mx.z, 1)],
        "pivot": _pivot_class(mn.z, mx.z),
        "material_slots": len(slots),
        "slot_names": slots,
    }
    return _state.cache_dims(path, measured)


def _reg_facts(ad):
    """Registry-only facts (no mesh load): Nanite flag, LOD0 triangle count, collision."""
    def tag(t):
        try:
            return ad.get_tag_value(t)
        except Exception:
            return None
    tris = tag("Triangles")
    return {
        "nanite": (tag("NaniteEnabled") == "True"),
        "tris": int(tris) if tris and str(tris).isdigit() else None,
        "collision": tag("CollisionComplexity"),
    }


# ── actions ──────────────────────────────────────────────────────────────────────
def handle(p):
    _hydrate_cache()
    op = p.get("op", "packs")
    fn = {
        "packs": _a_packs, "inventory": _a_inventory, "describe": _a_describe,
        "find": _a_find, "whats_new": _a_whats_new,
    }.get(op)
    if fn is None:
        if op == "instance_material":
            return {"error": "material authoring moved to its own verb — use "
                             "material op=instance parent=… name=…"}
        return {"error": f"unknown asset op '{op}'. known: "
                         "packs|inventory|describe|find|whats_new"}
    return fn(p)


def _class_counts(root):
    """root is a bare pack name (e.g. 'Megaplant_Library'); expand to its /Game path."""
    d = {}
    for a in _assets_under(f"/Game/{root}"):
        c = _class_name(a)
        d[c] = d.get(c, 0) + 1
    return d


def _a_packs(p):
    """Top-level Content roots with per-class counts + a one-line character. Registry
    only — no mesh loads, cheap."""
    out = {}
    for root in _game_roots():
        counts = _class_counts(root)
        sm = counts.get(STATIC_MESH, 0)
        char = _PACK_CHARACTER.get(root)
        summary = f"{sm} static meshes" if sm else f"{sum(counts.values())} assets"
        if char:
            summary += f" — {char}"
        out[root] = {"path": f"/Game/{root}", "counts": counts, "summary": summary}
    return {"packs": out, "root_count": len(out)}


def _a_inventory(p):
    """The workhorse. Registry-cheap and compact by DEFAULT: families + variant names +
    tris + Nanite come free (no mesh load); dims/pivot are filled from cache where present,
    null otherwise. Modes:
      - default: one compact dict per family (what you plan with).
      - family="Pine_Tree": full per-variant detail for one family, measuring just those.
      - measure=true, budget=N: warm the dims cache in bounded batches (default 60/call),
        returning {measured, remaining, complete} so it never blocks the bridge (G9).
    Skeletal meshes are counted but excluded (foliage painting is static-mesh only)."""
    pack = p.get("pack")
    if not pack:
        return {"error": "inventory requires pack= (a /Game root name or full path)"}
    root = pack if pack.startswith("/Game") else f"/Game/{pack}"
    only_family = p.get("family")

    reg = {_pkg(a): a for a in _assets_under(root, [STATIC_MESH])}
    skeletal_n = len(_assets_under(root, [SKELETAL_MESH]))

    # Bounded warm-up: load up to `budget` uncached meshes OR `seconds` of wall-clock,
    # whichever hits first. The count budget alone wedged the bridge for 13 minutes on a
    # cold Nanite pack (bugs.md B6) — first-load cost per mesh varies by orders of
    # magnitude, so only the clock actually protects the transport timeout.
    if p.get("measure"):
        import time
        budget = int(p.get("budget", _MEASURE_BUDGET))
        seconds = float(p.get("seconds", 20.0))
        deadline = time.monotonic() + seconds
        uncached = [pp for pp in reg if _state.cached_dims(pp) is None]
        done = 0
        for pp in uncached[:budget]:
            _measure_mesh(pp, load=True)
            done += 1
            if time.monotonic() > deadline:
                break
        _save_cache()
        remaining = max(0, len(uncached) - done)
        out = {"pack": root, "measured_this_call": done,
               "remaining": remaining, "complete": remaining == 0,
               "cached_total": sum(1 for pp in reg if _state.cached_dims(pp))}
        if remaining and done < min(budget, len(uncached)):
            out["note"] = (f"stopped at the {round(seconds)}s wall-clock budget "
                           f"(B6: one slow batch must never outlive the bridge timeout) "
                           f"— call again to continue")
        return out

    families = {}   # fam -> list of variant records (registry facts + cached dims if any)
    for path, ad in reg.items():
        name = _name(ad)
        fam = _family_of(name)
        if only_family and fam != only_family:
            continue
        facts = _reg_facts(ad)
        # In family-drill mode, measure the (few) uncached meshes now; else cache-only.
        measured = _measure_mesh(path, load=bool(only_family))
        families.setdefault(fam, []).append({
            "name": name, "path": path,
            "dims_cm": measured["dims_cm"] if measured else None,
            "pivot": measured["pivot"] if measured else None,
            "material_slots": measured["material_slots"] if measured else None,
            "tris": facts["tris"], "nanite": facts["nanite"],
        })
    if only_family:
        _save_cache()

    def _range(vals):
        vals = [v for v in vals if v is not None]
        return [round(min(vals), 1), round(max(vals), 1)] if vals else None

    grouped = {}
    for fam, vs in sorted(families.items()):
        vs.sort(key=lambda v: v["name"])
        measured_vs = [v for v in vs if v["dims_cm"]]
        # G27: height alone made "tall" read as "tree" (a 9.7 m bush). Footprint + the
        # height:width aspect put SILHOUETTE on the family line where selection happens —
        # aspect ≈1 is a blob/bush; a canopy tree with a trunk runs well above 1.
        widths = [max(v["dims_cm"][0], v["dims_cm"][1]) for v in measured_vs]
        pairs = [(v, round(v["dims_cm"][2] / w, 2))
                 for v, w in zip(measured_vs, widths) if w > 0.01]
        aspects = [a for _, a in pairs]

        # G38: the aspect tell PEAKS — past ~3 a "tall tree" is usually a bare spire/
        # snag (thin trunk, a wisp of canopy at the top), and a low tris-per-metre-of-
        # height corroborates it (the L1 burn: aspect-5.1 pine at ~190 tris/m rendered
        # as a pole; its leafy aspect-1.8 sibling ran ~716). Flag suspects on the family
        # line, where species selection happens.
        def _tpm(v):
            h_m = v["dims_cm"][2] / 100.0
            return (v["tris"] / h_m) if v["tris"] and h_m > 0.01 else None
        full_best = max((t for t in (_tpm(v) for v, a in pairs if a < 3.0) if t),
                        default=None)
        spires = []
        for v, a in pairs:
            t = _tpm(v)
            if a < 3.0 or (t and full_best and t >= 0.6 * full_best):
                continue
            tell = f"{v['name']} (aspect {a}"
            if t and full_best:
                tell += f", {round(t)} tris/m vs {round(full_best)} in fuller siblings"
            spires.append(tell + ")")
        entry = {
            "count": len(vs),
            "variants": [v["name"] for v in vs],
            "pivot": (measured_vs[0]["pivot"] if measured_vs else None),
            "nanite": all(v["nanite"] for v in vs),
            "measured": f"{len(measured_vs)}/{len(vs)}",
            "height_range_cm": _range([v["dims_cm"][2] for v in measured_vs]),
            "footprint_range_cm": _range(widths),
            "aspect_h_over_w": _range(aspects),
        }
        if spires:
            entry["sparse_spire"] = (
                "likely bare spire/snag, NOT a fuller tree (the aspect tell peaks ≳3): "
                + "; ".join(spires)
                + " — verify solo before weighting a stand toward these (G38)")
        if only_family:                 # drill mode carries full per-variant detail
            entry["detail"] = vs
        grouped[fam] = entry

    unmeasured = sum(1 for path in reg if _state.cached_dims(path) is None)
    return {
        "pack": root, "families": grouped, "family_count": len(grouped),
        "static_mesh_count": len(reg), "skeletal_ignored": skeletal_n,
        "unmeasured": unmeasured,
        "hint": (f"{unmeasured} meshes have no cached dims — call inventory(measure=true) "
                 "to warm them, or inventory(family=…) to drill one family"
                 if unmeasured and not only_family else None),
    }


def _resolve_asset_path(query, classes=None):
    """Turn an inventory short name (or family+variant) or full path into a concrete
    asset path. Returns (path, candidates): path set on a unique hit, else candidates
    lists the ambiguous matches for the caller to disambiguate. `classes` narrows the
    search (default: meshes + blueprints; terrain/spline pass material classes — G25)."""
    if query.startswith("/Game"):
        return query, []
    # Exact name wins over fuzzy — but the same name can belong to BOTH a StaticMesh and a
    # Blueprint (this pack ships Wall_4m as each). Collect all exact matches and flag the
    # collision rather than silently returning whichever the registry yields first.
    exact, fuzzy = [], []
    for ad in _assets_under("/Game", classes or [STATIC_MESH, BLUEPRINT]):
        n = _name(ad)
        if n == query:
            exact.append(_pkg(ad))
        elif query.lower() in n.lower() or _family_of(n) == query:
            fuzzy.append(_pkg(ad))
    if len(exact) == 1:
        return exact[0], []
    if len(exact) > 1:
        return None, sorted(exact)
    if len(fuzzy) == 1:
        return fuzzy[0], []
    return None, sorted(fuzzy)


def _a_describe(p):
    """One asset in full: dims, pivot, materials, collision, and referencers/dependencies
    (what a cabin BP pulls in). Accepts a short name or a full /Game path."""
    q = p.get("asset")
    if not q:
        return {"error": "describe requires asset= (short name or /Game path)"}
    path, candidates = _resolve_asset_path(
        q, classes=[STATIC_MESH, BLUEPRINT, "Material", "MaterialInstanceConstant"])
    if path is None:
        if not candidates:
            return {"error": f"no asset matches '{q}'"}
        return {"error": f"'{q}' is ambiguous", "candidates": candidates[:25],
                "candidate_count": len(candidates)}

    ad_list = _ar().get_assets_by_package_name(unreal.Name(path.split(".")[0]))
    cls = _class_name(ad_list[0]) if ad_list else "?"
    out = {"asset": q, "path": path, "class": cls}
    if cls in ("Material", "MaterialInstanceConstant"):
        return _describe_material(path, out)
    measured = _measure_mesh(path)
    if measured is not None:
        _save_cache()
        out.update({"dims_cm": measured["dims_cm"], "pivot": measured["pivot"],
                    "local_z": measured["local_z"], "slot_names": measured["slot_names"]})
        if ad_list:
            out.update(_reg_facts(ad_list[0]))
    # dependency graph (registry): what this asset references, and what references it.
    pkg = unreal.Name(path.split(".")[0])
    try:
        deps = _ar().get_dependencies(pkg, unreal.AssetRegistryDependencyOptions(
            include_hard_package_references=True))
        refs = _ar().get_referencers(pkg, unreal.AssetRegistryDependencyOptions(
            include_hard_package_references=True))
        out["dependency_count"] = len(deps or [])
        out["referencer_count"] = len(refs or [])
    except Exception as e:
        out["dependency_note"] = f"dep query unavailable: {e}"
    return out


def _describe_material(path, out):
    """G32: the material VET — will this dress a mesh surface, and will it hold still?
    Suitability (domain/blend/master) and MOTION (world-position-offset) are invisible to
    every mechanical read — collision never moves — so they must be read off the material
    graph BEFORE a mesh wears it. Three L1 burns behind this: a foliage-card master
    rendering checkerboard, a diorama pond master rendering as a mirror, and a hardcoded
    whole-mesh bob that took three user reports to corner."""
    m = _ue.load_asset(path)
    if m is None:
        out["note"] = "material could not be loaded"
        return out
    mel = unreal.MaterialEditingLibrary
    chain = []
    cur = m
    while isinstance(cur, unreal.MaterialInstance):
        parent = cur.get_editor_property("parent")
        if parent is None:
            break
        chain.append(parent.get_path_name().split(".")[0])
        cur = parent
    base = m.get_base_material()
    if base is None:
        out["warnings"] = ["no base material resolves — the instance chain is broken"]
        return out
    domain = base.get_editor_property("material_domain")
    blend = base.get_editor_property("blend_mode")
    out.update({
        "master": base.get_path_name().split(".")[0],
        "parent_chain": chain,
        "domain": str(domain).split(".")[-1].split(":")[0],
        "blend_mode": str(blend).split(".")[-1].split(":")[0],
        "two_sided": bool(base.get_editor_property("two_sided")),
        "parameters": {
            "texture": [str(n) for n in mel.get_texture_parameter_names(base)],
            "scalar": [str(n) for n in mel.get_scalar_parameter_names(base)],
            "vector": [str(n) for n in mel.get_vector_parameter_names(base)],
        },
    })
    warnings = []
    kind, note = material_motion(base)
    if kind is not None:
        out["motion"] = kind
    if kind in ("wpo", "pivot_wpo", "masked_wind"):
        out["has_world_position_offset"] = True
    if kind in ("wpo", "wpo_suspect", "pivot_wpo"):
        warnings.append(note)
    elif kind in ("masked_wind", "unreadable"):
        out["motion_note"] = note
    if not out["master"].startswith("/Game"):
        warnings.append(f"master lives outside /Game ({out['master']}) — engine/plugin "
                        "materials often expect runtime data this mesh won't have")
    if domain != unreal.MaterialDomain.MD_SURFACE:
        warnings.append(f"domain {out['domain']} — will NOT render as a mesh surface "
                        "material (decal/UI/post-process)")
    if warnings:
        out["warnings"] = warnings
    elif kind == "masked_wind":
        out["verdict"] = "surface-suitable, base-anchored (masked wind only)"
    elif kind is None:
        out["verdict"] = "surface-suitable and motionless (opaque/masked surface master, no WPO)"
    return out


# ── motion classification (G39) ──────────────────────────────────────────────────
# The per-property WPO pin read goes BLIND on a use_material_attributes master (the whole
# graph routes through one MaterialAttributes pin, so get_material_property_input_node
# returns None even when displacement is wired) — which is exactly how the worst-bobbing
# plugin master slipped the vet. Classify from BOTH the pin and the parameter names, and
# separate base-anchored masked wind (fine) from whole-mesh displacement (bobs).
_DISPLACE_TOKENS = ("displace", "sway", "bend", "bob")

# G40: object-space expressions inside a WPO subgraph anchor the motion to the OBJECT
# pivot/bounds — legitimate per-actor, but on an instanced component (ISM/foliage) they
# resolve to the WHOLE component, so every instance translates rigidly instead of bending.
_OBJECT_SPACE_TOKENS = ("ObjectPosition", "ObjectRadius", "ObjectBounds",
                        "ObjectLocalBounds", "ActorPosition")


def _wpo_object_space_refs(base, wpo):
    """Walk the WPO subgraph from its input node; return the object-space expression
    names found (the G40 pivot-anchoring tell), [] when the WPO is purely world-space."""
    mel = unreal.MaterialEditingLibrary
    seen, stack, refs = set(), [wpo], set()
    while stack:
        e = stack.pop()
        if e is None or e.get_name() in seen:
            continue
        seen.add(e.get_name())
        cn = type(e).__name__
        if any(t in cn for t in _OBJECT_SPACE_TOKENS):
            refs.add(cn.replace("MaterialExpression", ""))
        elif "TransformPosition" in cn:
            try:
                src = e.get_editor_property("transform_source_type")
                if src == unreal.MaterialPositionTransformSource.TRANSFORMPOSSOURCE_LOCAL:
                    refs.add("TransformPosition(local→world)")
            except Exception:
                pass
        try:
            stack.extend(mel.get_inputs_for_material_expression(base, e))
        except Exception:
            pass
    return sorted(refs)


def material_motion(base):
    """Classify whether a master material MOVES the meshes wearing it. Returns
    (kind, note): kind is None (still) | "masked_wind" | "pivot_wpo" | "wpo" |
    "wpo_suspect" | "unreadable"."""
    mel = unreal.MaterialEditingLibrary
    scalars = [str(n).lower() for n in mel.get_scalar_parameter_names(base)]
    wind_masked = any("wind" in s and "weight" in s for s in scalars)
    displaced = [s for s in scalars if any(t in s for t in _DISPLACE_TOKENS)]
    uma = bool(base.get_editor_property("use_material_attributes"))
    wpo = None if uma else mel.get_material_property_input_node(
        base, unreal.MaterialProperty.MP_WORLD_POSITION_OFFSET)
    if wpo is not None and wind_masked:
        return ("masked_wind",
                "vertex-masked wind WPO (Wind Weight): base stays anchored, leaves sway "
                "— the safe foliage animation")
    if wpo is not None:
        refs = _wpo_object_space_refs(base, wpo)
        if refs:
            return ("pivot_wpo",
                    f"pivot-anchored WPO ({', '.join(refs)} in the WPO graph): a "
                    "legitimate base-anchored bend on a lone actor, but on an instanced "
                    "component (ISM/foliage) object-space resolves to the WHOLE component "
                    "— every instance translates rigidly instead of bending (G40)")
        return ("wpo", "has WORLD-POSITION-OFFSET: every mesh wearing it MOVES (wind/"
                       "bob/deform) — no mechanical read can see this, and a master "
                       "built for another system (foliage plugin, diorama) deforms "
                       "arbitrary meshes wildly")
    if uma and (displaced or wind_masked):
        via = ", ".join(displaced) if displaced else "wind params"
        return ("wpo_suspect",
                f"material-attributes master carrying displacement params ({via}) — the "
                "WPO pin is unreadable on this graph but displacement is wired; without "
                "the runtime vertex data its own system supplies, the WHOLE mesh moves "
                "(trunk bobs, not leaves — G39)")
    if uma:
        return ("unreadable", "material-attributes master — the WPO pin can't be read, "
                              "so 'motionless' can't be certified mechanically")
    return (None, None)


_MOTION_RANK = {None: 0, "unreadable": 1, "masked_wind": 2, "wpo_suspect": 3, "wpo": 4,
                "pivot_wpo": 5}
_motion_cache = {}      # material path → (kind, note); session-lifetime


def _mesh_motion(mesh):
    """Worst motion verdict across a StaticMesh's material slots. (kind, note)."""
    worst = (None, None)
    for sm in mesh.static_materials:
        mi = sm.material_interface
        if mi is None:
            continue
        key = mi.get_path_name()
        hit = _motion_cache.get(key)
        if hit is None:
            base = mi.get_base_material()
            hit = material_motion(base) if base is not None else (None, None)
            _motion_cache[key] = hit
        if _MOTION_RANK[hit[0]] > _MOTION_RANK[worst[0]]:
            worst = hit
    return worst


def motion_notes(mesh_paths):
    """Author-time WPO notice for meshes about to be painted/added (G39): a population
    that will MOVE is announced when it is authored, not discovered in PIE. Masked wind
    is named as safe; unmasked/suspected displacement is a loud per-mesh warning."""
    moving, masked = {}, 0
    for pp in mesh_paths:
        m = _ue.load_asset(pp)
        if not isinstance(m, unreal.StaticMesh):
            continue
        kind, note = _mesh_motion(m)
        if kind in ("wpo", "wpo_suspect", "pivot_wpo"):
            moving.setdefault((kind, note), []).append(pp.rsplit("/", 1)[-1])
        elif kind == "masked_wind":
            masked += 1
    # G40: painting IS instancing — a pivot-anchored WPO doesn't just move, it moves WRONG.
    notes = [("MOVES WRONG when instanced" if kind == "pivot_wpo" else "ANIMATES")
             + f" ({', '.join(names[:4])}{', …' if len(names) > 4 else ''}): {note}"
             for (kind, note), names in moving.items()]
    if masked:
        notes.append(f"{masked} mesh(es) carry vertex-masked wind (Wind Weight) — base "
                     "anchored, leaves sway; the safe kind")
    return notes


def _a_find(p):
    """Name-substring + class filter across the whole project."""
    query = (p.get("query") or "").lower()
    kind = p.get("kind", "mesh")
    class_names = {"mesh": [STATIC_MESH], "blueprint": [BLUEPRINT],
                   "skeletal": [SKELETAL_MESH], "any": [],
                   "material": ["Material", "MaterialInstanceConstant"],
                   }.get(kind, [STATIC_MESH])
    hits = []
    for ad in _assets_under("/Game", class_names):
        n = _name(ad)
        if not query or query in n.lower():
            hits.append({"name": n, "path": _pkg(ad), "class": _class_name(ad)})
    hits.sort(key=lambda h: h["name"])
    return {"query": p.get("query"), "kind": kind, "count": len(hits),
            "matches": hits[:200], "truncated": len(hits) > 200}


def _snapshot_path():
    saved = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_saved_dir())
    return os.path.normpath(os.path.join(saved, _SNAPSHOT_NAME))


def _current_snapshot():
    return {root: _class_counts(root) for root in _game_roots()}


def _a_whats_new(p):
    """Diff current registry roots/counts against a persisted snapshot — how "Ryan just
    downloaded something" becomes agent-visible. Persisted to Saved/ so it survives editor
    restarts. On any detected change the measured-dims cache is invalidated so re-imports
    get re-measured. Pass commit=false to peek without updating the snapshot."""
    current = _current_snapshot()
    path = _snapshot_path()
    prev = {}
    if os.path.exists(path):
        try:
            with open(path) as f:
                prev = json.load(f)
        except Exception:
            prev = {}

    added_roots = sorted(set(current) - set(prev))
    removed_roots = sorted(set(prev) - set(current))
    changed = {}
    for root in set(current) & set(prev):
        if current[root] != prev[root]:
            changed[root] = {"before": prev[root], "after": current[root]}

    has_changes = bool(added_roots or removed_roots or changed)
    if has_changes:
        # Evict ONLY the changed/removed roots' entries (G29): nuking the whole cache on
        # any diff re-priced every measured pack at 13 min/66 meshes for one unrelated
        # download. A removed pack's dead entries leave with it; untouched packs keep theirs.
        stale_roots = set(removed_roots) | set(added_roots) | set(changed)
        stale = [pp for pp in list(_state.dims_cache)
                 if pp.split("/")[2:3] and pp.split("/")[2] in stale_roots]
        _state.invalidate_dims(stale)
        _save_cache()                     # persist the eviction so disk agrees

    if p.get("commit", True):
        try:
            with open(path, "w") as f:
                json.dump(current, f, indent=2)
        except Exception as e:
            return {"error": f"could not write snapshot: {e}"}

    return {"first_run": not prev, "changed": has_changes,
            "added_roots": added_roots, "removed_roots": removed_roots,
            "changed_packs": changed, "snapshot": path}
