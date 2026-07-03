# Guidance for LLMs driving ue-buttons

Field notes, ported from blender-buttons (chair, treasure chest, sword-in-the-stone,
a bust) and extended with what the first UE builds (the M1 table, the SPEC-01 hamlet)
taught. Read this before building. The rules that were true in Blender are mostly
properties of *LLMs doing 3D*, not of Blender — assume they apply here unless this
file says otherwise.

## The one rule

**THE ONE RULE lives in the server `instructions`** — always in your context, so it is
not restated here. In one breath: derive, don't divine — every number you type must
have a provenance (a status-block bound, a `feel` read, a `describe` sample, a map you
read, a dimension you authored), and spatial *relationships* are read with `feel`, not
computed in your head. Everything below is how to **live** that rule.

## The status block is your instrument panel

Every mutating call returns exact world bounds. **Trust and use them.** A whole
kit-composed cabin can be built as arithmetic on previous bounds — each wall seats on
the last piece's reported bounds, on the kit's 4 m grid, with zero corrections.
Maintain a stack-up/grid table as you go. Asking the scene again is almost never
needed; the answer was in the last status block.

**But watch for exact equality.** Two bounds that *match* exactly are a bug, not a
coincidence: coplanar faces z-fight (two kit walls in one plane, a floor at exactly
terrain height). blender-buttons has an always-on `validate` floor that catches this
unasked. **ue-buttons does not yet (SPEC-02)** — until it lands, treat every exact
match in your own table as a finding, and space or offset deliberately.

**No floor also means no collision self-report.** After a placement that could
penetrate, bury, or float, run `feel` on the touched actor (contacts, ground
relationship) instead of assuming silence means clean. When SPEC-02 lands this
paragraph inverts: the floor reads for you, and quieting a finding requires declaring
intent with a reason — there will be no "ignore".

**One dependent mutation per message.** Batched tool calls can execute in arrival
order, not authored order. Placements that each read their own reference are safe to
batch; chains where op 2 builds on op 1's result (place pad → place cabin on pad) are
not. Issue chained mutations one per message, each seeing the prior status block.

## Vision: composition and reading — never measurement

LLM vision self-confirms — you will see what you expected and report success whether
or not it's true — so an image can never *verify* what a mechanical read can answer
exactly. That rule is inherited from blender-buttons and it stands. What changes in UE
is that vision now has two **legitimate, load-bearing** jobs:

- **Reading `view(action="map")`.** The labeled top-down map exists precisely so that
  absolute `[x,y]` positions are *read off something real* instead of divined. Read the
  map → pick positions → act → map again to confirm the drawn result matches the read
  intent. That second look is comparing two images for gross agreement — legitimate.
  Concluding "the cabin is 3 m from the path" from pixels is not; that's `feel`.
- **Judging the place.** "Does this read as a hamlet?" — composition, lighting, mood —
  is a judgment call you make *before* burning the human's attention, and the human
  makes finally. Screenshot at visual milestones and show them.

And one inherited assumption to drop: blender-buttons could say "the human is ALWAYS
watching the live viewport." Here they may not be — builds run while the human is
away. So capturing to *show* your work at milestones is not wasteful; it's the report.
What stays forbidden is capturing to *check* placement or to *hunt* for geometry —
mechanical reads first, always.

## Placement: relational first, polar second, map-read third

The preference order for saying *where*:

1. **Relational** — `place={"on": ...}`, `at_corner`, `between`, `along=`/`facing=` a
   path. The runtime computes from live bounds; survives everything moving.
2. **Polar from an anchor** — `{"from": <label|path@frac|feature>, "bearing": deg,
   "distance": cm}`. Bearing ≡ UE yaw (north = +X, clockwise). How surveyors work.
3. **Absolute [x,y] read off `view(map)`** — legal, last resort, and only ever with
   that provenance.

Route form for paths: `{"start": ..., "steps": [{"turn": ±deg, "distance": cm}, ...]}`
— winding is alternate gentle turns. The runtime walks it and **returns every resolved
waypoint**; read them back instead of dead-reckoning where the chain ended.

## Assets: measure before you place

- **Inventory first.** `asset(action="inventory", pack=...)` gives families, variants,
  dims, and **pivots**. The pivot is the #1 predictable bug: a base-pivot tree placed
  like a center-pivot prop buries itself to the waist. The `add` runtime corrects for
  pivots — but only because the inventory measured them; trust its dims over the pack's
  marketing name (`Wall_4m` is 400 cm *wide*, not tall).
- **Native scale by default.** Marketplace dims are placement information, not a resize
  invitation — a cabin wall is 400 cm because its doorframe is human-sized. `dims=` on
  an asset scales and warns; have a reason.
- **Kit composition is grid arithmetic.** The cabin kit is a 4 m module, 3 m walls,
  20 cm thickness. Compose on the grid using each placed piece's reported bounds;
  never freehand a wall position.
- **Ambiguity errors are information.** "Pine_Tree matches 5 variants" means pick one
  (`add`) or let the population randomize (`scatter`) — don't just grab `_01` for a
  hero placement without looking at the dims.

## Terrain, paths, scatter: the environment order of operations

Order matters because each layer derives from the one below:

1. **Landscape first** — shape the landforms, then `flatten` pads for anything that
   needs level ground. `landscape describe` samples height/slope at map points; use it
   instead of tracing when planning (same height function built the mesh). Assign a
   `material=` (find one via `asset find kind=material`) — an unmaterialed terrain
   renders flat grey and hides every feature you cut into it.
2. **Paths second** — created draped over the terrain, then `carve` to grade, then
   `surface` with a contrasting material (dirt vs the terrain's grass). A carve alone
   is nearly invisible at eye level — the material strip is what makes the path READ
   as a path (gaps.md G25's lesson). The path is the settlement's skeleton: buildings
   place `along=`/`facing=` it.
3. **Buildings on pads** — flatten before placing; ground-snap (`place={"ground": true}`).
4. **Scatter last** — populations, not actors. Declare species mix, density, rules,
   seed. Scatter auto-clears existing paths and buildings — which only works if they
   exist first. The winding path through the trees is made by scatter *respecting* the
   path, never by deleting trees afterwards.
5. **Reroll, don't tweak.** A scatter stand you don't like is
   `scatter(action="regenerate", seed=...)` — same rules, new dice. Hand-moving
   individual instances is fighting the abstraction; if you keep wanting to, the rules
   are wrong — fix the rules.

Scatter groups are ONE actor each (HISM). `scene` reports "1,847 instances, 3 species"
— never ask for per-instance listings; nothing good is done with 1,847 rows.

## Undo is shared with the human — respect it

Every ueb mutation is a `ueb:<id>` transaction, 1:1 with the editor's undo stack, and
`history undo_to` rewinds by count. But the stack is **shared**: a manual edit the
human makes between your ops desyncs the count, and your undo would eat their edit
(gaps.md G1). Before a deep `undo_to`, confirm the human hasn't been editing alongside
you. Spatial verbs that report `undoable: false` (DynamicMesh terrain, HISM scatter)
mean exactly what they say — teardown for those is their own remove/reset actions, not
Ctrl+Z. The honest flag is a feature; plan around it.

## Working with the editor's quirks (field-verified)

- **Screenshots need a foregrounded editor** (gaps.md G8): high-res capture is async on
  the render thread and may never land while the editor window is backgrounded. If a
  capture times out, say so and ask the human to foreground the window — don't retry in
  a loop and don't report a stale image as current.
- **Perception is ueb-scoped** (G7): the Open World template ships ~135 scaffolding
  actors with real, sprawling bounds. `scene`/`feel` filter to ueb-tagged actors and
  report the untracked count. `include_all=True` exists; reach for it only when hunting
  something you didn't spawn.
- **Long ops have long timeouts for a reason**: `landscape` calls run up to minutes
  (mesh rebuild). Don't parallel-fire terrain edits; sequence them.
- **Creating a level from the Open World template is a trap** (G36): every
  template-copied always-loaded actor (DirectionalLight, SkyLight, SkyAtmosphere,
  VolumetricCloud, ExponentialHeightFog, PlayerStart, SkySphere) LOOKS fine in the
  editor but its descriptor never resolves at game time — Play renders an unlit void
  and the pawn spawns at the origin. If you (or raw editor Python) create a level with
  `new_level_from_template(..., OpenWorld)`, immediately DELETE the template env set and
  respawn each actor fresh (sky_light wants real_time_capture), place a PlayerStart via
  `add(what="player_start", ...)`, save — then run `scene op=pie_census` (call it twice:
  it starts Play, then censuses the GAME world and ends Play) and require
  `missing_at_runtime` to be empty before handing the level to a human. Editor-side
  reads can NOT see this defect; only the game-truth census can.

## HITL: the partnership split

The human owns taste and experiential judgment ("does it read as a place", "does the
walk feel right" in PIE); you own precision and mechanical verification. Surface taste
questions instead of guessing — asset choice between plausible variants, composition,
whether a style clash matters. And when mechanical verification and your expectation
disagree, the read wins; when two reads disagree, stop and tell the human — that's a
gap to file, not a coin to flip.
