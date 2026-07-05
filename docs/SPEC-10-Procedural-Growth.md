# SPEC-10 — pcg: wrapping UE's PCG framework as an intent verb

(Filename keeps the original "Procedural-Growth" slug; the verb and scope are `pcg`,
generic placement — see Scope.)

Status: **DESIGN** (2026-07-05). Grounded by two live spikes — every capability claim
below was exercised over the RC bridge, and the numbers are real (spike traces at the
bottom). **Both forks are now decided** (2026-07-05): verb = **`pcg`** (a standalone UE
system earns its own verb — revised same day from `foliage op=grow`, see Verb shape);
graphs = a code-authored palette (node-value tuning over Python is proven — no node
editor, no reliance on exposed user parameters).

## Problem

We hand-roll forest scatter — `foliage op=paint` over an InstancedFoliageActor, with the
agent computing density from spacing (`density ∝ 1/spacing²`, `4× = halve min_spacing`).
It works, but it is the exact coordinate-fiddling the project exists to escape, one
abstraction up: the agent reasons about spacing numbers instead of saying "grow a forest
here." UE5 already solves this declaratively with the **PCG framework** (node graph:
sample a surface → filter by density/slope/noise → spawn instances), and the forest graph
ships **with the engine**. The question this spec answers: how do we expose PCG as an
intent verb that stays inside our laws — legible, numbers-only perception; relational, not
coordinate, authoring; reversible; and driven entirely over Remote Control.

## What the spike proved (ground truth, 2026-07-05)

Driving PCG purely from editor Python over RC, in throwaway level `/Game/Maps/UEB_PCGSpike`
(30000 cm flat ueb terrain):

- **Firing a graph is fully reachable.** `spawn PCGVolume → scale to cover the surface →
  vol.pcg_component.set_graph(load_asset(graph)) → comp.generate(True)`. No GUI, no
  `PCGSubsystem` (absent in 5.8 Python — drive the component directly).
- **The forest graph is stock.** The PCG plugin ships 56 graph templates, incl.
  `/PCG/GraphTemplates/TPL_Showcase_SimpleForest`, `…HierarchicalGenerationForest`,
  `…RuntimeGrassGPU`, plus richer sample content under `/PCG/SampleContent/SimpleForest/…`
  and the ProceduralVegetation plugin's `SeedPointScatter`. Epic authored the graph; the
  "a human wires the node graph once" cost is already paid.
- **One call produced 332,941 instances** across 5 ISM components: ~1,329 mature trees
  (`PCG_Tree_01/02/03`) + 200 boulders + 331k seedling undergrowth — ~3× our whole
  hand-built forest, with zero density math on our side.
- **It sampled OUR terrain.** The graph read the ueb StaticMesh terrain's collision
  directly (all instances on-surface, z=0). **No Landscape required** — this matters,
  because Python can't author a Landscape in 5.8 ([[ue58-python-api-constraints]]) and our
  terrain is a DynamicMesh. PCG scattered on it anyway.
- **Self-contained meshes.** The graph spawns its own `PCG_*` content — NONE of the
  bare-branch procedural-vegetation trap that R3/G56 guards against.
- **Reversible.** `comp.cleanup(True)` emptied it cleanly. The component also exposes
  `regenerate_in_editor`, `dirty_generated`, `get_generated_graph_output`,
  `override_generation_radii`.

## How the palette gets tuned — DECIDED (node-value tuning over Python)

Firing a stock graph is trivial; the open question was **how a tuned variant gets
authored without the user living in the PCG node editor** (they don't know UE, and
node-graph work is exactly the editor-fighting this project exists to avoid). Spike #2
answered it: **graph node settings are readable AND writable over RC**, and the change
propagates through generation. So the palette is authored entirely in code:

```
duplicate a stock graph → /Game/UEB_PCG/<name>   (EditorAssetLibrary.duplicate_asset)
walk graph.nodes → node.get_settings()           (typed PCGSettings subobjects)
set_editor_property on the density/mesh/prune knobs
save the /Game copy                               → this IS a palette entry
```

Proven end to end (spike #2): cutting `points_per_squared_meter` 8× on the three
`PCGSurfaceSamplerSettings` nodes of a duplicated SimpleForest dropped the generated count
**332,941 → 44,502** (seedlings 331k → 44k) — the authored value propagated exactly. The
tunable surface per node type: `PCGSurfaceSamplerSettings` (density: `points_per_squared_meter`,
`point_extents`, `point_steepness`, `looseness`, `seed`), `PCGStaticMeshSpawnerSettings`
(which meshes spawn), `PCGSelfPruningSettings` (spacing/overlap), `PCGTransformPointsSettings`
(scale/rotation jitter).

Consequence: **we do NOT need graphs to expose user parameters** (the stock showcase
graphs don't — `SimpleForest.user_parameters` is an empty `InstancedPropertyBag`, and there
is no `get/set_graph_parameter` on `PCGGraphInstance` in 5.8). We bypass the parameter
system and edit node settings directly on our own `/Game` copies. The `call_method` route
to C++ `GetGraphParameter` remains a theoretical fallback for a param-exposing third-party
graph, but nothing needs it.

**Swapping the meshes (proven 2026-07-05).** Density is one axis; *which assets* grow is
the other, and it's the same node-editing move. Each `PCGStaticMeshSpawnerSettings` node
holds `mesh_selector_parameters` (a `PCGMeshSelectorWeighted`) whose `mesh_entries` is an
array of `PCGMeshSelectorWeightedEntry` — each a `{descriptor.static_mesh, weight}`. Rebuild
that array in code and the spawner grows whatever you point it at. Verified end to end:
swapped the showcase `PCG_Tree_*` for `SM_Pine_Tree_01..05` (weighted) → 601 pines; and
built three side-by-side plots on one terrain from three duplicated graphs — **pine**
(`SM_Pine_Tree_*`, 6–17 m conifers), **scrub** (`GV_Vol7_Shrub_*_full`, 2–6.5 m), **fantasy**
(`SM_FlowerTree_*`) — all draping the relief (saved: `/Game/Maps/UEB_ForestVariants`).

**Palette entry = a tuning function** (duplicate stock graph → set sampler densities + swap
spawner mesh_entries → save `/Game/UEB_PCG/<graph>`), checked into the runtime the way
FoliageType minting is. Adding `pine_dense` / `mixed_sparse` / `flower_grove` is writing one,
not opening an editor. The agent's day-one intent knobs: **which palette entry** (`graph=`),
**which surface / area** (`on=` → volume bounds, proven to drive sampling extent), and
**seed** (per-node `seed`, for reroll-without-restructure).

**Mesh vetting is a hard gate on palette entries (found 2026-07-05).** A mesh only earns a
palette slot after two checks, both cheap over RC: (1) **size** — `mesh.get_bounds()` height,
so a 0.6 m "Decoration" sprig never gets scattered as a canopy tree; (2) **bare-render / G56**
— walk the mesh's material masters, reject any under a runtime-dependent plugin
(`MA_Foliage_Trees` etc., the R3 rule). Dogfooding proved the need: `Megaplant_Library`
`Decoration_*` meshes are 0.6 m AND wear `MA_Foliage_Trees` (would render bare) — auto-rejected;
`UEB_Trees` hornbeam/spruce/birch are the same trap. And **motion**: a `pivot_wpo` palette
mesh (e.g. `SM_FlowerTree_*`) rigid-floats when instanced (G40), so the grow must set
`world_position_offset_disable_distance=1` on its spawned ISM components post-generate — done
for the fantasy plot, the same cure as G58. `wpo` (plain wind, e.g. the pines/shrubs) is left
to sway.

## Scope — PCG is generic placement, not a foliage feature

A huge share of world content will flow through this verb, so the spec must not bake in
its first use case. PCG is a **point-dataflow placement/assembly system**: sample points
(from a surface, spline, texture, volume, or other actors) → filter/transform (slope,
noise, density, distance-to, self-prune) → spawn assets at the survivors — mesh
instances, **actors, Blueprints, spline meshes**. The verb wraps *that*; vegetation is
the first palette class, not the boundary. What the same surface covers:

- **Forests / scatter** — stock graphs, spike-proven.
- **Dressing** — debris in a canyon, props in a cabin, stalagmites in a carved cave: the
  same sample→spawn shape with a different palette (the surface sampler reads any
  collision, including cave interiors).
- **Kit assembly (cities, ruins, fences)** — PCG assembles modular kits along grids and
  splines (Epic's Electric Dreams pattern). Needs an authored graph + a modular asset
  kit; **no stock city graph ships** — see "the graph is the ceiling."
- **Rock formations / spires** — as placed+scaled+stacked rock meshes, trivially (a
  palette with large scale ranges).
- **What `pcg` is NOT: a sculptor.** Carving caves, raising cliffs, novel geometry —
  geometry-script territory, owned by `terrain`. Road/river *networks* are authored by
  `spline`; `pcg` *consumes* splines as inputs (spawn-along-spline, clear-near-spline via
  difference nodes). Division of labor: **terrain carves, spline routes, pcg populates.**

**The graph is the ceiling.** Our proven authoring surface is duplicate-a-stock-graph +
tune node values (densities, mesh entries, prune spacing). Stock templates cover
vegetation/grass/rocks; there is nothing city-shaped to duplicate. OPEN SPIKE: can
editor Python author a graph **from scratch** (add nodes, wire edges)? If yes, the agent
can grow arbitrary generators in code; if no, new palette classes come from duplicating
the nearest stock/marketplace graph. Either way the verb shape below is unchanged — only
the palette registry grows.

**Graphs are visible, ordinary assets.** Palette entries live at `/Game/UEB_PCG/<name>`
as normal PCG graph assets — the user can double-click one in the Content Browser and
UE's node editor opens it like any hand-made graph. Code-authored means *we* never open
that editor, not that the artifacts are hidden.

**Backend.** Nothing PCG-specific in the transport and no UE-side MCP exists: the same
RC bridge → editor Python → `PCGComponent` API (`set_graph` / `generate` / `cleanup`)
that every other verb rides.

## Verb shape — DECIDED: mint `pcg`

Decided (2026-07-05, revising the same-day `foliage op=grow` call): **`pcg` is its own
verb.** The user's tiebreak is predictability — nothing about `foliage op=grow` suggests
PCG, while a verb named `pcg` is totally unambiguous. And it is the *stronger* reading of
the SPEC-05 law: verbs are named for the UE surface they drive, and PCG is a named,
standalone UE system (its own plugin, editor mode, and asset type) — not a feature of the
foliage mode. The seam is clean: `foliage` = InstancedFoliageActor painting, `pcg` =
graph-driven generation. Op names mirror the PCG component's own API (`generate()` /
`cleanup()`) for the same predictability reason:

```
pcg op=generate  graph=<palette name>  on=<terrain/surface label>  [region=…]  [seed=n]
pcg op=regenerate  label=<grove>       # re-run generate() after a surface/param change
pcg op=cleanup   label=<grove>         # cleanup(True) + destroy the volume — full reversal
```

- `graph=` resolves against the code-authored palette (small runtime registry, intent
  name → `/Game/UEB_PCG/<graph>`, each a stock graph duplicated + tuned in code, vetted
  the way FoliageType minting is).
- `on=` is relational, not coordinate: the named surface's AABB sizes and positions the
  PCGVolume (bounds proven to drive sampling extent). `region=` optionally clips to a
  circle/rect the way `foliage op=paint` already does.
- The result is a labelled, ueb-tagged PCGVolume actor — it joins the outliner registry
  and reconcile like any other ueb actor, so `op=cleanup` and level lifecycle
  (`level op=clear`) already know how to tear it down.

(The earlier `foliage op=grow` shape was weighed and reversed — "don't split plants
across verbs" lost to "a standalone UE system gets an unambiguous verb of its own.")

## Perception — census, numbers only

Policy holds: no screenshot, the agent perceives the result as numbers. After a generate,
walk the volume's managed ISM components and count per `static_mesh` — proven in the spike
(5 components, exact per-mesh counts). The verb returns a **per-mesh census** (per-species,
when the palette is a forest) and the volume's world-AABB coverage:

```
grew grove_north (graph=mixed_sparse, on=terrain):
  1329 trees  (PCG_Tree_01 ×425, _02 ×489, _03 ×415)
   200 boulders (PCG_Boulder_02)
  331412 seedlings (PCG_Seedling_01)     ← untuned showcase density; see note
  coverage: x[-15000,15000] y[-15000,15000], on terrain surface
  → pcg op=cleanup label=grove_north         # ready to fire
```

Every generate carries the HATEOAS `next` (regenerate / cleanup), per the vision law. The seedling
flood is the honest showcase output and precisely the argument for the curated palette
(A): a tuned `mixed_sparse` graph would author a sane seedling count once, so the agent
never sees 331k.

## Hazards / gaps to carry into build

- **G30 (the async trap).** A 333k-instance generate is a heavy game-thread op; a larger
  surface could outrun the HTTP timeout. `generate(force)` may run async (the spike read
  results a beat later), so the verb likely needs the poll-and-reread pattern G30 has been
  waiting for a concrete offender to shape — this may be it. Measure generate wall-clock in
  the first build; if it wedges, this is where G30's job/progress pattern finally gets
  built.
- **Motion / WPO.** The spike didn't audit whether `PCG_Tree_*` carry WPO wind (the G40/G58
  saga). The grow census must run the same `asset.material_motion` classifier the paint
  path does, and expose the same `rules.wind:"off"` WPO-disable knob if the palette trees
  float when instanced. Do not assume PCG meshes are static.
- **World Partition residency.** Generated instances on an Open World map land in
  partitioned cells; confirm `outliner op=reconcile` and `level op=streaming` see them
  correctly and that a save persists them (the spike saved without complaint, but 333k
  instances across external-actor cells wants a residency check).
- **Palette vetting.** Each palette graph must pass R3/G56 (no plugin-runtime leaf masters
  that render bare) before it earns a name — the same gate `foliage op=paint` enforces.
- **Volume must be TALL, not surface-thin (build gotcha, found 2026-07-05).** The
  SimpleForest sampler ray-hits the world over the volume's Z extent; a volume sized to a
  terrain's near-flat AABB (≈20 m tall) silently generates **zero** instances. `on=<surface>`
  must bracket the surface with generous headroom (the spike used ±60 m and worked; ±10 m
  gave nothing). Also: **spawn the volume already positioned/scaled, then generate** —
  moving a PCGVolume *after* a generate left stale state and produced zero on regen; a clean
  spawn at the right transform is reliable. The verb sizes the box from the surface AABB in
  XY but a fixed tall Z, and never mutates the transform between set_graph and generate.
- **PCG palette meshes carry `wpo` wind (found 2026-07-05).** `PCG_Tree_*`/`PCG_Seedling_*`
  classify as `wpo` (per-vertex wind), NOT the `pivot_wpo` rigid-float bug (G40) — they sway
  correctly on instances. Desirable, not a defect, but the grow census should surface the
  motion verdict so "this forest moves" is stated, and `rules.wind:"off"` (G58) stays
  available if a level wants it stilled.

## Sequencing

Independent of SPEC-09 (runtime lint). Depends on nothing unbuilt — path A rests entirely
on spike-proven capability. Recommended first build: the palette registry + `op=generate`/
`op=cleanup` against ONE curated graph, dogfooded on a real level (retire the hand-rolled
scatter in [[ueb-forest-level-status]] as the proof). `op=regenerate` and any parameter
work (path B) follow only if dogfooding demands them.

## Spike trace (2026-07-05, all over the RC bridge)

1. Class probe: `PCGComponent/PCGGraph/PCGVolume/PCGWorldActor` present;
   `PCGSubsystem` absent; `ProceduralFoliageSpawner.simulate` exists but 0 spawner assets
   ship and `ProceduralFoliageType` is absent → PCG is the live path, not Procedural
   Foliage.
2. `set_graph`/`generate(force)` signatures confirmed; `SimpleForest` graph loads.
3. Full drive: spawned `pcg_forest_spike` PCGVolume, scaled to ±15000/±6000 box over the
   terrain, `set_graph(TPL_Showcase_SimpleForest)`, `generate(True)` → **332,941
   instances**, all z=0 on the terrain surface, own `PCG_*` meshes.
4. `cleanup(True)` emptied it; regenerated + saved to `/Game/Maps/UEB_PCGSpike` for the
   user's visual judgment.
5. Parameter probe: `SimpleForest.user_parameters` is an empty `InstancedPropertyBag`; no
   `get/set_graph_parameter` in 5.8 Python; `call_method` present on graph + instance
   (theoretical fallback, unneeded). Richer forest graphs enumerated under
   `/PCG/SampleContent/…` and `/ProceduralVegetationEditor/…`.

Spike #2 — node-value tuning (2026-07-05, deciding the palette question):

6. `graph.nodes` → 16 nodes; each `node.get_settings()` returns a typed `PCGSettings`
   subobject (3× `PCGSurfaceSamplerSettings`, `PCGStaticMeshSpawnerSettings`,
   `PCGSelfPruning`, `PCGTransformPoints`, …). Settings props read fine
   (`points_per_squared_meter=0.015`, `point_extents`, `point_steepness`, `looseness`,
   `seed`).
7. `EditorAssetLibrary.duplicate_asset(SimpleForest → /Game/UEB_PCG/Grow_test)`, then
   `set_editor_property("points_per_squared_meter", old/8)` on all three samplers, saved.
   Repointed the spike volume at the copy, `generate(True)` → **44,502 instances**
   (seedlings 331k → 44k) — the code-authored density propagated through generation
   exactly. Palette-in-code path proven end to end; no PCG node editor touched.
