# gaps.md — ue-buttons

Every friction point the agent hits while driving UE becomes a numbered gap here.
Ported discipline from blender-buttons: a gap is **fixed and live-verified against the
running editor**, then **PRUNED from this file** — a completed gap is deleted, not left
behind with a FIXED banner. This file is the live worklist of what's still friction; the
reasoning behind a resolved gap lives in git history and the code, not here. "Verified"
means the fix was exercised over the RC bridge and the log/screenshot/`feel` confirms the
new behavior — not that it compiles. `G<n>` numbers are never reused (grep git history for
a retired one). Keep the reasoning while a gap is open, not just the diff.

Format: `### G<n> — <title>` · status line · what/why · resolution.

Gaps are *friction / missing-capability / design*. Outright defects go in `bugs.md`.

---

### G40 — motion verdicts ignore INSTANCING, and the status block has no level-wide motion census
Status: OPEN (found 2026-07-03 in the first SPEC-06 deixis experiment — the user selected
the forest and reported "whole trees float/rock, no bending"; design agreed, implementation
deliberately deferred until the spec-shaping session ends.)

The live case: `MM_Tree_Trunk` (Modular_Rural_Cabin pack) drives WPO with
`RotateAboutAxis` around the OBJECT PIVOT, angle scaled by `Distance(vertex, pivot) /
ObjectRadius`. Per-actor that's a legitimate base-anchored trunk bend. But 549 pines in the
level are FOLIAGE INSTANCES, and on an instanced component `ObjectPosition`/`ObjectRadius`/
local-origin resolve to the WHOLE COMPONENT's bounds — one pivot for the entire forest, a
radius spanning the valley — so every tree translates rigidly in sine arcs instead of
bending. G39's classifier calls this master `wpo` (correct but under-specific): the
verdict depends on material × USAGE, not the material alone.

The tell is fully mechanical, two static reads: (a) the WPO subgraph references
object-space expressions (`ObjectRadius`, `ObjectPosition`, `ObjectBounds`,
`TransformPosition` local→world) — walkable via `get_inputs_for_material_expression`;
(b) the mesh wearing it sits in an ISM/foliage component (even statically:
`used_with_instanced_static_meshes=True` on the master is the smoking gun without touching
the level).

Tool to build (the "would have highlighted it immediately" answer):
1. Upgrade the G39 classifier with a `pivot_wpo` kind (object-space WPO refs found) —
   fine as an actor, SEVERE when instanced.
2. A level-wide MOTION CENSUS on the status block: aggregate instanced meshes by motion
   kind, surface the bad combo as a forced warning, e.g.
   `⚠ motion: 549/4794 foliage instances FLOAT rigidly — MM_Tree_Trunk WPO is
   pivot-anchored and breaks under instancing (G40)`.
3. Same check fired at author time by `foliage op=paint`/`add` (extends the G39
   author-time announcement, which today would only say "MOVES", not "moves WRONG").

### G41 — native-linter wrapping hazards: `MAP CHECK` over RC crashes the editor; Data Validation is silent on real defects
Status: OPEN (recorded 2026-07-03 while testing whether stock UE tooling catches G40's
case; informs SPEC-08 before it's fleshed out.)

Facts, all live-verified today:
- `unreal.SystemLibrary.execute_console_command(None, "MAP CHECK")` issued through RC
  dispatch CRASHED UE 5.8 with `EXCEPTION_ACCESS_VIOLATION reading 0x28` (crash dump
  `UECC-Windows-8966F2934F0D67A9EFF48FA23F91A4E2_0000`; crashed session log ends at
  `Cmd: MAP CHECK`). Do NOT issue MAP CHECK over the bridge again; the earlier in-log
  MapCheck result reported `0 Error(s), 0 Warning(s)` anyway — no rule covers G40's case.
- `EditorValidatorSubsystem.is_object_valid(MM_Tree_Trunk, MANUAL)` → `VALID`: stock
  validators have nothing to say about a defective-under-instancing material. The
  subsystem API surface is `is_asset_valid / is_object_valid / validate_assets_with_settings /
  validate_changelist(s) / add_validator` — no `validate_loaded_asset` in 5.8, and
  `is_asset_valid` wants `AssetData`, not a loaded object.
Conclusion for SPEC-08: UE's native linters are a floor, not a roof — wrap them via the
validator-subsystem APIs (never console MAP CHECK through RC), and expect our own rules
(registered via `add_validator` as Python `EditorValidatorBase` subclasses) to carry the
real weight.

### G42 — `facing=<spline>` is degenerate for an actor standing ON that spline
Status: OPEN (found 2026-07-03, post-SPEC-05 L1 rebuild — placing the player_start
`along=` the trail with `facing="trail"`.)

`facing=<spline label>` means "turn to face the route" — perpendicular, toward the
nearest point. That's right for a cabin *beside* the trail, but for an actor placed ON
the spline it yields a sideways bearing (got 295.3° where the tangent was 25.3°) with no
warning, and nothing about the result says "you are ON the thing you're facing". The
recovery was a `spline op=describe at_fraction=` read + explicit `yaw=` — fine, but two
extra round trips for the single most natural trailhead intent ("start here, looking
down the path").

Fix shape: when the actor's position lies within the spline's width (it was just placed
`along=` it), `facing=<that spline>` should mean the TANGENT bearing at that fraction —
or at minimum warn and hand back the tangent as the ready-to-fire alternative
(HATEOAS: the finding carries the next legal move).

### G43 — spatial content is invisible to the actor-shaped perception surfaces (status block, outliner census, re-ground)
Status: OPEN (found 2026-07-03, post-SPEC-05 L1 retrospective — one root cause, three
symptoms.)

The level's content is population-shaped (a terrain, a spline, 17k foliage instances)
but every summary surface counts placed ACTORS:
- `outliner op=census` after the full L1 build: `count: 3` (PlayerStart + 2
  DynamicMeshActors). The 17,075-instance forest — the largest thing in the level by
  three orders of magnitude — doesn't appear (instances live in the untracked
  InstancedFoliageActor).
- The re-ground block fired mid-build saying `scene: 0 placed actor(s)` while a terrain,
  a 287 m trail, and two stands existed. An undercount that severe trains the agent to
  ignore re-ground blocks.
- The status block has no spatial roster at all — after the forest lands, nothing on any
  subsequent block says it exists.

Fix shape: one roster line sourced from the ueb registries, on the status block and in
the census, e.g. `terrains: valley · splines: trail 287m · stands: pine_forest 1916,
understory 15159`. Five numbers close all three symptoms at once. Re-ground should count
registries too, not just placed actors.

### G44 — the repeated `validate: OFF for this edit` paragraph is pure token weight
Status: OPEN (found 2026-07-03, post-SPEC-05 L1 retrospective.)

Every spatial-verb result carries the same three-line boilerplate ("the actor floor
checks placed actors (add/transform), not the terrain/population itself; `validate
op=run` to sweep…"), verbatim — six times in a nine-call build. The first occurrence
teaches; the rest are noise in exactly the surface (the forced senses) whose value is
signal density. Fix shape: compress to `validate: n/a (spatial)` after the first
occurrence per session, or always — the long form belongs in the verb description, which
already carries it.

### G45 — no grade/steepness instrument along a spline
Status: OPEN (found 2026-07-03, post-SPEC-05 L1 build.)

The trail drops 1885→1153 cm between waypoints and shipped with no read for whether
that's walkably steep — the agent can get z at waypoints (`spline op=describe`) and do
provenance-clean arithmetic, but grade-along-route is exactly the kind of derived number
the substrate should hand over (THE ONE RULE: the substrate does the arithmetic).
Playtest FEEL stays the human's; slope percent is a number and numbers are the agent's.
Fix shape: `spline op=describe` grows a grade profile — per-segment grade %, max grade +
where, e.g. `grade: avg 4.2%, max 14.8% at fraction 0.63` — and maybe a warning
threshold (hiking-trail reality: >15–20% reads as scrambling, not walking).

### G30 — no job/progress pattern for slow mutations: one pathological asset load can still outrun the HTTP timeout
Status: OPEN (successor to B6, 2026-07-02 — the two concrete offenders are fixed, the
general pattern isn't built. Reviewed 2026-07-03: deliberately deferred again — the
remaining wedge is a SINGLE atomic game-thread asset load, which even a tick-based job
can't chunk (the next dispatch would stall behind it on the game thread anyway); build
the async job + progress pattern when a new concrete offender appears to shape it,
not speculatively.)

B6's fixes hold: `terrain op=carve` batches its flatten features into ONE mesh rebuild (38-disc
carve round-trips in <0.5 s, was ~30 s dark), and `asset inventory measure=True` bounds each
batch by wall-clock (`seconds=`, default 20 s) as well as count. But the wall-clock check
runs BETWEEN mesh loads — a single cold Nanite mesh whose first load takes >60 s would still
wedge the bridge, and any future long game-thread verb inherits the same trap. The general
cure is an async job + progress pattern (kick the work off the dispatch path, poll a
`job_status`), or per-verb chunking as each new slow path appears. Until then: after any
timeout, poll `/remote/info` and RE-READ state before re-issuing — timed-out work usually
completed invisibly.
