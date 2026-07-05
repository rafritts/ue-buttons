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

### B18 — template Landscape sink is editor-only; streams back at z=0 in PIE and floors the terrain

**Status:** OPEN (server). This level (UEB_ScenicWood) hand-fixed live; the tooling still ships the broken sink.

**Repro:** `terrain op=create` on an Open World level, sculpt any feature that dips below z=0
(a hollow/valley). Editor looks correct — the ueb terrain is the only ground, engine
Landscape hidden+sunk. Hit Play: a flat collision floor appears at z=0. Anything below z=0
(the whole hollow) is unreachable, and terrain that pokes above z=0 sticks up through the
flat plane as fake "mountains" on the horizon. Editor and PIE disagree completely.

**Root cause:** the engine template Landscape (1 parent + 64 `LandscapeStreamingProxy`) is
"defeated" by `_TEMPLATE_SINK_CM = 200000` + `set_is_temporarily_hidden_in_editor` in
`terrain.py` (self-healed every dispatch, `verbs.py:125`). That mutation is **editor-process
in-memory only, never committed to disk.** World Partition cold-loads proxies from disk on
Play, so they stream back at their authored transform (z=0) with collision ON. Worse:
`play op=census` (`verbs.py:451`) explicitly SWALLOWS this — proxies-present + ueb-terrain =
"known-benign, nothing missing." It checks only for *missing* actors, never that the proxies
*collide at z=0 and seal the terrain below*. The one check that should have caught it was
told to ignore it. (Cache-vs-disk write-through miss: hide written to editor cache, never to
the on-disk source of truth; Play does a cold read and gets the stale row.)

**Fix (to bake in):**
  1. Root fix — in `terrain op=create` / `level op=new`, DELETE the 65 Landscape actors and
     SAVE, instead of sink+hide. Proven to survive a PIE cold-load. Cost: `terrain op=remove`
     can no longer "restore" the engine ground (G37) — acceptable, we never want it.
  2. Affordance — stop suppressing in `play op=census`; trace the game world at terrain
     points, and if a ray hits a `LandscapeProxy` instead of the ueb terrain, emit a finding
     ("engine landscape is the PIE floor at z=0, sealing terrain below it") carrying the
     ready-to-fire delete+save recovery command. Protects levels built before fix 1.

**Recovery recipe (until fixed):** delete all `Landscape` + `LandscapeStreamingProxy` actors
via `EditorActorSubsystem.destroy_actor`, then `level op=save`. Verify with a game-world
multi-trace in PIE: rays must hit `terrain`, not `LandscapeStreamingProxy`.

### B19 — `terrain op=shape material=` silently no-ops when the material can't be loaded

**Status:** OPEN (server).

**Repro:** `terrain op=shape material=<X>` where `<X>` resolves to an asset that fails to
load (e.g. `/Game/Fab/MI_qlEtl` — present in the asset registry but `load_asset` returns
None; a broken/redirector/unknown-class asset). The op returns a normal `{"shaped": ...}`
success payload with no warning; the mesh keeps whatever material it already had. The agent
reports "applied" and the user sees zero change — reads as "the tool is broken / the two
materials look byte-identical." Cost us a full diagnostic detour to catch.

**Root cause:** the material resolve path treats an unloadable material as "no material
supplied" and leaves the existing slot untouched, instead of erroring. A loadable material
applies correctly (verified: WorldGridMaterial→MI_UEB_ForestFloor→MI_UEB_Grass all took), so
the failure is specific to load-failure being swallowed silently.

**Fix:** in the terrain material-resolve, if `material=` was explicitly passed but the asset
fails to load, RAISE (or emit a loud warning finding) naming the unresolved path — never
report `shaped` success as if it applied. HATEOAS: the finding should carry `asset op=find
kind=material query=<...>` so the agent can pick a real one.

**Aside (not a bug, already flagged by G57):** `MI_UEB_ForestFloor` renders as a mirror/water
sheen on a uniform-vertex terrain (its `MM_Vertex_Color_Blend` master treats unpainted
vertices as water); `MI_UEB_Grass` is BLEND_MASKED (pinhole risk). Neither is a dry opaque
forest floor — the project lacks a good one. Worth authoring `MI_UEB_ForestFloor_Dry` from a
Megascans `M_MS_Srf` master + the `T_qlEtl_4K_*` textures (logged as a want, not a bug).
