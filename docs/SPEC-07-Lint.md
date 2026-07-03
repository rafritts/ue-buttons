# SPEC-07 — Lint: whole-level sweeps

Status: **DRAFT / STUB** — deliberately rough. Shaped after SPEC-05/06 land; do not
implement from this document as-is.

## Problem

SPEC-06's probes are *targeted* — the user points, the agent checks. Lint is the
*unprompted* version: sweep the whole level, report every finding. It is also where
accumulated tells (G38 sparse-spire, G39 motion, floaters/sinkers) get a permanent home
instead of living scattered across verbs.

## Learnings folded in (2026-07-03, G41 — read before fleshing out)

- **Verb shape decided by the user:** no new `lint` verb — EXTEND `validate` with a sweep
  scope: `scope=selection | label | all`. Selection scoping is SPEC-05 deixis reused
  ("select the forest, say lint this").
- **The sweep is SPEC-06's rule engine at firing point 3** — same rule table, evaluated
  level-wide instead of against one referent. This spec owns the sweep loop, the findings
  format, and the native-linter wrapping; the rules themselves live in SPEC-06.
- **Native linters are a floor, not a roof** (both live-verified): stock Data Validation
  returns VALID on the G40 material (asset-scoped validators are structurally blind to
  context-mismatch defects); the only Map Check result on record is 0 errors / 0 warnings.
- **HAZARD (G41): never issue `MAP CHECK` as a console command over RC dispatch** — it
  crashed UE 5.8 with an access violation (crash dump on record). Use the
  `EditorValidatorSubsystem` API surface instead: `is_asset_valid` (wants `AssetData`),
  `is_object_valid`, `validate_assets_with_settings`, `validate_changelist(s)`,
  `add_validator`. There is no `validate_loaded_asset` in 5.8.

## Scope (rough)

1. **Wrap the engine's own linters** — don't reinvent:
   - Map Check (the editor's level linter; structured errors/warnings) — via a safe API
     path only, NOT console `MAP CHECK` over RC (G41 crash).
   - Data Validation subsystem — register our rules as Python `EditorValidatorBase`
     subclasses so they ALSO fire for humans on save/submit.
   - Output Log scraping: streaming failures, ensures, Blueprint compile errors.
2. **Asset sweep** — run SPEC-06's material/motion/collision checks across the level's
   whole asset inventory instead of one referent.
3. **Spatial sweep** — floaters/sinkers, interpenetration pairs, terrain seam
   discontinuities: generalize `validate` from "check this placement" to "audit the level."
4. **Findings format** — numbered, actor-labeled, severity-ranked, with provenance.
   Open decision: findings as a `lint` verb result only, vs. a persisted `lint.md`
   worklist under the gaps.md prune discipline.

Sister-repo ground truth: blender-buttons `extension/lint.py` and `extension/validation.py`
already do the compiler-style-verdict version of this; port the doctrine, translate the
conventions.

## Open questions

- Can Python `EditorValidatorBase` subclasses survive the runtime sync/hot-reload cycle?
- Sweep cost: a full-level material load can be slow — does lint inherit G30's
  timeout trap, and does it become the concrete offender that finally shapes the
  async-job pattern?
- False-positive budget: what's the noise threshold before the user stops trusting it?

## Verification story (rough)

Seed a scratch level with N known defects; lint must find N/N — and report ZERO findings
on the clean L1 rebuild.

## Sequencing

After SPEC-06 (lint is probes-at-scale plus engine-linter wrapping). SPEC-08 covers what
static lint can't see.
