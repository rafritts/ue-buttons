# SPEC-09 — Runtime lint: PIE-based checks

Status: **DESIGN — fleshed out 2026-07-03; still GATED on SPEC-08 landing and being
dogfooded first.** The scope below is the best current shape, written down so the design
survives context loss — expect the dogfooding of SPEC-08 to reshape it. Do not implement
before the gate lifts.

## Problem

A class of defect is invisible statically and only exists while the game runs: the pawn
falls through the trail, wind displacement renders at 10x the authored intent, frame
time craters near a stand, an ensure fires on BeginPlay. The only honest check is a
scripted PIE session.

## Role in the family (sharpened by the G40 session)

Runtime lint is the fallback for rules with **no static tell** — where SPEC-07's
certificate can't be computed from asset × usage data alone (e.g. actual rendered WPO
magnitude; mask data the Python API can't read — mesh vertex-color presence is
unreadable in 5.8). Every rule lives at the cheapest tier that can catch it: static
certificate first, census second, PIE sampling last resort. SPEC-07's `tier="pie"`
rows are exactly this spec's work queue — and SPEC-08's sweep already names them as
"not checkable statically", so the demand signal is visible before anything is built.

## Verb shape

Rides `play` (SPEC-05: if UE owns a word, that verb owns it — this is Play):

```
play op=lint checks=[traverse, logs, budget] route=<spline-label> seconds=<n>
```

- The op owns the whole PIE lifecycle: start PIE, run the pass, capture, END play —
  standing B8 discipline (the agent owns starting AND ending PIE; mutations are refused
  while it runs, `play` itself is exempt).
- Returns the same findings format as SPEC-08 (numbered, severity, provenance,
  ready-to-fire `next`), so runtime findings and static findings read identically.

## The checks (build in this order, each gated on a dogfooded need)

1. **`traverse`** — walk a route end to end. Decision: **trace-walk simulation, not
   navmesh** — the dogfood levels build no nav data, and navmesh answers "can an AI
   path" not "does the ground hold". Mechanism: in the GAME world, step along the
   route's sampled centerline (the same live-trace sampling `spline op=describe`'s
   grade profile uses, G45) at capsule-stride intervals; at each step, capsule-sweep
   down from above head height. Verdicts: "walkable end to end" / "pawn falls through
   at [x,y] (fraction 0.32)" / "blocked at [x,y] (obstacle SM_Rock_03)". Grade
   steepness stays SPEC-07/G45 territory (static) — traverse checks the ground's
   SOLIDITY, not its slope.
2. **`logs`** — run PIE for `seconds` (default 10), capture the Output Log tail for the
   run window: ensures, errors, warnings, Blueprint compile failures, streaming
   failures. Cheap, certain to work, and catches the "ensure fires on BeginPlay" class
   the first `play op=census` already brushes against.
3. **`budget`** — frame-time sampling during the run vs. a declared budget (e.g.
   "16.6 ms"). Honest uncertainty: per-frame stat capture from editor Python is
   unproven. Candidate mechanism: `unreal.register_slate_post_tick_callback` (a real
   5.8 editor-Python API) accumulating delta-times into a buffer the dispatch reads
   after the run — this is also the candidate answer to "can we sample per-tick at all"
   (dispatch itself is game-thread and blocking, so sampling must be a registered
   callback, not a polling loop). If the callback path fails in the first experiment,
   `budget` is cut without mourning.
4. **Deferred until demanded: rendered-WPO sampling** — measuring *rendered* wind vs.
   authored intent. May be unreachable from editor Python; stays out of scope until a
   `tier="pie"` rule actually needs it and SPEC-08 dogfooding shows nothing cheaper
   catches the defect.

## The G30 collision (designed, not feared)

A fixed-duration PIE run plus capture WILL flirt with the HTTP dispatch timeout. Policy:

- v1 keeps every check inside a hard wall-clock budget (`seconds` capped at ~15) so a
  single dispatch survives.
- The moment a real check needs a longer run, **runtime lint becomes G30's concrete
  offender** — the async job + progress pattern gets built here (`play op=lint`
  returns a job handle; `play op=lint_status` polls), exactly the "wait for a concrete
  offender to shape it" outcome G30's deferral predicted. That decision is made then,
  with the offender's real shape in hand, not now.

## Verification plan

1. **traverse, broken trail:** in a scratch level, carve a trail, then destroy the
   collision on one strip section → `play op=lint checks=[traverse] route=trail`
   localizes the fall-through to that span (position + fraction); restore collision →
   "walkable end to end".
2. **traverse, blocked trail:** drop a boulder across the trail → blocked verdict names
   the obstacle actor.
3. **logs:** author a Blueprint/actor that ensures on BeginPlay in the scratch level →
   the ensure appears in findings with the run-window provenance; clean level → zero.
4. **budget (if the callback path works):** declared budget of 5 ms on L1's forest →
   over-budget finding with measured frame time; budget of 100 ms → clean.
5. **B8 discipline:** every verification run must end with PIE stopped and the editor
   world intact (`play op=census` equivalence before/after).

## Sequencing

Last of the diagnostic family (SPEC-06 → 07 → 08 → 09). The gate is deliberate:
dogfooding SPEC-08 tells us which defects static lint actually misses, and THAT list —
not this document — picks which check gets built first. Same reasoning that keeps G30
open.
