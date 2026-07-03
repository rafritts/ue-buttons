# Dogfood levels

Test fixtures, not deliverables. Each level exists to exercise a slice of the verb
surface and surface friction (→ gaps.md). Build enough to make the server sweat, log
what breaks, move on. A level is "done" when it stops teaching us anything, not when
it looks good.

## Level 1 — Valley of trees

A forest in a mountainous valley with a winding path through the trees.

This is SPEC-01's home turf and the first rung of the environment ladder (README):
valley → path → hamlets → castle. As a dogfood fixture it exercises:

- `terrain` (built as `landscape`, renamed in SPEC-05) — valley landform (two ridge
  features + floor), `describe` sampling, `flatten` pads.
- `spline` (was `path`) — route form (`{"turn": ±deg, "distance": cm}`), winding =
  alternating gentle turns; `terrain op=carve` grading; placement `along=`/`facing=`
  the route.
- `foliage` (was `scatter`) — the forest as a population (species mix, density, seed),
  auto-clearing the trail. Directly stresses G14 (HISM instances not rendering).
- (The `view(map)` bullet is history: the view verb was deleted with the no-LLM-vision
  policy. Absolute `[x,y]` now comes from polar anchors and describe reads only.)

Status: BUILT 2026-07-02 (live, through `dispatch`). 300 m valley (`landscape create`
+ `shape`: valley trough along X, two ridge walls E/W, noise — 108 m relief), a 278 m
winding trail down the floor (`path` route form, ±22° oscillation; `carve`d), and a
6,236-instance forest (`scatter`, 5 species / 32 FoliageTypes) that slope-rejected 4,823
candidates at the treeline and clear-rejected 436 to keep the trail open. Verified: all
6,236 instances live across 128 *registered* FISMCs, every one tagged `valley_forest`
(G14 holds at scale); `view(map)` reads as a valley. Scale test passed — 3× the hamlet's
area, ~2.4× its scatter.

What it taught (the point of the fixture): **B3** — `path` drape traced the terrain
before its collision finished cooking, silently wrote `z=0.0` on 4/9 waypoints, and
`carve` then baked that into a raised causeway. **G15** — `landscape describe` reports the
feature height-function, not the post-carve mesh, so describe⇄trace silently diverge after
an edit. **G16** — ueb `_state` outlives the level; the prior hamlet session's scatters/
paths were phantom-present in this fresh level (no level lifecycle verb). Palette reality
reconfirmed: the SM "trees" are branch/sapling pieces (tallest 4.4 m), the real trees are
skeletal (unscatterable) — the forest reads as scrub at human scale, fine for a fixture.

Done enough — it's still teaching (three live findings), but the next lessons are B3/G15/
G16 fixes, not more valley. Leaving the geometry as-is (dogfood: don't agonize over the
scene).

## Level 2 — Canyon to cave, cabin inside

A slot canyon that leads to a cave; inside the cave, a cabin.

Chosen because it's *hostile* to the current surface — each element attacks a known
soft spot:

- **Canyon** — steep, near-vertical terrain. The heightmap-style landform features in
  SPEC-01 were designed for valleys and hills; a slot canyon stresses slope limits,
  wall fidelity, and whether `terrain op=describe` stays honest on cliff faces.
- **Cave** — the big one: **a heightfield cannot make a cave.** One z per (x,y) means
  no overhangs, no interiors. This level forces the question SPEC-01 deferred: rock/
  cliff kit meshes composed into negative space, or DynamicMesh boolean carving. Either
  way it's new verb territory (or a deliberate "not yet" gap) — that's the point.
- **Cabin in the cave** — kit composition (Modular Rural Cabin, 4 m grid) inside an
  enclosed space with no skylight. Stresses: placement inside geometry (does spatial
  lint scream about "penetrating" the cave shell?), interior lighting (nothing in the
  surface does lights yet — likely a new gap), and screenshots in the dark (G8 gets a
  sibling: a technically-successful capture of pure black).

Expected yield: a fistful of gaps before anything looks like a cave. That's success.

## Level 3 — Cabin on a lake

A calm mountain lake with a cabin on the shore. A wooden dock reaches out over the
water. A stream feeds the lake from the hills, and a rowboat sits tied at the dock.
Trees come down to the waterline except around the cabin's clearing.

That's the whole brief — deliberately. Nobody involved knows how water works in UE5,
and **no one is allowed to find out before the build starts.** The vision comes first,
stated naively; discovering how the engine realizes it (and what the verb surface is
missing) IS the dogfood. Researching water up front to write a more "implementable"
level would launder the friction out of the fixture.

---

A note on all three levels: they're artist visions to be *carried out*, not
negotiated. If the surface can't express part of a vision, that's a gap to log — not
a reason to bend the vision toward what's easy. Pick and build them for the verbs
they break, not the postcard they make.
