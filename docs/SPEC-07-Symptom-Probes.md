# SPEC-07 — Symptom probes: the context-mismatch rule engine

Status: **DESIGN — fleshed out 2026-07-03, ready for sign-off. Not implemented.**
Supersedes the earlier stub; every live-verified fact from the G40/G41 sessions is
retained below. Implement only after sign-off.

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
   - Migration note: R1 currently warns; under this spec it becomes `breaks` and starts
     refusing. That changes paint's behavior on bad palettes — flagged for sign-off.
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

## Verification plan

1. **Port proof:** after moving R1 into the table, the existing G40 behaviors reproduce
   byte-for-byte — paint gate fires on MM_Tree_Trunk palettes, census line unchanged on
   L1 (⚠ 1916/17075), Bush_1 negative control stays quiet.
2. **Generalization proof (R2):** author a scratch material with `PerInstanceRandom`,
   place it standalone via `add` → gate fires with the converse verdict; scatter the
   same mesh via `foliage op=paint` → silent.
3. **Refusal UX:** paint with a `breaks` palette refuses with both escape hatches
   present and fireable; `force=true` plants with the warning.
4. **Cache:** second census on L1 is ~0 s (certificate cache hit), matching today's
   motion-census behavior.

## Sequencing

After SPEC-06 (needs its referents — DONE). Before SPEC-08 (the sweep is this engine at
firing point 3). The R1 port should land first as a pure refactor, then R2 as the
generalization proof.
