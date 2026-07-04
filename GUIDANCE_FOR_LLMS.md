# Guidance for LLMs driving ue-buttons

Field notes, ported from blender-buttons (chair, treasure chest, sword-in-the-stone,
a bust) and extended with what the first UE builds (the M1 table, the SPEC-01 hamlet)
taught. Read this before building. The rules that were true in Blender are mostly
properties of *LLMs doing 3D*, not of Blender — assume they apply here unless this
file says otherwise.

## The one rule

**THE ONE RULE lives in the server `instructions`** — always in your context, so it is
not restated here. In one breath: derive, don't divine — every number you type must
have a provenance (a status-block bound, a `feel` read, a `describe` sample, a `spline
op=describe` waypoint, a dimension you authored), and spatial *relationships* are read
with `feel`, not computed in your head. Everything below is how to **live** that rule.

## The status block is your instrument panel

Every mutating call returns exact world bounds. **Trust and use them.** A whole
kit-composed cabin can be built as arithmetic on previous bounds — each wall seats on
the last piece's reported bounds, on the kit's 4 m grid, with zero corrections.
Maintain a stack-up/grid table as you go. Asking the scene again is almost never
needed; the answer was in the last status block.

**But watch for exact equality.** Two bounds that *match* exactly are a bug, not a
coincidence: coplanar faces z-fight (two kit walls in one plane, a floor at exactly
terrain height). The always-on `validate` floor (SPEC-02) catches this unasked on every
add/transform and reports by exception on the status block; quieting a laden finding
requires declaring intent with a reason (`validate op=expect`) — there is no "ignore".
`validate op=run` sweeps the whole scene on demand; run it at milestones.

**One dependent mutation per message.** Batched tool calls can execute in arrival
order, not authored order. Placements that each read their own reference are safe to
batch; chains where op 2 builds on op 1's result (place pad → place cabin on pad) are
not. Issue chained mutations one per message, each seeing the prior status block.

## No vision — instruments only, never a picture

LLM vision is RECOGNITION, not measurement and not reasoning. It self-confirms — you
will "see" what you expected and report success whether or not it's true — so it is
**not reliable enough for this work**, full stop. There is **no screenshot, render, or
image verb**, on purpose. Do not render images, do not request them, do not narrate what
you "would see", and do not burn tokens trying to get a picture: there is no path to
one, by design, and reaching for it is wasted effort you should feel yourself starting
and stop.

Everything you'd reach an image for is a NUMBER here:

- **On the pad? buried? floating?** → `feel` (`rests_on` / `gap_between` / `describe`).
- **Framed, big enough, occluded?** → `feel op=framing` / `feel op=visible` — screen
  coverage, `est_px`, `occluded_fraction`, verdicts. Numbers off the viewport camera,
  never a rendered frame.
- **Does it draw?** → the `render:` status line and `feel op=render_state` (the full
  gating chain + the fix).
- **What does the ground do at [x,y]?** → `terrain op=describe` (height + slope samples).

If an appearance question has **no instrument yet** — "does this pine read as bare?",
"is the forest dense enough?", "is that foliage bobbing?" — that is a **gap to LOG**
(gaps.md), not a cue to look. Logging it is how the instrument gets built; that IS the
dogfood loop. The human owns every visual and taste call, from their own screen — do not
assume they're watching the viewport, report your findings as numbers and let them look.

## Placement: relational first, polar second, map-read third

The preference order for saying *where*:

1. **Relational** — `place={"on": ...}`, `at_corner`, `between`, `along=`/`facing=` a
   spline. The runtime computes from live bounds; survives everything moving.
2. **Polar from an anchor** — `{"from": <label|spline@frac|feature>, "bearing": deg,
   "distance": cm}`. Bearing ≡ UE yaw (north = +X, clockwise). How surveyors work.
3. **Absolute [x,y] from a READ** — an actor centre (`feel`/`outliner`), a `spline
   op=describe` waypoint, or a `terrain` bound. Last resort, and only ever with that
   provenance — never a coordinate typed from imagination.

Route form for splines: `{"start": ..., "steps": [{"turn": ±deg, "distance": cm}, ...]}`
— winding is alternate gentle turns. The runtime walks it and **returns every resolved
waypoint**; read them back instead of dead-reckoning where the chain ended.

## Assets: measure before you place

- **Inventory first.** `asset(op="inventory", pack=...)` gives families, variants,
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
  (`add`) or let the population randomize (`foliage op=paint`) — don't just grab `_01`
  for a hero placement without looking at the dims.

## Terrain, splines, foliage: the environment order of operations

Order matters because each layer derives from the one below:

1. **Terrain first** — shape the landforms, then `flatten` pads for anything that
   needs level ground. `terrain op=describe` samples height/slope at map points; use it
   instead of tracing when planning (same height function built the mesh). Assign a
   `material=` (find one via `asset op=find kind=material`) — an unmaterialed terrain
   renders flat grey and hides every feature you cut into it.
2. **Splines second** — created draped over the terrain, then `terrain op=carve
   along=<spline>` to grade, then `spline op=surface` with a contrasting material (dirt
   vs the terrain's grass). A carve alone is nearly invisible at eye level — the
   material strip is what makes the trail READ as a trail (gaps.md G25's lesson). The
   route is the settlement's skeleton: buildings place `along=`/`facing=` it.
3. **Buildings on pads** — flatten before placing; ground-snap (`place={"ground": true}`).
4. **Foliage last** — populations, not actors. Declare species mix, density, rules,
   seed. Painting auto-clears existing splines and buildings — which only works if they
   exist first. The winding trail through the trees is made by foliage *respecting* the
   route, never by deleting trees afterwards.
5. **Reroll, don't tweak.** A stand you don't like is `foliage(op="reseed", ...)` —
   same rules, new dice. Hand-moving individual instances is fighting the abstraction;
   if you keep wanting to, the rules are wrong — fix the rules.

A stand is ONE label (instanced foliage). Its `describe` reports "1,847 instances,
3 species" — never ask for per-instance listings; nothing good is done with 1,847 rows.

## Undo is shared with the human — respect it

Every ueb mutation is a `ueb:<id>` transaction, 1:1 with the editor's undo stack, and
`history undo_to` rewinds by count. But the stack is **shared**: a manual edit the
human makes between your ops desyncs the count, and your undo would eat their edit
(gaps.md G1). Before a deep `undo_to`, confirm the human hasn't been editing alongside
you. Spatial verbs that report `undoable: false` (DynamicMesh terrain, instanced foliage)
mean exactly what they say — teardown for those is their own remove ops, not
Ctrl+Z. The honest flag is a feature; plan around it.

## Working with the editor's quirks (field-verified)

- **Perception is ueb-scoped** (G7): the Open World template ships ~135 scaffolding
  actors with real, sprawling bounds. `outliner`/`feel` filter to ueb-tagged actors and
  report the untracked count. `include_all=True` exists; reach for it only when hunting
  something you didn't spawn.
- **Long ops have long timeouts for a reason**: `terrain` calls run up to minutes
  (mesh rebuild). Don't parallel-fire terrain edits; sequence them.
- **Never force-delete an in-use asset over the bridge** (G47): `delete_directory` /
  force-delete over an asset that's still referenced (even a scratch Material you
  authored moments ago — natively referenced, never saved) raises an "is in use" modal
  → handled ensure → the editor WEDGES with the RC thread hung; recovery is taskkill +
  relaunch. Cleanup order for scratch assets: delete REFERENCERS first (actors, then
  meshes, then materials), polite `delete_asset` only, and tolerate a failed polite
  delete — an unsaved asset evaporates on editor restart anyway.
- **Creating a level from the Open World template is a trap** (G36): every
  template-copied always-loaded actor (DirectionalLight, SkyLight, SkyAtmosphere,
  VolumetricCloud, ExponentialHeightFog, PlayerStart, SkySphere) LOOKS fine in the
  editor but its descriptor never resolves at game time — Play renders an unlit void
  and the pawn spawns at the origin. If you (or raw editor Python) create a level with
  `new_level_from_template(..., OpenWorld)`, immediately DELETE the template env set and
  respawn each actor fresh (sky_light wants real_time_capture), place a PlayerStart via
  `add(what="player_start", ...)`, save — then run `play op=census` (call it twice:
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
