# SPEC-06 — Symptom probes: the diagnostic verb layer

Status: **DRAFT / STUB** — deliberately rough. Shaped after SPEC-05's editor-poking
session; do not implement from this document as-is.

## Reframe from the 2026-07-03 session: ONE rule engine, not a probe collection

The G40 spelunk (whole trees floating — pivot-anchored WPO under foliage instancing)
reshaped this spec's core idea. Probes must NOT be bespoke per-symptom tools. The general
defect class is **context mismatch**: an asset authored under one usage assumption, used
under another. Neither the asset nor the level is wrong in isolation — the defect lives in
the pairing, which is exactly why UE's native linters (asset-scoped Data Validation,
level-scoped Map Check) are structurally blind to it (G41).

Design consequences:
- **Rules are data, machinery is generic.** One engine evaluates a rule table of
  `asset predicate × usage predicate → verdict`. Adding a defect class costs a table row,
  not a tool. The machinery built once: a material-graph walker, mesh-property readers,
  a census loop.
- **Certificates, not stored flags.** UE has NO "safe to instance" field anywhere
  (StaticMesh, material, FoliageType — verified live). The verdict is a certificate we
  COMPUTE per (mesh, material set, intended usage) and cache — like G39's motion cache,
  one level richer. Folder names / naming conventions are noise (the G40 pine ships in a
  folder literally named `Foliage/`).
- **Three firing points, same rule:** (1) author-time gate in the mutating verbs
  (`scatter`/`add` refuse-or-warn BEFORE planting — primary defense: the G40 pines were
  planted by OUR OWN scatter verb, so the gate covers the real workflow), (2) level-wide
  census on the status block (safety net for defects introduced outside the verb surface),
  (3) on-demand sweep (SPEC-07). A probe, a lint rule, and an author-time warning are the
  same row evaluated at different moments.
- **The gate UX** (the user's words, near-verbatim): "These pine variants will float
  rigidly as instances (trunk WPO is pivot-anchored). Want them standalone (motion is
  correct there), or should I pick motion-safe trees from inventory?" Both escape hatches
  compute from the same census.
- **No speculative rules — the gaps.md ratchet.** A row is added only when dogfooding
  produces the defect. The taxonomy is finite and industry-shared (~a dozen mismatch
  classes: WPO×instancing both directions, vertex-data×mesh, Nanite×feature,
  usage-flags×packaging, lightmap-UVs×static-lighting, pivot×snapping,
  non-uniform-scale×instancing…). Worst-case spelunking happens once per CLASS, and the
  class count is bounded — a ratchet with a ceiling, not a cathedral.

First two rows, live-verified 2026-07-03:
1. WPO subgraph contains object-space nodes (`ObjectRadius`, `ObjectPosition`,
   `ObjectBounds`, `ActorPosition`, local-origin transforms — a ~15-line generic graph
   walk found `ObjectRadius` in `MM_Tree_Trunk`) × mesh used in ISM/foliage component →
   rigid float (G40). Statically: `used_with_instanced_static_meshes=True` on a
   pivot-WPO master is the smoking gun without touching the level.
2. Converse: per-instance nodes (`PerInstanceRandom`, `PerInstanceCustomData`) × placed
   as a standalone actor → those nodes REQUIRE instancing; same walk, opposite direction.

Known readability limits (5.8, verified): mesh vertex-color presence is NOT exposed to
Python via the obvious APIs (`has_vertex_colors` absent, mesh-description API absent) —
the "masked wind but no mask painted" rule needs a workaround. UV channel count IS
readable (`StaticMeshEditorSubsystem.get_num_uv_channels`).

## Problem

Every visual symptom the user reports has a non-visual cause living in a machine-readable
surface (material graph, collision metadata, light settings, AABB math). Today each such
report turns into ad-hoc probe.sh archaeology. This spec makes the symptom→cause bridge a
first-class surface: the user points (SPEC-05) and names a symptom in plain words; the
agent runs the matching probe and confirms or refutes mechanically.

## Scope (rough)

Probably ONE `diagnose` verb with ops, not new verbs. Candidate ops:

- `op=material` — the "no texture / grey checkerboard" probe: default/grid material
  detection, null texture params, broken redirectors on a referent.
- `op=flicker` — coplanarity / z-fighting scan near a referent or in a region.
- `op=lighting` — the "too dark / blown out" probe: directional/sky light intensities,
  post-process exposure clamps, auto-exposure range.
- `op=motion` — extends the G39 classifier with param-VALUE sanity (wind speed 50 vs 5000).
- `op=solid` — the "I walked through it" probe: collision complexity, simple-collision
  prim count.

Each op is scoped by a SPEC-05 referent (selection, camera cone, or region). The op list
is expected to GROW by design: every new symptom the user reports becomes a candidate op.

## Open questions

- Verb shape: leaning `validate` extension after 2026-07-03 (one rule engine, three firing
  points — a separate `diagnose` verb now looks like needless surface). Decide against
  real usage.
- Which symptom is actually most frequent in dogfooding? Build that op first, not all five.
- How do probe verdicts feed the status block / notes channel?

## Verification story (rough)

For each op: deliberately break the thing in a scratch level (assign the grid material,
zero out collision, stack two coplanar planes), then confirm the probe finds it and
localizes it — and stays quiet on the clean L1 rebuild.

## Sequencing

After SPEC-05 (needs its referents). SPEC-07's lint sweeps are these probes run
unprompted at level scale.
