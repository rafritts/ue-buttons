"""SPEC-07 — the context-mismatch rule engine.

The general defect class: an asset authored under one usage assumption, used under
another. Neither side is wrong in isolation — the defect lives in the PAIRING, which is
why UE's native linters (asset-scoped Data Validation, level-scoped Map Check) are
structurally blind to it (G41). A rule is therefore a pairing test:

    asset predicate × usage predicate → verdict

Rules are DATA (the RULES table); machinery is generic and built once (the graph
walker, the certificate cache, the gate, the census). Adding a defect class costs a
table row — and a row is added only when dogfooding produces the defect (the gaps.md
ratchet; no speculative rules).

Three firing points, same table:
  1. author-time gate  — gate() in the mutating verbs, BEFORE the world changes.
     severity "breaks" REFUSES (force=True overrides); "degrades" warns and proceeds.
  2. status-block census — census_lines() on every mutating/spatial op: the safety net
     for defects introduced outside the verb surface (a human dragging assets in).
  3. on-demand sweep — SPEC-08 evaluates the same table level-wide via validate.

Certificates, not stored flags: UE has NO "safe to instance" field anywhere
(StaticMesh, material, FoliageType — verified live), and folder names are noise (the
G40 pine ships in a folder literally named Foliage/). Verdicts are computed per
(asset, rule) and cached for the session — R1 rides asset._motion_cache, R2 rides
_cert_cache below.
"""
import unreal

from . import _ue

# ── the generic material-graph walker (predicate machinery, built once) ────────────
def graph_refs(base, roots, tokens, local_transform_tell=False):
    """Walk the expression subgraph(s) upstream of `roots` (material-expression nodes)
    via get_inputs_for_material_expression; return the sorted class names matching
    `tokens`. local_transform_tell additionally reports local-source TransformPosition
    nodes (the G40 pivot-anchoring tell — a local→world transform anchors to the
    object origin exactly like an Object* node does)."""
    mel = unreal.MaterialEditingLibrary
    seen, refs = set(), set()
    stack = [r for r in roots if r is not None]
    while stack:
        e = stack.pop()
        if e is None or e.get_name() in seen:
            continue
        seen.add(e.get_name())
        cn = type(e).__name__
        if any(t in cn for t in tokens):
            refs.add(cn.replace("MaterialExpression", ""))
        elif local_transform_tell and "TransformPosition" in cn:
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


# ── asset predicates (one per rule; evidence string or None) ────────────────────────
_cert_cache = {}    # (material_path, rule_id) → evidence list; session-lifetime

# R2: nodes that only have data INSIDE an instanced component.
_PER_INSTANCE_TOKENS = ("PerInstanceRandom", "PerInstanceCustomData")
# The main property pins worth walking for R2 (per-instance nodes usually feed color
# variation, but nothing stops them anywhere else).
_MAIN_PROPS = ("MP_BASE_COLOR", "MP_METALLIC", "MP_SPECULAR", "MP_ROUGHNESS",
               "MP_EMISSIVE_COLOR", "MP_OPACITY", "MP_OPACITY_MASK", "MP_NORMAL",
               "MP_WORLD_POSITION_OFFSET", "MP_AMBIENT_OCCLUSION", "MP_SUBSURFACE_COLOR")


def _r1_evidence(mesh):
    """Pivot-anchored WPO on any of the mesh's materials — G40's tell. Delegates to the
    motion classifier (asset._mesh_motion, cached per material)."""
    from . import asset
    kind, note = asset._mesh_motion(mesh)
    if kind != "pivot_wpo":
        return None
    # note head: "pivot-anchored WPO (ObjectRadius, … in the WPO graph)"
    return note.split(":", 1)[0]


def _per_instance_refs(base):
    if bool(base.get_editor_property("use_material_attributes")):
        return []   # pin reads are blind on a material-attributes master (same limit
                    # as the motion classifier — G39's uma caveat)
    mel = unreal.MaterialEditingLibrary
    roots = []
    for pname in _MAIN_PROPS:
        prop = getattr(unreal.MaterialProperty, pname, None)
        if prop is None:
            continue
        try:
            n = mel.get_material_property_input_node(base, prop)
        except Exception:
            n = None
        if n is not None:
            roots.append(n)
    return graph_refs(base, roots, _PER_INSTANCE_TOKENS)


def _r2_evidence(mesh):
    """Per-instance material nodes on any of the mesh's materials — the G40 converse."""
    refs = set()
    for sm in mesh.static_materials:
        mi = sm.material_interface
        if mi is None:
            continue
        key = (mi.get_path_name(), "R2")
        if key not in _cert_cache:
            base = mi.get_base_material()
            _cert_cache[key] = _per_instance_refs(base) if base is not None else []
        refs.update(_cert_cache[key])
    return ", ".join(sorted(refs)) if refs else None


# ── the rule table (data — one row per dogfooded defect class) ──────────────────────
# id: never reused (gap-number discipline). gap: the dogfooded defect that earned the
# row. tier: cheapest tier that can catch it (static | census | pie). usage: which
# binding fires it. severity: breaks (gate refuses) | degrades (gate warns).
RULES = [
    {"id": "R1", "gap": "G40", "tier": "census", "usage": "instanced",
     "severity": "breaks",
     "title": "pivot-anchored WPO breaks under instancing",
     "evidence": _r1_evidence,
     "verdict": "will float rigidly as instances — {evidence}: object-space resolves to "
                "the WHOLE component, every instance translates instead of bending",
     "alternative": "place them standalone via `add` (motion is correct on a lone "
                    "actor), or pick motion-safe meshes — asset op=describe shows the "
                    "motion verdict (None/masked_wind are safe)"},
    {"id": "R2", "gap": "G40-converse", "tier": "census", "usage": "standalone",
     "severity": "breaks",
     "title": "per-instance material nodes require instancing",
     "evidence": _r2_evidence,
     "verdict": "use per-instance material nodes ({evidence}) — a standalone actor has "
                "no per-instance data, so those nodes render as constants",
     "alternative": "scatter it via foliage op=paint (instancing supplies the data), "
                    "or pick a mesh whose materials carry no PerInstance* nodes"},
]


def _mesh_for(path_or_mesh):
    if isinstance(path_or_mesh, unreal.StaticMesh):
        return path_or_mesh
    m = _ue.load_asset(path_or_mesh)
    return m if isinstance(m, unreal.StaticMesh) else None


# ── firing point 1: the author-time gate ────────────────────────────────────────────
def gate(mesh_paths, usage, force=False, reissue="re-issue the same call"):
    """Evaluate every rule row matching `usage` ("instanced" | "standalone") against
    the meshes about to be bound to it. Returns (refusal, notes): refusal is an
    error-shaped dict when a breaks-severity row fires unforced (the verb must return
    it INSTEAD of mutating); notes are author-time warnings to ride the result
    (degrades rows, or breaks rows overridden with force=True)."""
    notes = []
    for rule in RULES:
        if rule["usage"] != usage:
            continue
        offenders, evidence = [], set()
        for pp in mesh_paths:
            m = _mesh_for(pp)
            if m is None:
                continue
            ev = rule["evidence"](m)
            if ev:
                offenders.append(m.get_name())
                evidence.add(ev)
        if not offenders:
            continue
        shown = ", ".join(offenders[:5]) + (", …" if len(offenders) > 5 else "")
        verdict = rule["verdict"].format(evidence="; ".join(sorted(evidence)))
        if rule["severity"] == "breaks" and not force:
            return ({"error": f"refused ({rule['id']}/{rule['gap']}): {shown} {verdict}",
                     "rule": rule["id"], "offenders": offenders,
                     "next": {
                         "override": f"{reissue} with force=true — plants anyway; the "
                                     "census keeps flagging it",
                         "alternative": rule["alternative"]}}, [])
        prefix = ("forced past " + rule["id"] if rule["severity"] == "breaks"
                  else rule["id"])
        notes.append(f"{prefix}/{rule['gap']}: {shown} {verdict}")
    return (None, notes)


# ── firing point 2: the status-block census ─────────────────────────────────────────
def census_lines():
    """Level-wide census of every census-tier rule; one warning line per firing rule,
    [] when the level is clean (silence, not a report — this is the warning channel).
    Cheap after first classification: verdicts cache per material."""
    from . import foliage
    lines = []
    # R1 at level scale — foliage.motion_census owns the walk over instanced
    # components; its line format predates the table and is load-bearing (G40).
    mc = foliage.motion_census()
    if mc:
        lines.append(mc)
    sc = _standalone_census()
    if sc:
        lines.append(sc)
    return lines


def _standalone_census():
    """R2 at level scale: placed StaticMeshActors wearing per-instance-node materials."""
    bad = []
    for a in _ue.all_actors():
        if not isinstance(a, unreal.StaticMeshActor):
            continue
        c = a.static_mesh_component
        mesh = c.get_editor_property("static_mesh") if c is not None else None
        if mesh is None:
            continue
        if _r2_evidence(mesh):
            bad.append(a.get_actor_label())
    if not bad:
        return None
    shown = ", ".join(sorted(bad)[:4]) + (", …" if len(bad) > 4 else "")
    return (f"per-instance: {len(bad)} standalone actor(s) wear per-instance-node "
            f"materials — no instance data outside instancing, nodes render as "
            f"constants (R2): {shown}")
