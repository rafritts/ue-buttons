# SPEC-09 — Runtime lint: PIE-based checks

Status: **IN BUILD — gate lifted 2026-07-05; `logs` + `budget` implemented, `traverse` next.**
SPEC-08 landed and was dogfooded across four levels (L1/L2/Forest/PCG), so the gate condition
is met. `play op=lint` is live in `runtime/ue_buttons/lint.py` (two-call: static pre-scan +
Play, then read + end Play). The static compile-error pre-scan is LIVE-VERIFIED (it caught a
real compile-broken Blueprint and refused Play, proving the modal-deadlock guard); the frame
sampler, log-cursor, budget math and log-tail classification are each verified (live spike +
offline unit tests). The full in-PIE collect round-trip awaits a clean editor (a throwaway
compile-broken BP's session phantom was aborting PIE entry during the build). The original
design (2026-07-03) is preserved under `## The checks`; the buildable contract — reshaped by
two live spikes on 2026-07-05 — is in `## Design refresh` immediately below.

## Design refresh (2026-07-05) — buildable contract

Two spikes on the running editor settled the two unproven mechanisms and surfaced one
defect class the 2026-07-03 design did not anticipate.

**Verb + lifecycle — `play op=lint` is TWO-CALL, mirroring `play op=census`.** PIE spin-up
is asynchronous (the game world does not exist in the dispatch that requests Play), and —
decisively — per-frame sampling REQUIRES the game thread to tick freely between start and
read, which a single blocking dispatch cannot allow. So:
- **Call 1 (editor, not in PIE):** run the STATIC pre-scan (see below); if it finds a
  PIE-blocking defect, return findings and DO NOT start Play. Otherwise stash the requested
  `checks`/`route`/`seconds`/`budget_ms` in `_state.lint_run`, register the frame sampler
  (for `budget`), record the log-file byte offset (for `logs`), `editor_request_begin_play()`,
  return `{"lint": "sampling", "note": "PIE is running — call play op=lint again in ~<seconds>s"}`.
- **Call 2 (in PIE — `play` is B8-exempt):** read the sampler buffer + the log tail, run the
  `traverse` trace-walk in the game world, `editor_request_end_play()`, unregister the
  sampler, clear `_state.lint_run`, and return the SPEC-08 findings shape (numbered,
  severity, provenance, ready-to-fire `next`). The run window is the wall-clock gap between
  the two calls — `seconds` is guidance for how long the agent waits, not a blocking sleep.

**SPIKE 1 — `budget` sampler is PROVEN.** `unreal.register_slate_post_tick_callback(fn)`
fires `fn(delta_seconds)` on every slate tick and returns a `_DelegateHandle`;
`unreal.unregister_slate_post_tick_callback(handle)` stops it. A 4 s live run collected
21 076 real per-frame deltas (min 1.79 ms / mean 18.75 ms / max 125 ms). The callback ticks
during editor idle too, so the buffer MUST be reset at `begin_play` and read/cleared at
`end_play` to scope samples to the PIE window; store the buffer + handle in `_state` (never
reloaded). `budget` is IN — it survived its first experiment.

**SPIKE 2 — the compile-error modal (new, reshapes `logs`).** Requesting Play with a
Blueprint that has unresolved compiler errors throws a BLOCKING modal ("Blueprint Asset
Compilation Error … Play in Editor / Cancel"). A modal blocks the game thread, which is the
same thread RC dispatches run on — so it HANGS the bridge until a human clicks it, and the
two-call lint pattern would deadlock on call 2. Consequence: **compile errors must be caught
STATICALLY on call 1, before Play is ever requested** — never inside a PIE run. This becomes
the first thing `logs` does and the model for the check family: a runtime defect that can be
seen statically is caught statically; PIE is the last resort, never the first reach.

**Refreshed build order (each still gated on a dogfooded need):**
1. **`logs` (build first — cheapest, most certain).** Two parts. (a) STATIC pre-scan on
   call 1: enumerate Blueprints via the AssetRegistry, flag any with a compile-error/dirty
   status → finding with `next` = open/fix or delete; this also guards the bridge from the
   modal deadlock. (b) RUNTIME tail on call 2: capture `Saved/Logs/<Project>.log` from the
   byte offset recorded at `begin_play`, grep the run window for Error/Warning/Ensure/
   Blueprint-runtime failures. Log-file tail is chosen over an in-process log sink because
   it is certain to work and needs no engine-callback plumbing.
2. **`budget`** — sampler from SPIKE 1; compare mean/95th-percentile frame ms against a
   declared `budget_ms`; over-budget → finding with the measured distribution as provenance.
3. **`traverse`** — trace-walk a `route=<spline-label>` in the GAME world (capsule-sweep down
   at capsule-stride intervals along the live-sampled centerline, per G45). Biggest of the
   three; build after logs + budget prove the two-call harness end to end.

Unchanged from below: the G30 collision policy (hard `seconds` cap ~15 in v1; if a check
ever needs a longer run, THAT is G30's concrete offender and the async-job/`lint_status`
split gets built then), the findings-format equivalence with SPEC-08, and B8 discipline
(every run ends with Play stopped and the editor world intact).

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

## The checks (original 2026-07-03 detail — build order/mechanisms superseded by `## Design refresh`)

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
