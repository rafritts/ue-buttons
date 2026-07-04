# SPEC-07 — Symptom probes: the context-mismatch rule engine

Status: **IMPLEMENTED + live-verified 2026-07-04** (`runtime/ue_buttons/rules.py`; user
signed off on the R1 warn→refuse behavior change and on living without Map Check).
Verification trace at the bottom.

## Problem

Every visual symptom the user reports has a non-visual cause living in a machine-readable
surface (material graph, collision metadata, light settings, AABB math). Today each such
report turns into ad-hoc probe.sh archaeology — the G40 spelunk (whole trees floating)
took a session of manual graph-walking before the cause was named. This spec makes the
symptom→cause bridge a first-class surface, and the G40 session showed what shape it must
take: **one rule engine, not a probe collection.**

## The core idea: context mismatch

The general defect class is **context mismatch**: an asset authored under one usage
assumption, used under another. Neither the asset nor the level is wrong in isolation —
the defect lives in the pairing, which is exactly why UE's native linters (asset-scoped
Data Validation, level-scoped Map Check) are structurally blind to it (G41: stock
validation returns `VALID` on the G40 material; the only Map Check on record reported
0 errors / 0 warnings).

So a rule is a pairing test: `asset predicate × usage predicate → verdict`. Adding a
defect class costs a table row, not a tool.

## Architecture

New module `runtime/ue_buttons/rules.py`. No new verb — verdicts surface through the
existing verbs at three firing points (below). The module owns three things:

### 1. The predicate library (machinery, built once)

Small named functions, each reading one machine surface. The founding members already
exist and get MOVED here, not rebuilt:

- **Material-graph walker** — `asset._wpo_object_space_refs` generalized: walk any input
  pin's subgraph via `MaterialEditingLibrary.get_inputs_for_material_expression`, return
  the expression class names matching a token set. (Today it walks WPO for
  `ObjectPosition/ObjectRadius/ObjectBounds/ObjectLocalBounds/ActorPosition` and
  local-source `TransformPosition`; the generalization is parameterizing the start pin
  and token set.)
- **Motion classifier** — `asset.material_motion` and `_MOTION_RANK`, unchanged; rules
  consume its kinds.
- **Mesh readers** — bounds/height (`get_bounds`), UV channel count
  (`StaticMeshEditorSubsystem.get_num_uv_channels` — verified readable in 5.8),
  simple-collision prim count, Nanite flag.
- **Usage readers** — is this mesh referenced by an ISM/foliage component
  (`foliage._ifa_fismcs` + level census), placed standalone, scattered by a ueb stand
  (component tag), used on terrain vs. a mesh ribbon (material domain check, the G32
  lesson).

Known readability limit (5.8, verified): mesh vertex-color presence is NOT exposed to
Python (`has_vertex_colors` absent, mesh-description API absent). Rules needing it must
declare a higher tier (see `tier` below) rather than fake a static answer.

### 2. The rule table (data)

```python
RULES = [
  Rule(
    id="R1",            # never reused, same discipline as gap numbers
    gap="G40",          # the dogfooded defect that earned the row — REQUIRED
    title="pivot-anchored WPO breaks under instancing",
    tier="static",      # static | census | pie   (cheapest tier that can catch it)
    asset=pred.wpo_has_object_space_refs,      # material → evidence | None
    usage=pred.used_by_instanced_component,    # asset × level → evidence | None
    severity="breaks",  # breaks | degrades
    verdict="pivot-anchored WPO ({refs}) on an instanced component — every instance "
            "translates rigidly instead of bending",
    next=[...],          # ready-to-fire alternatives (HATEOAS — see gate UX)
  ),
  ...
]
```

- A rule FIRES only when both predicates return evidence; the evidence strings
  interpolate into the verdict (provenance, always).
- `tier` implements the cheapest-tier principle shared with SPEC-09: `static` rules
  compute from asset data alone (e.g. R1's smoking gun without touching the level:
  `used_with_instanced_static_meshes=True` on a pivot-WPO master), `census` rules need
  the level walked, `pie` rules can only be answered by SPEC-09's runtime pass.
- **Certificates, not stored flags.** UE has NO "safe to instance" field anywhere
  (StaticMesh, material, FoliageType — verified live), and folder names are noise (the
  G40 pine ships in a folder literally named `Foliage/`). The verdict is computed per
  (asset, rule) and cached session-lifetime, exactly like `asset._motion_cache` — that
  cache becomes the first entry of the general `_certificate_cache` keyed
  `(asset_path, rule_id)`.

### 3. The census loop (machinery, built once)

`foliage.motion_census` generalized: walk the level's instanced components + placed
actors once, evaluate every `census`-tier rule against each (asset, usage) pairing,
aggregate by rule. One walk, N rules — cost does not grow per rule.

## Founding rows (the only rows at implementation time — see the ratchet)

1. **R1 (G40, live-verified 2026-07-03):** WPO subgraph contains object-space nodes ×
   mesh used in ISM/foliage → rigid float. Already implemented as the `pivot_wpo`
   classifier + motion census; SPEC-07's job is to PORT it into the table as row one,
   proving the table shape, not to rebuild it.
2. **R2 (converse of G40):** material uses per-instance nodes (`PerInstanceRandom`,
   `PerInstanceCustomData`) × placed as a standalone actor → those nodes require
   instancing (render as constants/black). Same graph walk, opposite direction. Costs
   one predicate and one row — the cheap proof that the table generalizes.

**No speculative rules — the gaps.md ratchet.** A row is added only when dogfooding
produces the defect. The taxonomy is finite and industry-shared (~a dozen mismatch
classes: WPO×instancing both directions, vertex-data×mesh, Nanite×feature,
usage-flags×packaging, lightmap-UVs×static-lighting, pivot×snapping,
non-uniform-scale×instancing…). Worst-case spelunking happens once per CLASS, and the
class count is bounded — a ratchet with a ceiling, not a cathedral.

## Three firing points, same table

1. **Author-time gate** (primary defense — the G40 pines were planted by OUR OWN paint
   op, so the gate covers the real workflow): `foliage op=paint/reseed`, `add`, and any
   verb that binds an asset to a usage evaluates the applicable rows BEFORE mutating.
   - `severity="breaks"` → **refuse**, with the user's own gate UX (near-verbatim):
     "These pine variants will float rigidly as instances (trunk WPO is pivot-anchored).
     Want them standalone (motion is correct there), or should I pick motion-safe trees
     from inventory?" — both escape hatches as ready-to-fire calls (`force=true` to
     override; an inventory call filtered to motion-safe palettes as the alternative).
   - `severity="degrades"` → **warn and proceed** (today's "MOVES WRONG when instanced"
     note behavior).
   - Migration note: R1 previously warned; it is now `breaks` and refuses (signed off).
     `op=reseed` gates BEFORE removing the old stand — a palette that now refuses must
     not silently delete the stand it fails to replace; a stand painted with force
     stores the force and reseeds without re-asking.
2. **Status-block census** (safety net for defects introduced outside the verb surface —
   a human dragging assets in the editor): the generalized census line on every
   mutating/spatial op, exactly where `⚠ motion: 1916/17075 …` rides today.
3. **On-demand sweep** — SPEC-08. Same table evaluated level-wide; that spec owns the
   sweep loop and findings format, THIS spec owns the rules and the engine.

A probe, a lint rule, and an author-time warning are the same row evaluated at different
moments.

## What happened to the stub's `diagnose` verb and op list

Dropped. `op=motion` and `op=solid` are rules R1/(future collision row); `op=material` /
`op=flicker` / `op=lighting` were speculative — under the ratchet they wait for a
dogfooded defect, and when one lands it becomes a row, not an op. Targeted probing IS
`validate op=run targets=<referent>` (SPEC-06 deixis supplies the referent) plus the
complaint-vocabulary routing table in SPEC-06, which stays the symptom→probe index.

## Verification trace (2026-07-04, all over the bridge)

1. **Port proof:** census line on L1 byte-identical (`⚠ motion: 1916/17075 foliage
   instances FLOAT rigidly … SM_Pine_Tree_01, _02, _03, _05`); R2 census correctly
   silent on L1; understory (masked_wind) never fires.
2. **Refusal UX (R1):** `foliage op=paint` of SM_Pine_Tree_01 on the scratch level →
   `refused (R1/G40): … will float rigidly as instances — pivot-anchored WPO
   (ObjectRadius, TransformPosition(local→world) in the WPO graph)` with both escape
   hatches; `force=true` planted 24 instances carrying THREE block warnings (MOVES
   WRONG note, `forced past R1/G40`, the 24/24 census line); `op=reseed` inherited the
   force (23 planted, no re-ask).
3. **Generalization proof (R2):** authored `M_PerInst` (PerInstanceRandom → BaseColor)
   on a duplicated rock mesh. `add` → `refused (R2/G40-converse): … render as
   constants`; `force=true` spawned with the forced-past note; census flagged the
   standalone actor; `foliage op=paint` of the SAME mesh → planted silently (correct —
   instancing supplies the data).
4. **Cache:** L1 census 0.002 s first call, 0.000 s second (verdicts cache per material).
5. **Casualty → G47:** cleaning the scratch material with `delete_directory` while it
   was natively referenced wedged the editor (handled ensure + hung RC thread; taskkill
   + relaunch). Recorded as gap G47 — polite deletes only, referencers first, unsaved
   assets evaporate on restart.

The `force=` parameter on `add`/`foliage` needs an MCP client reconnect before it is
callable through the tools; verified over the raw bridge meanwhile.

## Sequencing

After SPEC-06 (needs its referents — DONE). Before SPEC-08 (the sweep is this engine at
firing point 3 — `rules.RULES` + the census loop are what SPEC-08's `validate` scope
sweep will consume).
