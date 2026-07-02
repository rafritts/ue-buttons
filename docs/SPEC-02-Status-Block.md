# SPEC-02 — The status block, REPL-style

Status: rough outline, 2026-07-02. Full spec after SPEC-01's E-milestones land.
Ground truth: blender-buttons' SPEC-16 ("the two forced senses") and `_core.py
_status()` — read both before implementing. Spatial lint is a *part* of this spec,
not the other way around.

## Why this is the spec that matters

In every review of blender-buttons ever run, the status block was the single most
praised element — above the placement DSL, above the verbs. The reason: it turns MCP's
call-and-response into a REPL. The agent acts, and in the same round-trip *sees* —
state, what changed, what's now broken. It never operates blind, never has to remember
to look, and can never mistake silence for success. That loop, not any individual
check, is what we're porting.

The root cause it solves (SPEC-16's diagnosis — port the reasoning, not just the
mechanism): **the model is a reactor, not an inspector.** It reacts brilliantly to
information put in front of it; it almost never elects to go *get* information it
wasn't handed — and the disposition that skips inspection is the same one that makes
it productive. So diligence cannot live in the model: any design that asks it to
*decide* to verify fails exactly when it's in flow. Perception and correctness must be
pushed into every response, forced.

Corollary that shapes the anatomy: the per-op block is a **single-object spotlight**
(the acted-on actor + scene globals). A relational defect — z-fight, penetration —
needs two objects and the relation between them, so it can *never* appear in the
spotlight; without a separate forced channel its absence reads as "all good" and
manufactures false confidence. That's why validate is its own sense, not more fields
on the block.

## Anatomy (blender-buttons' proven channel order, translated to UE)

Every mutating verb returns: result text → warnings → the two forced senses →
re-ground (periodic) → the status block. Read-only verbs (`feel`, `asset`, `view`)
carry no block — they ARE perception.

1. **Warnings channel** (ahead of the block so they're never lost):
   - *no-op warning* — a mutation that changed nothing can never masquerade as a
     successful edit.
   - *degraded-success warning* — the op worked but harmed something (UE analogues:
     spawn succeeded but overlaps everything; scatter placed 0 instances because rules
     excluded the whole region).
   - generic postcondition `notes` (auto mode-switches, fallbacks taken).
2. **Sense 1 — `feel` delta**: what you just changed, as perception, no verdict
   ("cabin_2 now rests-on terrain, flush-with pad edge").
3. **Sense 2 — `validate` line**: the always-on correctness floor, report-by-exception.
   This is where spatial lint lives (below). One line when clean; findings when not.
   **If the floor is disabled it must say so on every block** ("validate: OFF — floor
   is down") — silence-because-off must never read as silence-because-clean.
4. **Re-ground recap**: after enough churn, a compact scene recap + "re-read anything
   you haven't felt in a while before building on it." blender-buttons triggers on
   *weighted drift*, not raw mutation count (G117) — copy that.
5. **The block itself**: level (dirty/saved), acted_on vs viewport-active (bounds
   always describe the acted-on actor — blender-buttons G76), selected, dims (world
   AABB, rotation-aware, cm), bounds per axis, rot (yaw/pitch/roll), last_action
   {id, verb, summary}. Scatter groups render as one line ("1,847 instances,
   3 species"), never as rows.

Two conventions from around the block, kept:

- **Provenance**: every measurement any verb returns names its source ("↳ measured on
  cabin_2") — a number is never silent about what it was measured on. UE flavor: which
  actor/component, and whether simple or complex collision answered the trace.
- **Scope**: the floor runs after *geometry/placement* ops, not literally every op — a
  rename validates nothing. Declared intents are level-scoped (a "path↔terrain"
  blessing is a fact about this level, cleared on level load); only telemetry persists.

## The validate floor: spatial lint (UE edition)

Runs automatically on the touched delta after every mutation; whole-scene on demand.
UE makes this cheap — traces and penetration depth are native.

- **Ground relationship**: trace from actor base vs terrain — buried/floating, with
  delta AND fix ("base at z=0, terrain 5540 cm above → set z=5540"). Findings always
  carry the corrected value: the trace that found the problem knows the fix.
- **Penetration**: AABB fast pass → penetration depth ("penetrates rock_07 by 12 cm
  along −Y → nudge north 12 cm").
- **Z-fight**: coplanar-overlap heuristic (parallel overlapping faces within ~2 mm) —
  kit walls in the same plane, floors at exact terrain height, duplicate transforms.
- Scatter instances validate at generation time (the per-point trace already runs);
  sweeps sample rather than exhaust.

## Suppression discipline (port verbatim — this is load-bearing)

blender-buttons allows **no "ignore"**. The only way to quiet a finding is a positive,
justified declaration: `validate(op="expect", a=..., b=..., reason=...)` — the reason a
falsifiable design claim ("path gravel seats 3 cm into terrain by design"), optionally
depth-bounded (`max_depth`) so a blessed 3 cm clip can't hide an 11 cm one. Intent-free
defects — z-fights, duplicate transforms — are never suppressible at all. Contact
within the resting/flush epsilon (≲1 cm, consulting `feel`'s relations) is not a
finding in the first place.

## Sweep tier

`validate(op="run")` over the whole scene (or targets) — compiler-style verdict:
"PASS — 214 actors, no issues" or findings, one per line, each with its fix. Run
before screenshots and at milestones. Severity: errors + warns inline; notes
sweep-only. Silence discipline: clean = one line; no lint section that always prints.

## Non-goals

Aesthetic judgment (Ryan's), render-artifact detection beyond the coplanar heuristic,
physics-sim correctness, perf budgets. M1's status block already exists — this spec
upgrades it to the full two-senses form rather than inventing a new mechanism.
