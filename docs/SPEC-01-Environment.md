# SPEC-01 — Environment surface: asset, landscape, path, scatter

Status: draft, 2026-07-02. Author: Fable session (design); implementer: Opus session.
Prereq reading: `README.md` (north star), `SPEC-00-Initial.md` (+ addendum),
`docs/M2-epic-toolset-evaluation.md` (adoption test + verdicts).

## Why this spec exists

Rung 1 of the north star is an environment: a forest in a mountainous valley, a winding
path through hamlets, a castle. The M1 surface can place and relate *actors*; it cannot
make terrain, place three thousand trees, or draw a road. Those are different domains
with different physics, and each needs its own projection into intent space.

**The exit test is one hamlet** (defined at the bottom). Everything in this spec is
scoped to what the hamlet needs. The full valley is repetition + density, not new verbs
— resist generalizing past the exit test.

Four new verbs (`asset`, `landscape`, `path`, `scatter`) plus one extension to `add`.
Total surface goes 7 → 11 verbs. That is a lot of new surface at once, so the milestone
ordering below is sequenced so each verb is proven live before the next starts.

## What's already decided (don't relitigate)

- **No `fab` verb.** Asset *acquisition* is a human step (Fab has no API, and curation
  is taste — Ryan's side of the partnership). The agent's job is noticing and measuring
  what arrived: that's `asset(action="whats_new")`, perception not acquisition.
- **Epic toolsets are backends, never surface** (see M2 eval). For this spec that means:
  `editor_toolset.toolsets.asset.AssetTools` and `static_mesh.StaticMeshTools` back the
  `asset` verb; `scene.trace_world` / `_snap_to_ground` back scatter's ground-conform
  logic. Import the modules in-runtime and call static methods — never via `:8000`.
- **Units are centimeters everywhere**, per SPEC-00 conventions. No mixed units in
  params or return dicts. Human-readable *summary strings* may render meters for values
  ≥ 1000 cm ("16.8 m") — numbers in dicts stay cm.
- **Marketplace meshes are placed at native scale by default.** Dims in inventories are
  *information for placement math*, not an invitation to resize. A cabin wall is 400 cm
  because its doorframe is human-sized; scaling it breaks texel density and grid fit.
  Explicit `scale=`/`dims=` overrides exist but warn in the status block.
- **PCG framework is deferred.** UE5's PCG is the "right" long-term scatter engine but
  is a large, graph-asset-shaped API. First bite is instanced-mesh scatter we fully
  control (below). Revisit PCG when the full valley's density demands it — that's a
  rung-1-scale problem, not a hamlet problem.

## The test palette (installed 2026-07-02, ~29 GB)

Verified present in `Content/` and readable via asset registry from the bridge:

| Pack | Root | What it contributes |
|---|---|---|
| Megaplant Library | `/Game/Megaplant_Library` | 16+ tree/shrub species, 381 static meshes (use SM variants, ignore the 322 skeletal) |
| GV Free Shrubs | `/Game/GV_FreeShrubsPack` | 66 undergrowth meshes |
| Rock Env Pack / Rock Collection 04 | `/Game/RockEnv_Pack`, `/Game/Rock_Collection_04` | ~148 rock/cliff meshes |
| Modular Rural Cabin | `/Game/Modular_Rural_Cabin` | 160 meshes: modular wall kit on a **4 m grid** (walls 400/800 × 20 × 300 cm, gable tops 470 cm), 32 prebuilt cabin Blueprints, ivy/detail meshes |
| KiteDemo | `/Game/KiteDemo` | terrain-grade landscape materials, 37 meshes |
| ParagonProps | `/Game/ParagonProps` | 478 stylized props (hamlet clutter; style clash accepted — test assets) |
| Fab (Megascans) | `/Game/Fab` | surface materials |

Style mismatch is explicitly fine — these assets exercise the machinery; the palette is
swappable later precisely because placement is relational, not baked coordinates.

---

## Verb 1: `asset` — perception over the project's content

The question this verb answers: **"what can I build with, and how big is it?"**
Epic's tools answer path-level queries; ours answers at build-planning altitude.

Actions (one `@mcp.tool`, action-dict style like the M1 verbs):

- `asset(action="packs")` — top-level `Content/` roots with asset counts by class and
  a one-line character ("381 static meshes, 16 tree species"). Cheap: registry only,
  no asset loads.
- `asset(action="inventory", pack=..., kind="mesh")` — the workhorse. Per static mesh:
  name, path, dims from bounds (cm), triangle count (LOD0), Nanite flag, material slot
  count. **Group by inferred family**: strip trailing `_01`/`_02`/size suffixes and
  cluster (`SM_Pine_Tree_01..05` → family `Pine_Tree`, 5 variants, height range
  590–1680 cm). Families are what an agent plans with; variants are what scatter
  randomizes over.
- `asset(action="describe", asset=...)` — one asset in full: dims, pivot location
  relative to bounds (see below), materials, collision presence, referencers/deps
  (Epic's `get_referencers`/`get_dependencies` — useful for "what does this cabin BP
  pull in").
- `asset(action="find", query=..., kind=...)` — name-substring + class filter across
  the project. Backed by Epic `find_assets`.
- `asset(action="whats_new")` — diff current registry roots/counts against a snapshot
  held in `_state` (persist the snapshot to a JSON sidecar in `Saved/` so it survives
  editor restarts). This is how "Ryan just downloaded something" becomes agent-visible.

Implementation notes for the backend:

- Registry-only where possible (`get_assets_by_path`, tags). Loading a mesh
  (`get_bounding_box`, triangle counts) is the expensive step — **cache measured dims
  in `_state` keyed by asset path**, invalidate on `whats_new` changes. First
  `inventory` of Megaplant will load ~381 meshes; that's acceptable once, not per call.
- **Pivot matters and must be reported.** Placement math needs to know whether a mesh's
  origin is at its base (trees, walls — usually) or centered (some props). Report as
  `pivot: "base"|"center"|"other"` derived from where origin sits in the local bounds
  z-range. Getting this wrong buries trees to their waist; it's the #1 predictable bug
  in this whole spec.
- Return shape is JSON-safe dicts (the dispatch protocol flattens everything anyway);
  keep per-asset dicts small and let `describe` carry the detail.

## Extension: `add` grows `asset=`

`add(asset="Pine_Tree_04", label=..., on=..., at=..., yaw=...)` — spawn a project
static mesh (or cabin Blueprint) by inventory name or full path, placed with the same
relational DSL as primitives. This is not optional garnish: **the hamlet's cabins are
composed wall-by-wall with exactly this.**

- Resolve short names through the `asset` inventory (families + variants); error with
  candidates listed on ambiguity ("Pine_Tree matches 5 variants — pick one or use
  scatter for random variants").
- Adopt the M2-eval verdict now: `primitive.py:40-50`'s bbox→scale math generalizes
  `add`'s dims logic to arbitrary meshes — but per the native-scale rule above, only
  apply it when the caller explicitly passes `dims=`.
- Blueprints spawn via their generated class; they come in as one actor (good — a
  prebuilt cabin is one thing to relate to).
- Placement uses measured bounds + pivot from the `asset` cache; `on=ground` should
  ground-snap via trace (adopt `scene.py _snap_to_ground` / `trace_world`).

## Verb 2: `landscape` — terrain as a heightfield

Terrain is not an actor with dims; it's a grid of heights. The projection that keeps
the agent in intent space: **the agent describes landforms; the runtime synthesizes the
heightmap.** The agent never hand-writes height arrays over the wire.

- `landscape(action="create", size=[x_cm, y_cm], base_height=...)` — new Landscape
  actor, flat, sized to the request (the hamlet needs roughly 200 m × 200 m;
  the valley later wants 2–4 km — size drives Landscape component/resolution choices,
  document the mapping in the docstring).
- `landscape(action="shape", features=[...])` — the interesting one. Features are
  declarative landform primitives, applied in order onto the height grid:
  `{"kind": "valley", "axis": "x", "floor_width": 8000, "wall_height": 6000, "roughness": 0.3}`,
  `{"kind": "hill"|"ridge"|"plateau"|"flatten", "at": [x,y], "radius": ..., "height": ...}`,
  plus `{"kind": "noise", "amplitude": ..., "scale": ...}` for natural variation.
  Runtime composes these into the heightmap (numpy is available in UE's Python — use
  it) and writes it to the landscape.
- `landscape(action="flatten", region=..., blend_margin=...)` — carve a building pad or
  path bed. `scatter` and hamlet assembly depend on this.
- `landscape(action="describe")` — bounds, height range, and height/slope sampled at
  arbitrary points (`at=[[x,y],...]`) so placement logic can ask "how high is the
  ground here" without tracing.

Implementation reality check (spike first — this is the highest-API-risk verb):

- The editor Python surface for Landscape is historically the weakest of the four.
  Candidates to evaluate in a spike, in order: (1) `unreal.LandscapeProxy` /
  `LandscapeSubsystem` edit-layer APIs in 5.8, (2) heightmap import via
  `LandscapeImportHelper`/automated import, (3) **fallback that definitely works**:
  generate a heightmap PNG on the server side, import as landscape via editor utility.
  Budget the spike before committing verb internals; file gaps for whatever's ugly.
- If all Landscape-actor paths prove unscriptable in 5.8, the escape hatch is a dense
  static-mesh terrain via Geometry Script — visually fine for the hamlet, wrong for
  the full valley (no foliage-on-landscape, no landscape material blending). Take the
  escape hatch only with a gap filed to revisit.
- Undo: heightmap edits may not sit cleanly in `ScopedEditorTransaction`. If they
  don't, say so honestly in the status block (`undoable: false`) rather than lying.
  History integrity is a feature; silent lies about it are worse than gaps.

## Verb 3: `path` — splines as first-class intent

A path IS a list of waypoints — the rare case where the natural UE primitive (spline)
and intent space already agree. Keep it that thin.

- `path(action="create", label=..., points=[[x,y],...], width=...)` — spawn an actor
  with a SplineComponent through the points (z resolved by ground-sampling each point
  against the landscape — the agent thinks in 2D map coordinates, the runtime drapes).
- `path(action="carve")` — flatten/smooth the landscape under the spline (delegates to
  `landscape` internals: flatten along the spline with blend margins) and assign the
  path its ground look. First slice: carving + a dirt material zone is enough; spline
  *meshes* (fences, cobbles) are a later action.
- `path(action="describe", label=...)` — length, point count, positions along it
  (`at_fraction=0.5` → world point + tangent). **This is the hamlet's skeleton**: "place
  cabin_2 left of the path at fraction 0.4, facing it" needs positions + tangents.
- Placement DSL grows two path-aware terms usable by `add`/`scatter`:
  `along=(path_label, fraction, side, offset_cm)` and `facing=path_label`.

### Map positions: polar first, grid second

Anywhere this spec accepts a 2D map position (`landscape` feature `at`, `path`
waypoints, `scatter` region centers), two forms are legal and resolve to the same
internal point:

- **Polar (preferred)**: `{"from": <anchor>, "bearing": <deg>, "distance": <cm>}` —
  anchor is a labeled actor, `("path_label", fraction)`, a named landscape feature, or
  `"center"` (map center). This is how humans give directions and surveyors lay out
  sites; it keeps the agent relating to things it already placed instead of inventing
  grid numbers.
- **Absolute**: `[x, y]` in map cm — legal, expected to be *read off* `view(map)`
  (below), not invented.

**Compass convention (decide once, bake into every docstring): north = +X (UE
forward), east = +Y, azimuth/bearing measured clockwise from north.** This makes
bearing numerically identical to UE yaw — one rotation vocabulary everywhere.

`path` additionally accepts a **route form** instead of a waypoint list: a start
position plus steps, each `{"bearing": deg, "distance": cm}` (absolute compass) or
`{"turn": ±deg, "distance": cm}` (relative to current heading — the natural encoding
of "winding": alternate gentle turns). The runtime walks the route, resolves every
waypoint, and returns all resolved positions so the agent knows exactly where the
chain ended up; `view(map)` is the visual confirm. Route headings double as the
tangent data `along=`/`facing=` placement uses.

### Map perception — the grounding for every [x,y] in this spec

`landscape` features and `path` waypoints take raw 2D map coordinates — the one place
this spec permits them, because terrain design is inherently cartographic and there is
no prior object to relate to when the landscape is the first thing in the level. But
the blender-buttons lesson stands: coordinates are only intent-space when the agent can
*read* them off something rather than invent them blind.

So `view` grows one action alongside this spec (build it in E3, before `path`):

- `view(action="map")` — top-down orthographic capture of the landscape extent with a
  **labeled coordinate grid** burned in (gridlines every 20 m at hamlet scale, axis
  labels in map cm), plus markers for existing labeled actors, paths (drawn through
  their waypoints), and scatter-region outlines. Optionally `overlay="height"` to
  shade elevation.

Workflow this enables: `view(map)` → agent reads the terrain like a site plan → picks
waypoints/feature centers *off the map* → `path(create)` → `view(map)` again to verify
the drawn path matches the read intent. Choosing `[x,y]` becomes reading, not guessing.
Implementation: capture from a top-down ortho camera (or sample the heightfield
directly and render server-side with PIL/matplotlib — server-side is likely easier to
label and has no async-screenshot dependency; G8 doesn't block it).

## Verb 4: `scatter` — populations, not actors

A forest is a population with rules, not 3,000 placement decisions. The agent declares
the rules; determinism makes it reproducible; clearances protect the intent already
placed.

- `scatter(action="create", label=..., meshes=["Pine_Tree", "Black_Alder:0.3"], region=...,
  density_per_100m2=..., seed=..., rules={...})`
  - `meshes`: inventory family names (variants randomized per-instance) with optional
    weights.
  - `region`: `{"kind": "circle"|"rect"|"polygon", ...}` or `{"kind": "landscape"}`
    (everywhere), minus automatic keep-outs.
  - `rules`: `min_spacing_cm`, `max_slope_deg`, `align_to_slope` (rocks yes, trees no),
    `scale_jitter` (e.g. 0.85–1.15), `yaw_random` (default true), `clear_of`:
    list of path labels / actor labels / regions with margins. **Default: every scatter
    automatically clears existing paths by path-width + margin and existing buildings
    by their bounds + margin.** The winding path through the trees is made by scatter
    respecting the path, not by deleting trees afterwards.
  - Generation: jittered-grid or Poisson-disk sampling (server- or runtime-side, either
    is fine; keep it numpy), then per-point ground trace for z + slope test (adopt
    `trace_world`).
- Instancing: one actor per scatter group holding one
  `HierarchicalInstancedStaticMeshComponent` per mesh variant; instances are transforms
  on those components. Fully scriptable, cheap to render, and the whole population is
  one labeled actor — `scatter(action="remove", label=...)` or editor-delete kills the
  forest stand as a unit. (This is why not per-tree actors: 3,000 actors would poison
  `scene` output and the undo stack.)
- `scatter(action="describe", label=...)` — instance counts per variant, region, seed,
  rules — enough to regenerate or reason about it.
- `scatter(action="regenerate", label=..., seed=...)` — same rules, new dice. The
  human's "hmm, reroll that stand" button.
- Auto-status: scatter groups report as `label (scatter: 1,847 instances, 3 species)`
  in `scene`/status output — never as thousands of rows.

## Milestones (sequenced; each live-verified before the next)

- **E1 — `asset`** (no dependencies; immediately useful). Exit: `packs` + `inventory`
  of Megaplant returns families with correct dims + pivots; `whats_new` detects a
  registry change; dims cache survives reload.
- **E2 — `add(asset=)`** (needs E1's inventory). Exit: compose one cabin from wall/
  gable pieces on the 4 m grid using relational placement only; spawn one prebuilt
  cabin Blueprint next to it; both ground-snapped.
- **E3 — `landscape`** (spike first, then verb). Exit: 200 m × 200 m landscape with a
  gentle valley profile + noise; `describe` height sampling agrees with trace results;
  `flatten` carves a clean building pad.
- **E4 — `path`** (needs E3). Exit: 5-waypoint winding path draped over terrain,
  carved, queryable at fractions.
- **E5 — `scatter`** (needs E3+E4 for ground + clearances). Exit: mixed-species stand
  (≥3 families, ≥500 instances) that respects the path and a building pad, reproducible
  from its seed.
- **E6 — the hamlet** (exit test, below).

Process: gaps.md discipline as always — friction → numbered gap → fix → live-verify →
clear. New-domain verbs will generate gaps fast; that's the system working.

## Exit test: the hamlet

On a fresh level, driven end-to-end through verbs (no raw Python ripcord except where a
filed gap documents why):

1. `landscape`: ~200 m × 200 m terrain — valley-edge feel: one side rising rocky,
   gentle floor, natural noise.
2. `path`: a winding path (≥5 waypoints, visible curvature) crossing the terrain,
   carved and dressed.
3. Buildings: 3–4 cabins along the path — at least one composed from modular pieces,
   the rest prebuilt Blueprint variants — placed relationally (`along=` the path,
   `facing=` it), on flattened pads, ground-snapped.
4. `scatter`: forest stand(s) of ≥3 species + undergrowth + rocks, clearing the path
   and cabins so the path reads as *going somewhere through trees*.
5. Verification both ways: mechanical — `feel` confirms cabin/path relations, scatter
   `describe` counts, no instance inside a clearance; visual — `view` screenshots from
   path level ("standing on the path looking toward the hamlet") and a high orbit.
6. `history`: teardown to empty level via `undo_to` (landscape caveats documented if
   they exist), then rebuild from the same calls — the rebuild must land within
   placement tolerance of the first build (determinism check: seeds + relational
   placement = reproducible hamlet).

Ryan judges the screenshots — "does this read as a place?" — and walks it in-editor
(PIE) for feel. The agent proves the numbers; the human judges the place.

## Risks / open questions

- **Landscape Python surface** (named above) — highest risk; spike before building.
- **Foliage vs HISM**: UE's InstancedFoliageActor gives editor-native foliage painting
  interop but a murkier API; HISM-per-group gives full control. Spec chooses HISM; if
  landscape material/foliage interactions demand real foliage actors later, migrate
  behind the verb (surface unchanged — that's the point of verbs).
- **Scatter scale**: hamlet-scale (hundreds–low thousands) is safe as one-shot
  synchronous calls. Valley-scale (hundreds of thousands, PCG territory) is explicitly
  out of scope; do not architect for it yet.
- **Skeletal-mesh plants** (Megaplant ships 322): ignore for scatter (HISM is
  static-mesh only); inventory marks them so nobody trips on it.
- **Undo depth**: a 2,000-instance scatter inside one transaction may be heavy; if the
  editor chokes, batch and report honestly in `history`.
