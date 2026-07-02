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

### B3 — path drape traces the terrain before collision is ready → silent z=0.0, then `carve` bakes it into the mesh
Status: OPEN (found 2026-07-02 driving Level 1 dogfood; root cause characterized, not fixed)

Repro (Level 1, "Valley of trees"): `landscape create` → `landscape shape` (valley +
ridges + noise) → `path create` (route form) → `path carve` → `scatter`. The path's
returned waypoints came back with **`z=0.0` on 4 of 9 points** while the rest draped to real
terrain height (e.g. `[-3264,1311,418.9]`). The scatter that ran later reported
`no_ground: 0` — every one of ~11k candidates traced fine. So the *same* `trace_ground`
missed for the path and hit for the scatter, minutes apart, on the same terrain.

Root cause (two-stage): `path._drape` (path.py:129-130) does
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
