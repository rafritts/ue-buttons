# SPEC-07 — Lint: whole-level sweeps

Status: **DRAFT / STUB** — deliberately rough. Shaped after SPEC-05/06 land; do not
implement from this document as-is.

## Problem

SPEC-06's probes are *targeted* — the user points, the agent checks. Lint is the
*unprompted* version: sweep the whole level, report every finding. It is also where
accumulated tells (G38 sparse-spire, G39 motion, floaters/sinkers) get a permanent home
instead of living scattered across verbs.

## Scope (rough)

1. **Wrap the engine's own linters** — don't reinvent:
   - Map Check (the editor's level linter; structured errors/warnings).
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
