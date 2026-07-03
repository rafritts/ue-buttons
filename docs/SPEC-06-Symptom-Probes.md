# SPEC-06 — Symptom probes: the diagnostic verb layer

Status: **DRAFT / STUB** — deliberately rough. Shaped after SPEC-05's editor-poking
session; do not implement from this document as-is.

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

- Verb shape: one `diagnose` verb vs. folding ops into `feel`/`validate`? (Decide against
  real usage, not upfront.)
- Which symptom is actually most frequent in dogfooding? Build that op first, not all five.
- How do probe verdicts feed the status block / notes channel?

## Verification story (rough)

For each op: deliberately break the thing in a scratch level (assign the grid material,
zero out collision, stack two coplanar planes), then confirm the probe finds it and
localizes it — and stays quiet on the clean L1 rebuild.

## Sequencing

After SPEC-05 (needs its referents). SPEC-07's lint sweeps are these probes run
unprompted at level scale.
