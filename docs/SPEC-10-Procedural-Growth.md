# SPEC-10 — Procedural Growth: wrapping PCG as an intent verb

Status: **DESIGN** (2026-07-05). Grounded by a live spike — every capability claim below
was exercised over the RC bridge, and the numbers are real (spike trace at the bottom).
The verb name and the parameter strategy need the user's sign-off before build; the two
open forks are called out explicitly.

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

## The central design question — parameters

Firing a stock graph is trivial; **tuning it by intent is the hard part.** The spike
found `SimpleForest.user_parameters` is an **empty `InstancedPropertyBag {}`** — the
showcase graphs hardcode their values in nodes and expose no override surface. There is no
`get_graph_parameter`/`set_graph_parameter` on `PCGGraphInstance` in 5.8 Python; the only
`override_*` methods are cosmetic (title/color/category). So "grow a *sparse* pine forest"
cannot be a scalar we poke into the stock graph. Two honest paths, and this is **fork #1
for the user**:

- **(A) Curated graph palette — RECOMMENDED.** A human authors (or we adopt + lightly
  tune) a small set of *named* graph variants in-editor, ONCE: e.g. `pine_dense`,
  `mixed_sparse`, `grass_meadow`. The agent selects one by intent name and points it at a
  surface. No parameter override needed; the taste lives in the graph, authored once by
  the human — which is exactly our partnership model (human owns taste, agent owns precise
  placement). This is buildable today with only what the spike already proved.
- **(B) Property-bag override — DEFERRED.** For graphs that DO expose `user_parameters`,
  reach the `InstancedPropertyBag` via `call_method` against the C++
  `GetGraphParameter`/`SetGraphParameter` (both `PCGGraph` and the instance expose
  `call_method`; untested for params). Higher risk, and moot until a param-exposing graph
  is in play. Build it when a concrete need shapes it (the G30 ratchet), not speculatively.

Path A ships the verb; path B is a later enrichment. The verb's real intent knobs on day
one are the two the spike already proved: **which graph** (the palette) and **which
surface / how large an area** (the volume bounds — `on=<terrain>` maps to the volume's
scaled box).

## Verb shape (proposal — needs sign-off, fork #2)

PCG is procedural *foliage/vegetation* generation, and `foliage` already owns instanced
scatter. Recommendation: **extend `foliage`, don't mint a verb** — consistent with SPEC-05
(if UE owns a word, that verb owns it; `op=` is the discriminator) and with SPEC-08's
"no new verb" precedent.

```
foliage op=grow  graph=<palette name>  on=<terrain/surface label>  [region=…]  [seed=n]
foliage op=regrow  label=<grove>        # re-run generate() after a surface/param change
foliage op=ungrow  label=<grove>        # cleanup(True) + destroy the volume — full reversal
```

- `graph=` resolves against the curated palette (SPEC decision: palette is a small
  registry in the runtime, mapping intent names → `/Game` or `/PCG` graph paths, each
  vetted the way our FoliageType minting is).
- `on=` is relational, not coordinate: the named surface's AABB sizes and positions the
  PCGVolume (bounds proven to drive sampling extent). `region=` optionally clips to a
  circle/rect the way `foliage op=paint` already does.
- The result is a labelled, ueb-tagged PCGVolume actor — it joins the outliner registry
  and reconcile like any other ueb actor, so `op=ungrow` and level lifecycle
  (`level op=clear`) already know how to tear it down.

The alternative — a dedicated `grow` verb — is on the table if the user judges procedural
generation conceptually distinct enough from hand-painting to deserve its own word. I lean
against (it splits "put plants on the ground" across two verbs), but it's the user's call.

## Perception — census, numbers only

Policy holds: no screenshot, the agent perceives the result as numbers. After a grow, walk
the volume's managed ISM components and count per `static_mesh` — proven in the spike (5
components, exact per-species counts). The verb returns a **per-species census** and the
volume's world-AABB coverage:

```
grew grove_north (graph=mixed_sparse, on=terrain):
  1329 trees  (PCG_Tree_01 ×425, _02 ×489, _03 ×415)
   200 boulders (PCG_Boulder_02)
  331412 seedlings (PCG_Seedling_01)     ← untuned showcase density; see note
  coverage: x[-15000,15000] y[-15000,15000], on terrain surface
  → foliage op=ungrow label=grove_north      # ready to fire
```

Every grow carries the HATEOAS `next` (regrow / ungrow), per the vision law. The seedling
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

## Sequencing

Independent of SPEC-09 (runtime lint). Depends on nothing unbuilt — path A rests entirely
on spike-proven capability. Recommended first build: the palette registry + `op=grow`/
`op=ungrow` against ONE curated graph, dogfooded on a real level (retire the hand-rolled
scatter in [[ueb-forest-level-status]] as the proof). `op=regrow` and any parameter work
(path B) follow only if dogfooding demands them.

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
   (route for path B, untested). Richer forest graphs enumerated under
   `/PCG/SampleContent/…` and `/ProceduralVegetationEditor/…`.
