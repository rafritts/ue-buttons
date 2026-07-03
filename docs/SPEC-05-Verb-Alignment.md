# SPEC-05 — Verb alignment: UE-native names, legible provenance

Status: **DRAFT** — written 2026-07-03 to be shaped with the user before implementation.
This spec comes FIRST in the new family (before SPEC-06..09 deixis/probes/lint/runtime):
diagnostics built on misaligned verbs would harden the misalignment.

Ported doctrine — read both before fleshing out:
- `blender-buttons/docs/SPEC-05-verb-collapse.md`: **one verb per native menu/mode.** Lean
  on the tool knowledge the model already has from training, so schemas specify args
  instead of teaching concepts. The taxonomy is self-closing when it mirrors the native
  UI's own organization.
- `blender-buttons/docs/SPEC-20-verb-provenance.md`: make it legible AT THE CALL SITE
  whether a verb is a native feature made drivable or our invention. Its `scatter` was
  deleted for impersonating a native feature it shared no code with.

## Goal (the user's words, 2026-07-03)

This server will eventually expose **hundreds of tools/ops**. They must be effortless for
the agent to intuit, and the way that stays true at scale is a **near 1-to-1 mapping onto
UE5 constructs**. At ~10 verbs an agent can memorize a private vocabulary; at hundreds it
cannot — the only documentation that scales is the model's own training data, and that
data is written in UE's words. Every op named by its UE construct is an op the agent
already knows before reading the schema; every privately-named op is a permanent tax on
every future session. The taxonomy is also self-closing (bb SPEC-05): when the surface
mirrors UE's own organization, it can't sprawl into a landfill — a new op has one obvious
home, named by the construct it drives.

## Problem

ue-buttons inherited blender-buttons' verb NAMES without re-deriving them from UE's own
taxonomy. The predictability argument cuts in UE's favor too: the model's training is
dense with UE tutorials, docs, and forum posts that use UE's words — Foliage, Landscape,
PCG, Place Actors, Content Browser, Details, Outliner. A verb that uses UE's word for a
UE thing is guessable and self-documenting; a verb that uses OUR word for a UE thing
(or worse, UE's word for a NON-UE thing) forces the agent to memorize a private mapping,
and mis-teaches every reflex the training data provides.

Two live exhibits, one in each direction:

1. **`scatter` hides a native concept (bb's scatter sin, inverted-but-same).** The verb
   IS UE's Foliage system — it writes `InstancedFoliageActor.add_instances()` and mints
   `FoliageType_InstancedStaticMesh` assets — but nothing at the call site says so. A
   UE-trained reflex says "paint foliage"; nothing in the surface answers to "foliage".
   The G40 debugging session had to *discover* that scatter = foliage before it could
   even enumerate the instances. And UE 5.x's modern native scatter is **PCG** (the
   Procedural Content Generation framework) — the cousin audit must decide whether our
   sampler is a from-scratch cousin of PCG (R2 territory) or a legitimate thin layer
   over the Foliage system with a PCG cousin-tag.
2. **`landscape` wears a native name for a non-native thing (the inverse sin).** UE's
   Landscape is a specific system — heightfields, layers, sculpt/paint tools, landscape
   materials, grass types. Our `landscape` verb builds **StaticMesh terrain** precisely
   BECAUSE UE 5.8 Python cannot create real Landscape (known constraint). The name
   promises capabilities (sculpt layers, paint layers, grass) that don't exist here and
   invites every Landscape reflex the training data has. Candidate: rename to `terrain`
   with a cousin tag ("≈ UE Landscape, which Python cannot author; this is mesh terrain —
   no layers/grass-types").

## The rules (ported, UE-translated)

- **One verb per UE-native surface.** Where a verb maps to an editor mode, menu, panel,
  or named system, use UE's own word: Foliage mode → `foliage`, Content Browser →
  `asset`, Place Actors → `add`, Outliner/World Settings → `scene`. Senses (`feel`,
  `validate`) and infrastructure (`history`) keep plain names — nobody mistakes them for
  menu items (bb SENSE family ruling).
- **R1 — native-cousin tag (mandatory).** Any verb/op that parallels a shipped UE feature
  cites it in the schema and states the delta: "≈ Foliage paint, agent-driven sampling
  instead of brush strokes"; "≈ PCG, but immediate instances, no graph asset".
- **R2 — no from-scratch cousin reimplementations.** If UE ships the feature and Python
  can drive it, we wrap it, never rebuild it. (Our scatter already passes half this test —
  storage/rendering IS the native foliage path; the sampling layer is ours.)
- **R3 — provenance from the build, never model memory.** Native-vs-macro is read from
  the verb's implementation (which `unreal.*` APIs it calls). Cousin claims are verified
  against the live 5.8 build — model memory is densest on UE ≤5.3-era APIs and
  self-confirms (today's proof: three deprecated-API surprises in one session:
  `validate_loaded_asset` absent, `has_vertex_colors` unexposed, mesh-description API
  absent).
- **R4 — version anchoring.** The status block / connect handshake should state the
  attached UE version and the version the server was verified against, with a drift
  tripwire. A short "UE 5.8 deltas vs the model's reflexes" primer belongs in the server
  instructions (seed: the ue58-python-constraints list — no Landscape authoring, no
  numpy, no Spline+HISM component-add; grows as R3 finds more).

## The audit (the work of this spec)

Classify every verb and op — `scene, add, transform, select, feel, history, asset,
landscape, path, scatter, validate` — as NATIVE (wraps one UE feature; named by UE's
word), MACRO (orchestrates several; must not impersonate), or SENSE (read-only, plain
name). For each: what `unreal.*` surface it actually drives (read the code, R3), its
nearest native cousin in 5.8 (Foliage, PCG, Landscape, Splines, Modeling Tools, …), and
the verdict — keep name / rename / re-tag / wrap-native / delete.

Known audit questions going in (not prejudged):
- `scatter` → `foliage`? And if so, does the verb grow toward the native mode's semantics
  (paint/fill/erase per FoliageType) rather than our one-shot generate?
- `landscape` → `terrain`? (The strongest single misalignment: native name, non-native thing.)
- `path` — cousins are SplineComponent / Landscape Splines; ours carves + builds mesh.
  Macro; needs its R1 tag at minimum.
- `add` for Blueprint actors vs plain meshes — does the schema speak UE's actor/asset
  vocabulary correctly?
- `history` — ours is op-history + `undo_to`, UE's is the transaction/undo stack. Same
  concept? Tag the difference.

## Verification story (rough)

The bb standard: after renames, a fresh agent (no repo priors) given only the verb list
and schemas correctly predicts what each verb drives and reaches for the right verb from
a UE-phrased request ("paint some pines on the hillside" → `foliage`, not a hunt through
`scatter`). Schema-only test, no live editor needed — plus one live pass proving renamed
verbs still dispatch.

## Sequencing

Before SPEC-06..09 (they add verbs/ops — deixis reads, `validate` sweep scopes — that must
be born aligned). Renames are breaking changes to recipes/docs; do them while the surface
is young.
