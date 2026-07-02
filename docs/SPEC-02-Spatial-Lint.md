# SPEC-02 — Spatial lint: deterministic validation, REPL-style

Status: rough outline, 2026-07-02. Full spec after SPEC-01's E-milestones land.

## Why

Derived coordinates can still be wrong — stale anchor, pivot surprise, terrain edited
after placement. Derivation (SPEC-01) keeps the agent from *inventing* bad numbers;
this spec catches derived-but-wrong ones deterministically. UE is a physics engine
wearing an editor as a hat: traces, overlap tests, and penetration depth are native,
cheap, and exact. The model is never the load-bearing spatial reasoner — perception
before the action, arithmetic during it, **verification after it**.

## The direction: REPL-style status (the critical part)

blender-buttons' insight, extended: every mutation already returns a status block; lint
findings ride *in* that block, so the agent gets act → see → correct in one round-trip,
like a REPL echoing errors. Never a separate "now validate" step the agent must
remember — validation is ambient.

```
── ue status ───────────────────────────────
  level:      Hamlet (dirty)
  active:     cabin_2  dims: [800, 400, 470] cm
  last_action: {id: 14, verb: add, summary: "cabin_2 along path_main@0.4"}
  ⚠ lint:
    cabin_2 base at z=0 but terrain is 5540 cm above → set z=5540
    cabin_2 penetrates rock_07 by 12 cm along -Y → nudge north 12 cm
────────────────────────────────────────────
```

Findings always carry the corrected value, not just the complaint — the trace that
found the problem knows the fix.

## Two tiers

- **Inline (ambient)** — runs on every mutation, scoped to the actors just touched:
  ground-relationship trace (buried/floating vs terrain, with delta), AABB overlap fast
  pass against neighbors, penetration depth on hits. A few traces per mutation; near-free.
- **Sweep (`check` verb)** — whole-scene pass on demand (before screenshots, at
  milestones): all actors, sampled scatter instances, plus the heavier heuristics —
  z-fighting (overlapping bounds with parallel faces within ~2 mm), duplicate
  transforms, floating clutter.

## Judgment calls to settle in the full spec

- **Intent epsilon**: resting/flush contact is penetration ≈ 0 *by design*. Contact
  ≲ 1 cm is presumed intended (consult `feel`'s rests-on/flush relations); beyond it,
  a defect. Threshold configurable, defaulted sanely.
- **Severity**: error (buried in terrain) vs warn (2 cm clip) vs note (kissing bounds).
  Only errors/warns appear inline; notes reserved for the sweep.
- **Scatter**: instances are validated at generation time (ground trace already runs
  per-point); sweeps sample rather than exhaust.
- **Silence discipline**: no findings → no lint section at all. The block must stay
  scannable; a lint section that always prints something trains the agent to skip it.

## Non-goals

Visual/aesthetic judgment (that's Ryan's), render-time artifact detection beyond the
coplanar heuristic, physics simulation correctness, performance budgets.
