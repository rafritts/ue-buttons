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

### G5 — `feel distance_between` ANY is AABB nearest-surface, not true mesh-surface
Status: OPEN (narrowed 2026-07-02 — AABB nearest-surface landed; only sub-AABB precision remains)

`distance_between(axis=ANY)` now returns the true nearest-surface distance between the two
world AABBs (the Euclidean length of the per-axis box gaps; 0 if they overlap) alongside the
centre-to-centre figure — exact for box footprints. The remaining gap is sub-AABB precision:
for a non-box mesh at contact range the nearest points lie on the actual surfaces, not the
bounding boxes. blender-buttons gets this from a BVH nearest query both directions, which UE
Python doesn't cheaply expose. Only matters for tight, non-box contact; port a
geometry-nearest path if perception ever needs that depth.

### G10 — modular room composition isn't expressible in the pure relational DSL
Status: OPEN (design note; E2 used derived-grid `at`, which is legitimate)

E2's exit test wants a cabin "composed from modular pieces using relational placement
only." The adjacency DSL (`left_of`/`in_front_of`/`at_corner`) expresses *abutting* pieces
well (a straight wall run tiles flush), but it can't express the two things a 4 m-grid room
needs: (a) spanning a fixed module — placing the back wall exactly 400 cm from the front,
not face-to-face — and (b) a perpendicular corner join where a yaw-90 wall meets the end of
another. E2 built the enclosure by reading the first wall's ground-snapped centre off the
scene and placing the other three at ±400 cm grid offsets (`at=` with `ground:true`). Under
the "derived, not divined" principle this is legitimate — the module (400 cm) is *measured*
from the wall family and the origin is a *perceived* anchor — but it isn't the relational
vocabulary. A future placement term would close the gap: `grid=(anchor, module, cell)` or a
`corner_join=(wall, end)` that snaps a perpendicular piece to another's end on the shared
grid. Verified mechanically: front↔back centre distance = 400.0 cm exactly; corners overlap
(negative gaps); roof eaves rest over the wall tops.

### G11 — the pack's "prebuilt cabins" are World assets, not spawnable Blueprints
Status: OPEN (palette knowledge for the user; E2/E6 adapt)

SPEC-01 expected "32 prebuilt cabin Blueprints" in Modular_Rural_Cabin. Reality (from
`asset packs`/`find`): the 32 Blueprints are modular *pieces* (Wall_*, Roof_*, Porch_*) plus
a few prop BPs (Mailbox, Outhouse, Trash_Bin); the 5 fully-built cabins ship as **World**
assets (level maps), which place via level-instancing, not `spawn_actor_from_class`. So E2's
"spawn one prebuilt cabin Blueprint" is satisfied by a prebuilt one-actor building BP
(Outhouse) — verified spawning as a single ground-snapped actor. For E6, a "prebuilt cabin"
means either level-instancing a cabin World (a new mechanism, not yet a verb) or composing
from modular pieces as E2 did. Flagged for the user (asset curation): if whole-cabin BPs are
wanted, they'd need to be authored from the World assets, or a `level-instance` placement
path added behind `add` (see SPEC-04 non-goals).

### G21 — z-fight against the ground surface is undetectable (the spec's own "floor at exactly terrain height" case can never fire)
Status: OPEN (found by SPEC-02 implementation review, 2026-07-02; deferred — needs placer-epsilon coordination first)

Two design choices, each individually correct, compose into a blind spot. (1) Substrates
(terrain, scatter stands, paths) are excluded from the neighbor pool because their AABBs
are meaningless for overlap — right call. (2) z-fight detection is AABB-face coplanarity —
right call for actor↔actor. Together: an actor coplanar with the *ground surface* — SPEC-02
explicitly lists "floors at exact terrain height" as a target case — has no detector. The
AABB method couldn't catch it anyway (a terrain's AABB max-z is its peak, not the local
surface).

But the ground detector already holds the number: `gap = base_z − trace_z`. Today
`|gap| ≤ GROUND_EPS` (2 cm) all reads as "resting". The fix is a third band:
`|gap| ≤ COPLANAR` (~2 mm) is *coplanar with ground* — an intent-free z-fight finding
("base exactly at terrain surface → sink 1–2 cm or raise"), distinct from resting
(COPLANAR < |gap| ≤ GROUND_EPS, fine). This is also the GUIDANCE_FOR_LLMS "exact equality
is a bug, not a coincidence" lesson made mechanical. One nuance: ground-snapped placement
(`place={"ground": true}`) intentionally produces base ≈ surface — the placement verb
should seat with a deliberate epsilon (or auto-declare the intent) so the floor and the
placer don't fight.

Deferred deliberately (not shipped in the G18/G19 pass): the naive third band would fire a
z-fight on EVERY ground-snapped actor, louder than the silence it replaces. Its prerequisite
— a substrate-only ground trace — now exists (G18), but the safe version needs the placer to
seat with a known epsilon (or auto-declare) FIRST, else detector and placer fight. Land the
placer-epsilon convention, then add the band.
### G22 — the "blank" Open World template ships a collidable Landscape at z=0; the surface can't see it as ground, warn about it, or remove it
Status: OPEN (found 2026-07-02, L1 rebuild through the MCP verbs; reattributed B3's root cause)

A fresh Open World level carries 64 `LandscapeStreamingProxy` tiles — a real, collidable
Landscape at z=0 spanning the world. Every ground trace whose true surface lies below z=0
hits it first and returns a legitimate-looking 0.0 (see B3 reattribution). `scene` counts
it among "untracked scaffolding" but nothing says "there is a second ground plane shadowing
your terrain", and no verb can hide/remove engine actors. Workaround used: keep all
authored geometry above z=0 (`transform nudge` the terrain up; min bound was −366 →
+600). Resolution directions: (a) traces prefer/filter-to ueb substrates and warn when the
winning hit is engine scaffolding at exactly z=0; (b) an environment/level verb surfaces
"what grounds exist here" and can neutralize the template Landscape (hide, or opt-in
delete); (c) at minimum the status block should warn when authored terrain dips below an
engine ground.

### G23 — the ueb op log (`history`) outlives the level; reconcile (G16) cleaned the registry but not the log
Status: OPEN (found 2026-07-02, L1 rebuild)

Fresh level `Untitled_2`, `scene reconcile` reports fully clean — yet `history op=list`
still shows op001–op004 from a prior session's test actors (`foll_a`, `d_a`, `d_b`), and
every status block stamped `last_action: op004 nudge d_a` until the first new mutation.
G16 gave the actor registry a level lifecycle; the mutation log needs the same (clear or
namespace the log per level, and `undo_to` must refuse to cross a level boundary).

### G24 — terrain has no lifecycle: `landscape create` refuses an existing label and there is no `landscape remove`
Status: OPEN (found 2026-07-02, L1 rebuild)

Wanted to rebuild the terrain with a different `base_height` (G22 workaround);
`create` errors with "label 'terrain' already exists" and the action set
(create/shape/flatten/describe) has no remove/replace. `shape replace=True` resets
features but can't change size/origin/base. Workaround: `transform nudge` on the terrain
actor (worked — traces follow the moved mesh). Resolution: `landscape remove` (mirror of
`scatter remove` / `path remove`), or let `create` on an existing label mean idempotent
rebuild.

### G25 — the `render:` line prescribes "assign the intended material" but no verb can assign materials
Status: OPEN (found 2026-07-02, L1 rebuild)

After every terrain edit the status block warns: "slot 0 is the engine DEFAULT material
(unassigned — renders as flat grey) → assign the intended material". The advice is
correct and un-followable — no verb touches materials (the KiteDemo pack's terrain-grade
landscape materials sit unusable). The forced-sense loop prescribes an action outside the
verb surface. Resolution: a minimal material-assign facility (e.g. on `landscape`/`add`:
material=<asset>), or stop prescribing what the surface can't do.

### G26 — `landscape describe` model fields don't track the terrain actor's transform
Status: OPEN (found 2026-07-02, L1 rebuild)

After `transform nudge terrain [0,0,600]`, describe's traced `z` is correct
(mesh reality), but `z_model`, `bounds.z`, and `height_range_cm` still report the
un-transformed height function (600 low), so EVERY sample is flagged "diverges" forever
and the flag loses its signal value (it should mean "carved/flattened here", not "the
whole actor moved"). Resolution: compose the actor transform into the model side of
describe (offset z_model/bounds by the actor's world transform).

### G27 — `asset inventory` reports height but not silhouette; "tall" got mistaken for "tree"
Status: OPEN (found 2026-07-02, L1 user playtest — forest read as giant bushes, 1/10)

The compact inventory shows `height_range_cm` only. The agent picked the GV shrub pack's
2–9.7 m plants as forest canopy on height alone; the user's read: "everything read as a
bush" — because they are bushes: no trunk, aspect ratio ≈ 1. The discriminating data
(full x/y dims → height:width ratio; ideally a trunk/canopy hint) exists per-asset in
`describe` but not in the family listing where selection actually happens. Resolution:
surface footprint dims (or height:width ratio) alongside height in inventory families,
so silhouette is derivable at pick time.

### G28 — `scatter` accepts min_spacing far below canopy width → wall-to-wall interpenetration ("ultra clipped")
Status: OPEN (found 2026-07-02, L1 user playtest)

min_spacing_cm=450 with ~500–800 cm-wide plants ⇒ neighbors clip constantly; the user
read the whole stand as clipped geometry. The runtime has (or can lazily measure) each
family's footprint — it should derive a default min_spacing from the widest scattered
family (or warn when the given spacing is below measured canopy width), instead of
trusting a number the agent fabricated without reading widths.

G25 addendum (L1 playtest): the cost is not cosmetic. With no material on the terrain,
the carved path — geometrically correct, verified at grade — was "the tiniest of tiny
lines" to the user. Path legibility at eye level NEEDS a material strip (dirt vs grass),
not just carve geometry; a `path` without a material story is invisible in the render
even when perfect in the mesh.

G23 addendum (post-crash observation): after a full editor PROCESS restart (nvidia-driver
crash), both the registry and the op log came back empty — the phantom state lives in the
editor's in-process Python session, not on disk. So the haunting crosses level changes
within one editor run but not process restarts. The fix scope is narrower than first
thought: clear/namespace the op log on level change, same trigger G16's reconcile uses.

### G29 — no way to remove an asset pack through the surface (KiteDemo, implicated in editor hangs, needed manual deletion)
Status: OPEN (found 2026-07-02; the user fingered KiteDemo's legacy non-Nanite meshes for
"waiting for static meshes" editor hangs and asked for full removal)

Asset curation is half-in half-out of the surface: `asset` can perceive packs
(packs/inventory/describe/whats_new) but can't retire one. Removing KiteDemo meant
closing the editor and deleting `Content/KiteDemo` on NTFS by hand — outside every verb.
Also stale-state hazard: the server's persisted dims cache and registry snapshot still
reference the deleted pack until a `whats_new` rebaseline. Resolution: probably keep
deletion manual (destructive, rare) but make the surface honest about it — `whats_new`
should flag vanished packs and evict their cached dims, and `asset packs` shouldn't
serve a pack that no longer exists on disk.

G29 addendum (verified live after the removal, 2026-07-02): the surface handled the
vanished pack better than feared — `asset packs` reads the live registry (KiteDemo gone
immediately, no stale serving) and `whats_new` reported `removed_roots: ["KiteDemo"]`
and rebaselined cleanly. Remaining unverified: whether the persisted dims cache evicts
the dead pack's entries. Also observed: RockEnv_Pack Texture2D count 20→12 in the same
diff — possibly a boot-time registry-scan race (whats_new ran seconds after editor
launch); watch whether it reverts on a later diff.
