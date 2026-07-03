# bugs.md — ue-buttons

Outright defects (wrong output, crash, corrupted state) found while building or driving
ue-buttons. Same discipline as `gaps.md`: a bug is **reproduced, fixed, and the fix
live-verified over the RC bridge**, and then **PRUNED from this file** — a completed bug is
deleted, not left behind with a FIXED banner. This file is the live worklist of what's
still broken; the reasoning behind a fix lives in git history and the code, not here. `B<n>`
numbers are never reused (grep git history for a retired one). Keep the repro and root cause
while a bug is open, not just "fixed".

Distinction from `gaps.md`: gaps are friction, missing capability, or design limits.
bugs are things that are *supposed to work and don't*.

Format: `### B<n> — <title>` · status · repro · root cause · fix · verification.

---

### B6 — `asset inventory measure=True` wedges the RC bridge for minutes; the timed-out call keeps running invisibly
Status: OPEN (found 2026-07-02 driving Level 1 rebuild through the MCP verbs)

Repro: fresh editor session (cold asset cache), `asset(action="inventory",
pack="GV_FreeShrubsPack", measure=True, budget=66)`. The MCP call timed out; every
subsequent call — including a plain `scene()` — returned "remote control unreachable
(timed out)" for **~13 minutes** while the editor loaded/measured the 66 Nanite meshes on
the game thread. When the bridge came back, the dims cache was fully warmed: the work had
completed server-side the whole time.

Two defects vs the documented contract ("bounded batches … never blocks the bridge"):
(1) the budget bounds the mesh *count*, not the wall-clock — one batch of first-load
Nanite meshes can hold the game thread far past any HTTP timeout, taking the whole verb
surface down with it (the default budget=60 is in the same danger zone); (2) a timed-out
call whose work keeps running is indistinguishable from a lost one — the agent can't tell
"retry" from "wait", and a blind retry would double-queue the load. Fix directions: chunk
the batch internally by wall-clock (e.g. stop after N seconds, return partial progress +
"call again"), and/or make the measure job async with a progress field on `inventory`.

Not measure-specific: `path carve` on a 22.5k-vertex terrain did the same (client timeout
→ bridge dark ~30 s → work landed anyway, verified by re-tracing the bed at grade). Any
long game-thread job outruns the HTTP timeout; the general fix is a job/progress pattern
(or per-verb wall-clock chunking) for every potentially-slow mutation.

### B3 — path drape traces the terrain before collision is ready → silent z=0.0, then `carve` bakes it into the mesh
Status: OPEN (found 2026-07-02 driving Level 1 dogfood; root cause characterized, not fixed)

Repro (Level 1, "Valley of trees"): `landscape create` → `landscape shape` (valley +
ridges + noise) → `path create` (route form) → `path carve` → `scatter`. The path's
returned waypoints came back with **`z=0.0` on 4 of 9 points** while the rest draped to real
terrain height (e.g. `[-3264,1311,418.9]`). The scatter that ran later reported
`no_ground: 0` — every one of ~11k candidates traced fine. So the *same* `trace_ground`
missed for the path and hit for the scatter, minutes apart, on the same terrain.

**Root cause REATTRIBUTED (2026-07-02, L1 rebuild):** the collision-cook-race theory is
wrong (or at most secondary). The default Open World template ("blank" level) ships with a
real engine **Landscape at z=0** (64 `LandscapeStreamingProxy` tiles, visible via
`scene(include_all=True)`). Every ground trace whose true terrain surface lies **below
z=0** hits that Landscape first and returns 0.0 — a *legitimate hit on the wrong ground*,
not a miss. Verified live: `landscape describe` on a fresh valley read z=0.0 exactly where
the model went negative, the 0.0 persisted across settle-and-retry (no cook race), and
after nudging the terrain +600 so all geometry clears z=0, every trace agreed with
model+offset and a 14-waypoint path draped with zero 0.0s. Explains all prior evidence,
including the \"self-consistent flat 0.0 re-trace\" (it was re-hitting the template
Landscape). Fix directions shift accordingly: traces should filter to (or prefer) the ueb
terrain / warn when the hit actor is engine scaffolding at exactly z=0; and the surface
should surface the stowaway Landscape's existence (see G22).

Original (superseded) root-cause theory: `path._drape` (path.py:129-130) does
`z = _ue.trace_ground(x,y); draped.append([x, y, z if z is not None else 0.0])`. Right
after `shape`, the DynamicMesh's **complex collision hasn't finished cooking**, so
`SceneTools._trace_world` returns `None` for the first waypoints — silently defaulted to
`0.0` instead of surfaced as a failure. Then `path carve` computes its flatten grade from
those stored waypoints, so it **flattened the southern bed to z=0** — baking the bad drape
into real geometry (a raised causeway ~800 cm above the natural −825 floor). Re-tracing the
floor afterward now *hits* z=0.0 there (a real flat surface), so the corruption is
self-consistent and invisible to a re-trace. Evidence: floor trace at x≤−6000 returns a flat
`0.0`; `landscape describe` (height function) still says −825..−269 there (see G15).

Two defects to fix: (1) `trace_ground` / `_drape` must distinguish "nothing beneath the
ray" from "collision not ready" — settle-and-retry after `shape`/`create` (poll the trace
until it stabilizes, or force a collision-cook wait), and `_drape` should *warn* on a miss,
never silently write 0.0. (2) `carve` should refuse (or warn) when a target waypoint z looks
like a miss sentinel rather than grading to it. Blender-buttons' drape has no cook race
(CPU mesh, immediate) — this is UE-specific (async physics cook).
