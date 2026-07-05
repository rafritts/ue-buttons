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

### B15 — hidden template ground keeps COLLISION: PCG grass floats at z=0 over terrain dips
Status: OPEN (found 2026-07-05, user report on UEB_PCGMeadow — "grass only rests on 0+ z")

Repro: terrain with noise dipping below z=0 → `pcg op=generate` → every instance over a
dip sits at EXACTLY z=0.0 (measured: 27/92 sampled instances float, all z=0.0 over
ground z=−25..−112). Root cause: G37's `set_template_hidden` only sets the two render
flags (`set_is_temporarily_hidden_in_editor` / `set_actor_hidden_in_game`); the engine
template Landscape's collision plane at z=0 survives. Our own `trace_ground` ignores it
by actor list, but PCG's surface sampler ray-casts at the physics level and can't be
handed an ignore list — it hits whichever surface is higher, so terrain below z=0 loses
to the ghost plane. Fix: `set_actor_enable_collision(False)` rides the hide (and True
rides the restore) — hidden means GONE, for renderer and physics alike.
