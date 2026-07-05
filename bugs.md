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
to the ghost plane. Fix: hidden means GONE, for renderer and physics alike — and since Landscape
heightfield collision ignores every setter Python can reach (actor
set_actor_enable_collision, component NO_COLLISION, ECR_IGNORE — all probed live, all
no-op), the hide SINKS the proxies by an exact 2 km offset and the restore raises them
back; idempotent via a z threshold.

### B16 — template hide/sink is NOT reasserted on level open (user-visible white checkered plane)
Status: OPEN (found 2026-07-05, user report — "terrain clips through this white generic
checkered world surface floor material" after reopening UEB_PCGForest)

Repro: build on a ueb terrain (template hidden), `level op=open` another ueb level →
the engine template's white z=0 Landscape RENDERS again, terrain dips clip through it,
and (B15) its collision plane is back for PCG. Root cause: the editor-side hide is
per-session and `_transition_reconcile` counts on `terrainmod._hydrate()` to reassert
it — but `_hydrate` early-returns when `_state.terrains` is non-empty, and every ueb
level names its terrain "terrain", so the incoming level's same-labeled actor keeps the
registry entry alive across the transition and the reassert never runs. Fix: the
transition reasserts `set_template_hidden(True)` explicitly whenever terrains exist,
instead of hoping _hydrate falls through to it.

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
