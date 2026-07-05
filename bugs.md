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

### B11 — validate ground lint flags a PCG grove volume as "buried 5560cm"
Status: OPEN (found 2026-07-05, first pcg dogfood — UEB_PCGForest)

Repro: `pcg op=generate graph=mixed_sparse on=terrain label=forest` (two calls), then
`validate op=run` → `ground 1 new: forest buried 5560.6cm … raise base to z=-20.7`.
Root cause: the grove's PCGVolume is deliberately TALL (SPEC-10 invariant 1 — the
sampler needs Z headroom or it yields zero), so its base sits metres below grade BY
DESIGN; but `_ue.substrate_labels()` doesn't know pcg volumes, so validate's actor
floor sweeps it as a placed prop. Following the lint's own affordance (raise the base)
would MOVE a generated volume — which is SPEC-10 invariant 3's zero-instances failure.
Fix: substrate the grove — `_state.pcg_volumes` registry + `unreal.PCGVolume` class
tell (the durable half, same G47 lesson as DynamicMeshActor terrains).

### B12 — status roster renders a pending grove as "groves: forest None"
Status: OPEN (found 2026-07-05, same dogfood)

Repro: the status block after fire (call 1) reads `spatial: … groves: forest None`.
Root cause: `_generate` registers the pending grove with `instances: None`, and
`spatial_roster()` uses `v.get('instances', '?')` — the key EXISTS, so the `'?'`
default never fires and Python's `None` reaches the human line.
Fix: render a pending grove as `generating`, not `None`.
