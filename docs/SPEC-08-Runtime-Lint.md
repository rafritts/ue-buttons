# SPEC-08 — Runtime lint: PIE-based checks

Status: **DRAFT / STUB** — deliberately rough, and the least certain scope of the family.
Explicitly gated on SPEC-07 landing first; expected to be reshaped by whatever the static
linter turns out NOT to catch in practice. Do not implement from this document as-is.

## Problem

A class of defect is invisible statically and only exists while the game runs: the pawn
falls through the trail, wind displacement renders at 10x the authored intent, frame time
craters near the scatter, an ensure fires on BeginPlay. The only honest check is a
scripted PIE session.

## Scope (rough)

- **Scripted PIE run** — start PIE, run a scripted pass, record, end play (standing B8
  discipline: the agent owns starting AND ending PIE).
- **Traversability** — walk a `path` end to end via nav or trace-walk; verdicts like
  "walkable end to end" / "pawn falls through at [x,y]".
- **Log + stats capture during play** — ensures, warnings, frame-time/GPU stats vs. a
  budget, for a fixed-duration run.
- **Maybe: WPO displacement sampling over time** — the only way to measure *rendered*
  wind rather than authored wind. May be unreachable from editor Python; may not survive
  first contact.

## Open questions

- What can editor Python actually do WHILE PIE runs? (Dispatch happens on the game
  thread — can we sample per-tick at all, or only before/after?)
- Is traversability nav-mesh-based (needs nav data the dogfood levels don't build) or
  trace-walk-simulated?
- Does a scripted PIE run belong in a verb, or is it the concrete offender that finally
  builds G30's async job + progress pattern?

## Verification story (rough)

Deliberately break a trail (delete a carve section's collision), run the traversability
check, get the fall-through localized to the broken span; clean trail passes.

## Sequencing

Last of the diagnostic family (SPEC-05 → 06 → 07 → 08). Deliberately deferred until
dogfooding SPEC-07 shows what static lint misses — same reasoning that keeps G30 open.
