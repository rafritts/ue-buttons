# SPEC-15 — `build`: the Build menu (nav first), plus the walkability sense it unlocks

Status: **DESIGN — spike-proven 2026-07-05.** Audience: the agent implementing the verb.
Every engine claim below was probed live over the RC bridge on UE 5.8 (traces at bottom)
unless marked **SPIKE-CHECK**.

## Problem

UE's Build menu owns the derived-data passes: navigation, lighting, HLODs. None are
drivable today, and the first one gates real capability: **no navmesh means no AI
movement, no reachability sense, and SPEC-09's traverse has no engine-grade answer to
"can a pawn get from A to B"**. The verb is `build` (SPEC-05 reserved it for exactly
this menu).

## Decisions already made (do not relitigate)

- **v1 is `nav` only.** Lighting and HLOD ops are specified (the APIs are one call
  each, both probed present) but built when a dogfooded need appears: the dogfood
  levels are dynamic-lit (Lumen-era; `build_light_maps` bakes static lighting nobody
  is using), and HLOD matters at streaming scale we haven't hit. Do not build
  speculatively (charter).
- **`build` mutates; `feel` perceives.** `build op=nav` creates/sizes the bounds volume
  and rebuilds. The QUERIES it unlocks — "is B reachable from A, and how long is the
  path" — land as **`feel op=route`** (agent-only sense, SPEC-05 law: `feel` owns
  relational perception). This spec defines both because one subsystem backs them.
- **Nav generation is async across editor ticks** — the G30 fire/collect pattern, third
  confirmed instance (pcg generate, niagara activate, nav build). Fire returns
  `{"build": "building"}`; collect gates on `is_navigation_being_built() == False`
  **plus a non-degenerate coverage census** (the flag alone lies: the spike read False
  while one tile existed).
- **Coverage census = a projection grid**, numbers only: N×N `project_point_to_
  navigation` samples over the volume's XY extent → coverage fraction + hole
  coordinates. This is the navmesh's legible form, same philosophy as pcg's per-mesh
  census.
- Verb name `build`, `op=` discriminator.

## Verb contract

### MCP tool (`server/main.py`)

```python
@mcp.tool()
def build(op: Literal["nav", "describe", "clear", "lighting", "hlod"] = "describe",
          on: str = "terrain", label: str = None, quality: str = None) -> str:
    ...
    return render(call_ue("build", p, timeout=240))
```

### Ops

| op | params | effect |
|---|---|---|
| `nav` | `on=` (label whose AABB sizes the volume; default terrain), `label=?` (default `nav`) | ensure one ueb-tagged NavMeshBoundsVolume sized to `on=`'s AABB (+z headroom), fire `RebuildNavigation`, return pending stub; NEXT call with the same label collects: coverage grid census, RecastNavMesh presence |
| `describe` | `label=?` | building flag, volume coverage AABB, latest coverage census (re-sampled live), recast actor tile info |
| `clear` | `label=?` | destroy the bounds volume + the RecastNavMesh actor, unregister |
| `lighting` | `quality=` (preview/medium/high/production) | `LevelEditorSubsystem.build_light_maps(quality, with_reflection_captures=True)` — **DEFERRED**: wire when a baked-lighting need is dogfooded; blocking call, G30 wall-clock hazard, measure and record |
| `hlod` | — | `WorldPartitionHLODBlueprintLibrary.build_hlod_for_volume/actors` — **DEFERRED** until a streaming-scale level exists |

### `feel op=route` (the sense this unlocks — implement in `feel`'s module)

```
feel op=route from=<label|[x,y]> to=<label|[x,y]>
```

Resolve endpoints to positions (labels via the existing lookup; ground z via trace),
`project_point_to_navigation` each (generous z extent — the spike needed ±5000 to
catch terrain relief), then `find_path_to_location_synchronously`:

- both project + valid path → `{reachable: true, path_length_cm, straight_line_cm,
  detour_ratio, points: [...]}` (the spike measured 9,815 vs 8,485 straight — the
  detour ratio is the legible "how annoying is this walk" number).
- endpoint fails to project → `{reachable: false, reason: "no navmesh at <which end>"}`
  + the HATEOAS next: `build op=nav` (if no volume) or the hole's coordinates from the
  census (if built but holey).
- `path.is_partial()` → reachable false, with the furthest reached point.

If no ueb nav volume exists, `feel op=route` errors with `build op=nav on=<terrain>` as
the ready-to-fire next line — the sense TELLS the agent how to earn it (vision law).

### Errors (HATEOAS)

- `nav` with unknown `on=` → the standard label-lookup error.
- collect while `is_navigation_being_built()` → pending stub again, never a partial
  census recorded (the B-series lesson from pcg's collect gate).
- coverage census < 5% at collect → **warning finding**, not success: name the two
  known causes (relief steeper than the 44° agent slope; collision not nav-relevant)
  and carry `build op=describe` + the holes.

## Runtime implementation (`runtime/ue_buttons/build.py`, new module)

Registry (`_state.py`, hasattr-guarded): `nav_volumes = {}` — `{label: {on, actor_name,
coverage, census, pending}}`. Wire into `_VERBS` + SPATIAL; reconcile prunes;
rehydrate-on-open adopts ueb NavMeshBoundsVolumes (class tell + tag, the G61 pattern);
add both `NavMeshBoundsVolume` and `RecastNavMesh` to `_ue.substrate_labels()` class
tells (a nav volume is scaffolding, not scenery — keep it out of actor-floor lint, the
B11 lesson). `level op=clear`'s ueb sweep catches the volume; the auto-spawned
`RecastNavMesh-Default` is NOT ueb-tagged — clear must destroy it explicitly
(**SPIKE-CHECK**: whether destroying the last bounds volume already tears the recast
actor down on its own).

The proven call sequence:

```python
v = eas.spawn_actor_from_class(unreal.NavMeshBoundsVolume, center)   # spawns WITH a
v.set_actor_scale3d(extent_cm / 100.0)   # real 100cm brush cube — scale = half_ext/100
unreal.SystemLibrary.execute_console_command(world, "RebuildNavigation")
# … editor ticks between dispatches …
unreal.NavigationSystemV1.is_navigation_being_built(world)           # collect gate 1
unreal.NavigationSystemV1.project_point_to_navigation(               # collect gate 2:
    world, pt, None, None, unreal.Vector(200, 200, 5000))            #   coverage grid
```

Volume sizing: XY from `on=`'s AABB; Z spans the AABB ±2000 cm headroom (nav needs to
see the ground, not the sky — but relief must be inside the volume). The spike's
50×50×20 scale (100×100×40 m) over the PCGForest terrain produced full coverage.

**The one-rebuild trap (shapes the fire/collect contract):** the first
`RebuildNavigation` left ONE 988 cm tile at the origin (coverage 1/25) with
`is_navigation_being_built()` already False; a second fire after ticks elapsed reached
25/25. Whether the cure was the second command or just elapsed ticks is unresolved —
**SPIKE-CHECK at build time**: if collect finds the flag False but coverage degenerate,
re-fire ONCE before reporting the warning (bounded self-heal, mirror the B16 style),
and record which cure worked in this spec when known.

RecastNavMesh actor: auto-spawns on the tick after the volume lands (0 actors in the
spawn dispatch, 1 on the next — do not spawn it yourself).

Path/projection signatures (both bitten live): `project_point_to_navigation(world,
point, nav_data=None, filter_class=None, query_extent=Vector)` — the extent is
POSITIONAL and its default (0,0,0) makes every query miss on relief; always pass a tall
extent. `find_path_to_location_synchronously(world, start, end)` returns a
`NavigationPath` (`is_valid`, `is_partial`, `path_points`); `get_path_length` returns
`(NavigationQueryResult, float_cm)` — unpack, don't print.

New-module reload gotcha applies.

## Invariants

1. **Fire and collect are separate dispatches**; collect gates on the building flag AND
   a sane census. A False flag with degenerate coverage is "still building or wedged",
   never success.
2. **Every route/coverage number carries provenance**: census points are the grid you
   sampled this dispatch, not a remembered one (ground truth is perishable).
3. Projection queries always pass an explicit tall `query_extent`.
4. The RecastNavMesh actor is engine-owned: never labeled, never moved; destroyed only
   by `clear`.
5. Coverage below threshold is a warning finding with causes and next moves — never
   silent (pcg invariant 5, inherited).

## Verification plan (live, over the MCP tools, before commit)

1. `build op=nav on=terrain` on a dogfood level → pending stub; volume ueb-tagged,
   sized to the terrain AABB (compare numerically).
2. Second call → coverage census ≥ threshold (record the fraction), RecastNavMesh
   present, registry updated, `pending: false`.
3. `feel op=route` between two labeled actors → reachable, path_length ≥ straight_line,
   detour_ratio recorded. Route to a point on a cliff wall → reachable false with the
   projection failure named.
4. `feel op=route` with NO nav built (fresh level) → error carrying `build op=nav`.
5. `build op=clear` → both actors gone, registry pruned, `feel op=route` errors again.
6. Save/reopen → volume rehydrates (the RecastNavMesh persists in the level —
   **SPIKE-CHECK** its state after reopen: stale navmesh must be detected via a census
   re-sample, not trusted).
7. Validate lint stays clean with a nav volume present (substrate exclusion holds).
8. Dogfood on the L1 valley (steep walls should produce honest holes at the treeline)
   → findings to gaps/bugs.

## Ground truth — spike traces (2026-07-05, RC bridge, UE 5.8, on /Game/Maps/UEB_PCGForest)

1. Classes: NavigationSystemV1, RecastNavMesh, NavMeshBoundsVolume, NavigationPath,
   WorldPartitionBlueprintLibrary, HLODLayer present; `EditorBuildUtils`,
   `LightingBuildOptions` absent. `LevelEditorSubsystem.build_light_maps(quality,
   with_reflection_captures)` is the only lighting entry point.
2. NavigationSystemV1 statics: find_path_to_actor/location_synchronously,
   get_path_cost/length, get_random_(reachable_)point_in_navigable_radius,
   is_navigation_being_built(_or_locked), navigation_raycast,
   project_point_to_navigation, register_navigation_invoker, on_navigation_bounds_updated.
3. `spawn_actor_from_class(NavMeshBoundsVolume)` → REAL brush (100 cm cube), scaled
   (50,50,20) → measured bounds 5000×5000×2000 cm. RecastNavMesh: 0 in the spawn
   dispatch, `RecastNavMesh-Default` present on the next.
4. First `RebuildNavigation`: `is_navigation_being_built()` False immediately; recast
   bounds 988×988×0 cm at origin z=-20; coverage grid (5×5 over ±4000, extent 200/200/
   5000) = **1/25**. Terrain (`DynamicMeshComponent`) `can_ever_affect_navigation` was
   already True. Second `RebuildNavigation` + elapsed ticks → **25/25**.
5. Path proof: endpoints (±3000,±3000) projected (extent ±5000 z); path valid,
   non-partial, 4 points, length **9,815 cm** vs 8,485 straight-line (routes around
   relief/trees). `navigation_raycast(w, a, b)` → None (unblocked on-mesh line).
   Un-projected endpoints (default extent) → `find_path` returns invalid/0-point path,
   and raw (x,y,300) points don't project at all: the tall-extent rule.
6. HLOD: `WorldPartitionHLODBlueprintLibrary.build_hlod_for_actors/for_volume` exist.
7. Cleanup: volume + recast actor destroyed cleanly.
