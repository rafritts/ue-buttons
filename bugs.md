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

### B9 — `view action=map` can't find a ueb terrain the rest of the system sees
Status: OPEN (found 2026-07-03 building L1). Blocks map-based path planning — the map is
documented as THE legal source of absolute [x,y].

Repro (fresh `Untitled_1`, no prior state):
1. `landscape create size=[30000,30000] origin=[0,0] base_height=0 material=MI_UEB_Grass`
   → succeeds, actor `terrain` (DynamicMeshActor).
2. `landscape shape replace=True features=[valley, noise]` → succeeds, height range
   −827..13591 cm, status block prints terrain bounds.
3. `view action=map` → renders the "no terrain — create a landscape first" placeholder.
   Meanwhile, at the SAME moment: `scene` lists `DynamicMeshActor: ["terrain"]`;
   `landscape describe` traces the actual mesh (source "traced (actual mesh)"); the
   status block on every call prints `bounds of: terrain`.

So the map renderer's terrain lookup diverges from `scene`/`landscape`/status — they
resolve the terrain, the map path alone does not. Not a state-lifetime issue (single
fresh session, terrain created seconds earlier).

Root cause: UNKNOWN — the `view(map)` server-side render must key terrain differently
(class filter, tag, or a `_state` key the map reader checks but create/shape don't
populate) than `landscape describe`, which reads it fine. PRIME SUSPECT: the map worked
in the 2026-07-02 L1 build ("view(map) reads as a valley") but that was the SAVED
WorldPartition level `UEB_L1_Valley`; this build is the unsaved `Untitled_1`. The map
reader may resolve terrain via a persistent-level / WorldPartition query that returns
empty on an untitled, never-saved map, while `landscape describe` reads the in-memory
`_state`. If so, the fix is to make the map reader use the same `_state` terrain handle.

Impact / workaround: path planning that needs absolute [x,y] off the map is blocked;
the `path` route form (anchor + relative turn/distance steps) does NOT need the map, so
a winding path is still authorable. Fix + live-verify before relying on the map again.
