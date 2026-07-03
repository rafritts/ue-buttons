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

### B10 — status block `last_action` goes stale across spatial verbs (shows a prior session's op)
Status: OPEN (found 2026-07-03, post-SPEC-05 L1 build.)

Repro: build L1 through the verbs in a fresh level. Through terrain create/shape/carve,
spline create/surface, and both foliage paints, the status block's `last_action` showed
`{'id': 'op003', 'verb': 'transform', 'summary': 'rotate cutover_cube'}` — an action from
the PREVIOUS session, on an actor that no longer exists. It only refreshed at the first
`add` (op004).

Root cause: `last_action` reads the transaction-history registry, and spatial verbs
(terrain/spline/foliage — deliberately not history-undoable) never mint an entry. So the
field silently reports the last HISTORY op, not the last ueb op.

Why it's a bug and not noise: the block's whole contract (SPEC-02, THE ONE RULE) is
"trust the block over your memory". A ground-truth surface that confidently reports a
stale foreign action is wrong output, not missing polish. Fix shape: track the last ueb
dispatch regardless of verb kind (annotate non-undoable ops as such), or suppress the
field when it doesn't describe the last call.
