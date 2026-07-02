# Dogfood levels

Test fixtures, not deliverables. Each level exists to exercise a slice of the verb
surface and surface friction (→ gaps.md). Build enough to make the server sweat, log
what breaks, move on. A level is "done" when it stops teaching us anything, not when
it looks good.

## Level 1 — Valley of trees

A forest in a mountainous valley with a winding path through the trees.

This is SPEC-01's home turf and the first rung of the environment ladder (README):
valley → path → hamlets → castle. As a dogfood fixture it exercises:

- `landscape` — valley landform (two ridge features + floor), `describe` sampling,
  `flatten` pads.
- `path` — route form (`{"turn": ±deg, "distance": cm}`), winding = alternating
  gentle turns; `carve` grading; placement `along=`/`facing=` the path.
- `scatter` — the forest as a population (species mix, density, seed), auto-clearing
  the path. Directly stresses G14 (HISM instances not rendering).
- `view(action="map")` — the only legal source of absolute `[x,y]`; plan the path on
  the map, confirm the drawn result against the read intent.

Status: the hamlet exit test already walks a slice of this. Extending it = more
terrain area, denser scatter, longer route chains — a scale test as much as a verb
test.

## Level 2 — Canyon to cave, cabin inside

A slot canyon that leads to a cave; inside the cave, a cabin.

Chosen because it's *hostile* to the current surface — each element attacks a known
soft spot:

- **Canyon** — steep, near-vertical terrain. The heightmap-style landform features in
  SPEC-01 were designed for valleys and hills; a slot canyon stresses slope limits,
  wall fidelity, and whether `landscape describe` stays honest on cliff faces.
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

## Level 3 — TBD

Ryan hasn't decided yet. Candidates worth considering when the time comes, ranked by
what they'd newly exercise rather than by looks:

- **Castle approach** (rung 1's finale) — large modular kit composition at scale,
  asset acquisition workflow (5.8-filtered Fab pack), silhouette/landmark placement
  read off the map.
- **Lakeside hamlet** — water (nothing in the surface touches water yet), shoreline
  scatter rules, reflections making vision judgment calls harder.
- **Obstacle course** (rung 2's donut) — the first level with *logic*: triggers,
  moving platforms, respawn. Gated on the Blueprint logic verb; would mark the jump
  from environments to game systems.

Whatever it becomes, pick it for the verbs it breaks, not the postcard it makes.
