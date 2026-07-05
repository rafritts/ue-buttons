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

### B17 — terrain meta file is shared across levels keyed by label alone: same-label terrains clobber each other
Status: OPEN (found 2026-07-05 while diagnosing B16; PRE-EXISTING, predates pcg)

Repro: level A saves terrain meta under label "terrain"; level B creates its own
"terrain" → `_save_meta` merges by label into ONE shared Saved/ file, so B's features
overwrite A's. Reopen A: `_hydrate` adopts B's heightfield model for A's actor —
`terrain op=shape/flatten` would REBUILD A's terrain as B's landform, and z_model
diverges from traces. Every dogfood level uses the label "terrain", so every pair
collides. Fix direction: key the disk meta by (level package, label) with a one-time
migration of the flat file; the in-session registry stays label-keyed (it is per-level
by construction — reconcile GCs on transition).
