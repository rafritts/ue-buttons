# SPEC-10 — `pcg`: wrap UE's PCG framework as an intent verb

Status: **IMPLEMENTED + live-verified** (2026-07-05). Audience: the agent implementing the
verb. Every engine claim below is spike-proven over the RC bridge (traces at bottom)
unless marked **SPIKE-CHECK** — those you verify live before relying on them. Filename
keeps the original "Procedural-Growth" slug; the verb is `pcg`.

## BUILD OUTCOME (2026-07-05)

Shipped: `pcg` verb (generate/regenerate/cleanup/describe/palette), runtime `pcg.py`,
wired into `verbs.py` (SPATIAL), reconcile/roster/outliner/`level op=clear`, sense-3
`render.grove_line`, the MCP tool, README + instructions. One curated palette entry
`mixed_sparse` (SimpleForest, density cut 8× → ~31k over a 252 m surface). Live-verified
end-to-end: palette + unknown-graph HATEOAS error, generate→census (per-mesh counts +
motion), seed reroll (arrangement changes, shared asset untouched), cleanup (volume +
instances gone), reconcile clean + orphan-GC, status block render line + grove roster.

**The one design change from this spec — generate is TWO-CALL, not a single-call poll.**
The spec assumed step 6's "poll until stable" runs inside one dispatch. It CANNOT: PCG
generation is asynchronous (it advances on the editor's tick), and a blocking Python
dispatch holds the game thread so the editor never ticks mid-call — an in-call poll sees
zero forever. There is no `PCGSubsystem`, no synchronous flush, no way to pump the tick
from Python (probed live). So generate FIRES the graph and returns `{"pcg":"generating"}`;
the next call with the same label COLLECTS the settled census and applies the WPO cure —
the G30 fire/collect job pattern, mirroring `play op=census`. `regenerate` is the same
two-call shape. This is the [[G30]] async-job pattern's first built instance.

The collect gates on the component's own `PCGComponent.generated` flag (False while the
graph is still running, True only when it finished — probed live), NOT on a count-stability
poll: a blocking dispatch holds the game thread so counts can't advance mid-call, and a
naive "stable across two reads" loop would finalize whatever partial total it caught. If
`generated` is still False, collect keeps the grove pending and returns the "call again"
stub — it never records a partial census or re-fires the graph.

SPIKE-CHECK outcomes: `PCGComponent.seed` IS a settable editor property (per-grove reroll,
shared graph untouched — verified: seed 7 → 31227, seed 99 → 31183). Generated ISM
components live ON the volume actor, so `destroy_actor` (cleanup + `level op=clear`'s
ueb-tag sweep) removes the instances with it — no pcg-aware pre-pass needed. Mesh vetting
(size/bare-render gate) is deferred to the palette-authoring path (the mesh-SWAP helper) —
the one shipped entry uses proven stock meshes; the motion half of vetting (pivot_wpo →
WPO-disable) IS built and runs on the census. Level save/reopen residency left to the
spike's proof (not re-run to avoid writing test state into the user's project).

---

## Decisions already made (do not relitigate)

- **Verb = `pcg`**, its own verb (user call, 2026-07-05, reversing `foliage op=grow`):
  PCG is a standalone UE system; predictability demands an unambiguous name. Ops mirror
  the PCG component's own API: `generate` / `regenerate` / `cleanup`.
- **Graphs = code-authored palette**: duplicate a stock graph → tune node settings in
  Python → save under `/Game/UEB_PCG/`. No node editor, no `user_parameters` (stock
  graphs don't expose any; 5.8 has no `get/set_graph_parameter`).
- **Scope is generic placement, not foliage.** PCG samples points (surface / spline /
  texture / volume / actors), filters them, and spawns assets (ISM instances, actors,
  Blueprints, spline meshes). Palette classes will grow beyond vegetation (dressing,
  kit assembly, rock formations). Boundaries to enforce in verb docs and errors:
  **terrain carves, spline routes, pcg populates** — `pcg` never sculpts geometry, and
  networks (roads/rivers) are `spline`'s to author, `pcg`'s to consume.
- **Perception = numbers only** (per-mesh census). No screenshots.
- Palette graphs are ordinary visible assets: the user can open `/Game/UEB_PCG/<name>`
  in the PCG node editor at any time. Nothing is hidden; only *our* authoring path is
  code.

## Verb contract

### MCP tool (`server/main.py`)

Follow the `foliage` tool as the template (thin projection, `call_ue`, long timeout):

```python
@mcp.tool()
def pcg(op: Literal["generate", "regenerate", "cleanup", "describe", "palette"] = "generate",
        label: str = "pcg", graph: str = None, on: str = "terrain",
        region: dict = None, seed: int = None, rules: dict = None,
        force: bool = False) -> str:
    ...
    return render(call_ue("pcg", p, timeout=240))
```

Also update: `server/_instructions.py` (verb list says 14 — becomes 15) and the README
verb table.

### Ops

| op | params | effect |
|---|---|---|
| `generate` | `graph=` (required), `on=`, `label=`, `region=?`, `seed=?`, `rules=?` | spawn a ueb-tagged PCGVolume sized to the `on=` surface, assign the palette graph, `generate(True)`, return census |
| `regenerate` | `label=`, `seed=?` | re-run `generate(True)` on the existing volume (after a surface/palette change, or reroll with a new seed) |
| `cleanup` | `label=` | `pcg_component.cleanup(True)` + destroy the volume + unregister — full reversal |
| `describe` | `label=` (omitted → all groves) | census + params from the registry, re-counted live; read-only |
| `palette` | — | list palette entries: name, source graph, mesh families, tuned density; read-only. This is the discoverability surface — `generate` with an unknown `graph=` errors with this same list (HATEOAS) |

Build order: `generate` + `cleanup` + `palette` first; `regenerate`/`describe` in the
same PR if cheap, else after dogfooding demands them.

### Errors (each carries the next legal move, per the vision law)

- unknown `graph=` → error listing palette names + `pcg op=palette`.
- unknown `on=` label → error naming the outliner lookup that failed.
- `generate` produced **0 instances** → NOT silent success: `degraded_warning` naming
  the two known causes (volume headroom, moved-after-generate — see Invariants) with the
  re-fire line.
- duplicate `label=` → error (labels are unique across ueb actors).

## Runtime implementation (`runtime/ue_buttons/pcg.py`, new module)

Mirror `foliage.py`'s shape: a `handle(p)` dispatching on `p["op"]`, returning a plain
dict. Wire into `verbs.py`:

- `from . import pcg as pcgmod`; add `"pcg": _v_pcg` to `_VERBS`.
- Add `"pcg"` to the `SPATIAL` set — same lifecycle class as terrain/spline/foliage:
  status block yes, history/transaction no, `undoable: false`, teardown is its own
  `cleanup`. `_focus_label` already handles SPATIAL via `result["label"]` — every
  mutating result must carry `label`.
- `_status_block`'s foliage-only `population_line` branch: extend the sense-3 render
  walk to pcg groves (same motivating case — a grove correct in data that draws
  nothing). If that's more than a small change, log it as a gap and ship without.

### State registry (`_state.py`)

```python
pcg_volumes = {}   # {label: {graph, on, seed, region, actor_name, counts}}
```

`_state` is never hot-reloaded (see its header) — a new module-level name is only
present after an editor restart, so every access goes through a
`hasattr(_state, "pcg_volumes")`-guarded init, same pattern as `_state.follow` in
`verbs.py`.

Registry lifecycle: extend `outliner op=reconcile` to diff `pcg_volumes` against the
live level (prune entries whose volume actor is gone), exactly as it does for
`terrains`/`foliage_stands`. Confirm `level op=clear` tears groves down via the
ueb-tag sweep — **SPIKE-CHECK**: destroying the PCGVolume actor must also remove its
generated instances; if orphans survive, `clear` needs a pcg-aware pre-pass
(`cleanup(True)` before destroy).

### `op=generate` algorithm

1. **Resolve** `graph=` in the palette (materialize the `/Game/UEB_PCG/` asset if
   missing — see Palette). Resolve `on=` to a live actor; AABB via `_ue.bounds(actor)`.
2. **Compute the volume transform.** XY center/extent from the AABB (clipped by
   `region=` if given — reuse foliage's region vocabulary: circle/rect/polygon/terrain,
   MAP cm). Z: center on the surface's z mid, half-extent `max(6000, surface_z_span/2 +
   2000)` cm — the sampler ray-casts over the volume's Z extent and a thin volume yields
   **zero** instances (proven: ±6000 worked, ±1000 gave nothing). PCGVolume's unscaled
   box is ±100 cm, so `scale3d = half_extents / 100`.
3. **Spawn the volume already at that transform** (`EditorActorSubsystem.
   spawn_actor_from_class(unreal.PCGVolume, loc)` + set scale before any generate).
   NEVER move/rescale it after a generate — proven to leave stale state that produces 0
   on regen. Label it, ueb-tag it (reuse `add`'s tagging helper so outliner/feel/level
   see it).
4. **Assign + fire**: `vol.pcg_component.set_graph(unreal.load_asset(palette_path))`
   then `comp.generate(True)`. There is NO `PCGSubsystem` in 5.8 Python — drive the
   component only.
5. **Seed** — **SPIKE-CHECK**: `PCGComponent` is expected to expose a `seed` property;
   if so, `seed=` sets it pre-generate (per-grove reroll without touching the shared
   palette asset). If not, per-grove seeding means writing node seeds — which would
   mutate the shared palette graph, so in that case duplicate the graph per grove or
   drop `seed=` from v1 and log a gap. Never mutate a shared `/Game/UEB_PCG` asset per
   call.
6. **Wait for completion (G30).** `generate(force)` can complete asynchronously (spike
   observed results landing a beat later). Poll: re-read the volume's ISM component
   instance counts until stable across two reads (with a bounded loop; the server call
   allows 240 s). Measure and record wall-clock in the result. If a big surface wedges
   the HTTP call anyway, this becomes G30's job/progress pattern — build it then, not
   speculatively.
7. **Census + motion audit.** Walk the volume's generated ISM components; count per
   `static_mesh` (proven: 5 comps, exact per-mesh counts). For each unique mesh run the
   same material-motion classifier the foliage path uses (`foliage.motion_census` /
   the asset-module motion helpers): meshes classified `pivot_wpo` rigid-float when
   instanced (G40) → set `world_position_offset_disable_distance = 1` on their ISM
   components post-generate (the G58 cure; proven on the fantasy plot). Plain `wpo`
   (wind sway) is left on but reported in the census. `rules={"wind":"off"}` forces the
   disable on ALL the grove's components (same knob as foliage G58).
8. **Register + return** (shape below). Also confirm the level saves + reopens with the
   instances intact once during verification — 333k instances across World Partition
   external-actor cells wants one explicit residency check (spike saved without
   complaint; re-verify after reopen).

### Result dicts

`generate`/`regenerate` (the status block renders around this; `notes` become ⚠ lines):

```python
{"label": "grove_north", "graph": "mixed_sparse", "on": "terrain",
 "census": [{"mesh": "PCG_Tree_01", "count": 425, "motion": "wpo"}, ...],
 "instances": 44502, "coverage": {"x": [-15000, 15000], "y": [-15000, 15000]},
 "wall_clock_s": 4.1, "seed": 7,
 "next": ["pcg op=regenerate label=grove_north seed=<n>",
          "pcg op=cleanup label=grove_north"]}
```

`cleanup`: `{"label": ..., "removed_instances": n, "removed": True}`.
`palette`: `{"palette": [{"name": "mixed_sparse", "source": "TPL_Showcase_SimpleForest",
"meshes": [...], "density_note": ...}, ...]}`.

## Palette registry (in `pcg.py`)

```python
PALETTE = {
    "mixed_sparse": {
        "source": "/PCG/GraphTemplates/TPL_Showcase_SimpleForest",
        "tune": _tune_mixed_sparse,   # (graph) -> None, edits node settings
    },
    ...
}
```

- **Materialize lazily**: `generate` with `graph=name` checks
  `/Game/UEB_PCG/<name>`; if absent → `EditorAssetLibrary.duplicate_asset(source,
  dest)` → run `tune(graph)` → save. Idempotent; the `/Game` copy is the asset of
  record and user-inspectable.
- **Tuning surface (all proven read+write over RC, propagate through generation):**
  - `PCGSurfaceSamplerSettings`: `points_per_squared_meter` (density),
    `point_extents`, `point_steepness`, `looseness`, `seed`.
  - `PCGStaticMeshSpawnerSettings`: `mesh_selector_parameters`
    (`PCGMeshSelectorWeighted`) `.mesh_entries` — array of
    `PCGMeshSelectorWeightedEntry`, each `{descriptor.static_mesh, weight}`. Rebuild
    this array to swap what grows (proven: pine/scrub/fantasy plots).
  - `PCGSelfPruningSettings` (spacing/overlap), `PCGTransformPointsSettings`
    (scale/rotation jitter).
  - Access pattern: `graph.nodes` → `node.get_settings()` → typed `PCGSettings`
    subobject → `set_editor_property`.
- **Mesh vetting is a hard gate on every entry's mesh list** (all cheap over RC):
  1. size — `mesh.get_bounds()` height sane for the slot (a 0.6 m sprig never becomes a
     canopy tree; proven need: Megaplant `Decoration_*`);
  2. bare-render / G56 — walk the mesh's material masters, reject runtime-dependent
     plugin masters (`MA_Foliage_Trees` etc., the R3 rule);
  3. motion — classify; `pivot_wpo` is allowed but must trigger the step-7 WPO disable.
  `force=True` on generate bypasses (1)–(2) with the same census-keeps-flagging
  semantics foliage uses.
- First shipped entries: ONE curated forest entry (tuned SimpleForest — sane seedling
  density so nobody ever sees 331k undergrowth) is enough to dogfood. `pine_dense` /
  `flower_grove` etc. follow as one tuning function each.

## Invariants (violating any of these produced real failures)

1. **Volume must be TALL.** Thin volume ⇒ silent zero instances. (±6000 cm worked;
   ±1000 did not.)
2. **Spawn at final transform, then generate.** Moving a generated volume then
   regenerating produced zero. Never mutate the transform between `set_graph` and
   `generate`.
3. **Drive `PCGComponent` directly** — no `PCGSubsystem` in 5.8 Python.
4. **Never mutate a shared palette asset per call** (seeds, densities) — per-grove
   variation goes through the component or a per-grove duplicate.
5. **Zero instances is a warning, never a silent success.**
6. **Every mutating result carries `label`** (the SPATIAL status block depends on it).

## Verification plan (live, over the MCP tools, before commit)

1. `pcg op=palette` lists the curated entry. `op=generate graph=<bad>` errors with the
   list.
2. `op=generate` on a fresh rolling-terrain level: census non-zero, counts match a
   manual ISM walk, volume is ueb-tagged and visible to `outliner`/`feel`, wall-clock
   recorded.
3. `op=cleanup`: instances gone (ISM walk = 0), actor gone, registry pruned,
   re-`generate` with the same label works.
4. `seed=` reroll changes the arrangement but not the palette asset (SPIKE-CHECK
   outcome documented in this spec when known).
5. `level op=save` → `op=open` (reopen): instances persist (World Partition residency).
6. `outliner op=reconcile` after a human-deletes-the-volume simulation prunes the
   registry entry.
7. Dogfood: rebuild the [[ueb-forest-level-status]] forest through `pcg` and retire the
   hand-rolled density math — that level is the acceptance test.
8. Failures found on the way become numbered gaps in `gaps.md` (fix → live-verify →
   prune), per house discipline.

## Open spike (not gating the first build)

**From-scratch graph authoring**: can editor Python CREATE a graph (add nodes, wire
edges — `PCGGraph.add_node`-shaped API), not just duplicate+tune? Decides whether new
palette *classes* (kit-assembly city, spline-dressing) can be grown entirely in code or
must start from the nearest stock/marketplace graph. Verb shape is unaffected either
way. Run it as its own spike before designing the second palette class.

## Ground truth — spike traces (2026-07-05, all over the RC bridge)

Spike #1 (capability), throwaway level `/Game/Maps/UEB_PCGSpike`, 30000 cm flat ueb
terrain:

1. Class probe: `PCGComponent/PCGGraph/PCGVolume/PCGWorldActor` present; `PCGSubsystem`
   absent; `ProceduralFoliageSpawner.simulate` exists but 0 spawner assets ship and
   `ProceduralFoliageType` is absent → PCG is the live path, not Procedural Foliage.
2. `set_graph`/`generate(force)` signatures confirmed; `SimpleForest` graph loads. The
   PCG plugin ships 56 graph templates (`TPL_Showcase_SimpleForest`,
   `…HierarchicalGenerationForest`, `…RuntimeGrassGPU`, sample content under
   `/PCG/SampleContent/…`, `/ProceduralVegetationEditor/…`).
3. Full drive: spawned PCGVolume, scaled ±15000 XY / ±6000 Z over the terrain,
   `set_graph(TPL_Showcase_SimpleForest)`, `generate(True)` → **332,941 instances**
   across 5 ISM comps (331,412 `PCG_Seedling_01`; 425/489/415 `PCG_Tree_01/02/03`; 200
   `PCG_Boulder_02`), all on-surface at z=0 — the graph sampled our **DynamicMesh**
   terrain's collision directly; no Landscape required
   ([[ue58-python-api-constraints]]).
4. `cleanup(True)` emptied it cleanly. Component also exposes `regenerate_in_editor`,
   `dirty_generated`, `get_generated_graph_output`, `override_generation_radii`.
5. Parameter probe: `SimpleForest.user_parameters` is an empty `InstancedPropertyBag`;
   no `get/set_graph_parameter` in 5.8; `call_method` exists as a theoretical fallback
   (unneeded).

Spike #2 (node-value tuning, decided the palette design):

6. `graph.nodes` → 16 nodes; `node.get_settings()` returns typed `PCGSettings`
   subobjects; properties read fine (`points_per_squared_meter=0.015`, etc.).
7. `duplicate_asset(SimpleForest → /Game/UEB_PCG/Grow_test)`, cut all three samplers'
   `points_per_squared_meter` 8×, saved, regenerated → **44,502** instances (seedlings
   331k → 44k). Code-authored density propagated exactly; no node editor touched.

Hand-grown proof levels (2026-07-05): tuned 8k-instance plot (601 pines / 7.4k
undergrowth / 28 boulders) on rolling terrain; three-palette variants level
(`/Game/Maps/UEB_ForestVariants`) — pine (`SM_Pine_Tree_*`), scrub
(`GV_Vol7_Shrub_*_full`), fantasy (`SM_FlowerTree_*`, pivot_wpo → WPO-disable applied)
— proving mesh-swap and the vetting gate (Megaplant `Decoration_*` auto-rejected: 0.6 m
AND `MA_Foliage_Trees`).
