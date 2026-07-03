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

### G30 — no job/progress pattern for slow mutations: one pathological asset load can still outrun the HTTP timeout
Status: OPEN (successor to B6, 2026-07-02 — the two concrete offenders are fixed, the general pattern isn't built)

B6's fixes hold: `path carve` batches its flatten features into ONE mesh rebuild (38-disc
carve round-trips in <0.5 s, was ~30 s dark), and `asset inventory measure=True` bounds each
batch by wall-clock (`seconds=`, default 20 s) as well as count. But the wall-clock check
runs BETWEEN mesh loads — a single cold Nanite mesh whose first load takes >60 s would still
wedge the bridge, and any future long game-thread verb inherits the same trap. The general
cure is an async job + progress pattern (kick the work off the dispatch path, poll a
`job_status`), or per-verb chunking as each new slow path appears. Until then: after any
timeout, poll `/remote/info` and RE-READ state before re-issuing — timed-out work usually
completed invisibly.

### G31 — scatter family resolution over-matches across packs
Status: OPEN (found 2026-07-02, L1 replay)

`scatter meshes=["Rock"]` silently matched 48 variants across TWO packs
(Rock_Collection_04's 7 measured rocks + 41 unmeasured RockEnv_Pack meshes → 46
FoliageTypes, most dims-blind, scale-jittered). `add` errors on ambiguous short names
with candidates; scatter family matching should be as honest — error (or at least warn
with pack attribution) when a family name resolves across multiple packs, and accept a
`pack=` scope. Workaround used: pass explicit variant names.

### G32 — material suitability is invisible to the verbs (and no way to author one on-surface)
Status: OPEN (found 2026-07-02, L1 replay — cost 3 render/probe round-trips)

Assigning a terrain material is now one param — but nothing tells the agent whether a
material CAN work on a mesh surface. Three traps hit in one session: a foliage-card
masked master (Grass_Patch_1) renders as default checkerboard on the terrain; a
vertex-color-blend diorama material (Diorama_Ground) renders as a MIRROR (its no-vertex-
color layer is pond water); both pass `feel render_state`'s `materialised: ok` (the link
only checks non-null slots). And when no suitable ground material existed in the palette,
the fix (author `MI_UEB_Grass`: MIC of MM_Basic + the pack's Grass_* tiling textures,
tuned Roughness/Normal Power) had to be done with raw editor Python — off the verb
surface. Wants: (a) `asset describe` on a material reports domain/blend/master +
a usability hint; (b) render_state's materialised link flags decal-domain/default-
fallback; (c) a minimal `asset` action to instance a master material with texture/scalar
params. Note: `MaterialEditingLibrary.set_material_instance_*` setters return False even
on success in 5.8 — read back `texture_parameter_values` to verify. Addendum (the tree-motion hunt): material MOTION is
just as invisible as material suitability — the cabin pack's tree masters carry a
hardcoded diorama bob (whole-mesh vertical WPO, no exposed parameter), and the PV
plugin's MA_Foliage_Trees master deforms wildly on static bakes (its WPO expects PV
data) — three escalating user reports before the cause was found, and no mechanical
read can see WPO at all (collision never moves). A material vet should also report
"has WPO / parented outside /Game" as a warning.

### G33 — terrain has no UV-tiling control: near-field ground texture smears
Status: OPEN (found 2026-07-02, L1 replay)

The DynamicMesh terrain's UVs stretch a tiling ground texture (2 m-ish textures over a
300 m mesh) — at eye level the ground reads as smeared/blurry watercolor; roughness sheen
amplified it into a wet look until the material's Normal/Roughness Power were tuned down.
`landscape` wants a `uv_tile_cm=` (target texel density) applied when the mesh is built,
so a tiling material renders at its authored scale.

### G34 — path surface ribbon: terrain pokes through between samples
Status: OPEN (found 2026-07-02, L1 replay — cosmetic, one spot in 274 m)

The strip drapes vertex pairs every ~175 cm with lift=3 cm; a terrain bump cresting
between two sample rows can pierce the ribbon (one green patch mid-trail in the L1
shots). Cheap fixes: sample the max of several traces per across-segment, or default
lift a bit higher (5–8 cm), or subdivide where the longitudinal slope changes fastest.

### G35 — no verb can place a PlayerStart: an authored scene always needs one
Status: OPEN (found 2026-07-02, L1 replay — the user asked for player insertion at the trailhead)

Every authored scene ends at the same question: "where does the player drop in?" The
surface has no answer — `add` spawns primitives and StaticMesh/Blueprint assets only;
gameplay/engine actors (PlayerStart first among them) can't be placed, perceived, or
relocated through the verbs. The L1 trailhead insertion was done with raw editor Python
(relocate the Open World template's PlayerStart, seat at traced grade + 92 cm capsule
half-height, yaw = trail start bearing). Wants: a first-class way to say "insert the
player HERE facing THAT" with the usual relational/polar/path vocabulary (e.g.
`add(what="player_start", place={"along": {"path": "trail", "fraction": 0}},
facing=...)` or a small `scene`/`add` sibling), ground-seated by trace like any
placement, and visible to `scene`/`feel`/`view(map)` as a marker. Note the template
level already ships one PlayerStart — creating a second silently wins/loses by
priority; the verb should relocate-or-create, not blindly spawn.

### G36 — `new_level_from_template` (Open World) yields always-loaded actors that never load in PIE
Status: OPEN (found 2026-07-02, chasing the L1 black-screen-on-Play)

A level created with `LevelEditorSubsystem.new_level_from_template(..., "/Engine/Maps/
Templates/OpenWorld")` LOOKS right in the editor but is broken at game time: every
template-copied actor with `is_spatially_loaded=False` (DirectionalLight, SkyLight,
SkyAtmosphere, VolumetricCloud, ExponentialHeightFog, PlayerStart, SM_SkySphere) is
ABSENT from the PIE world — Play renders an unlit void ("black screen") and the pawn
spawns at world origin, under any authored terrain. Spatially-loaded actors (proxies,
ueb DynamicMeshes, foliage) stream fine; dirty+resave does NOT heal the stale
descriptors; freshly spawned always-loaded actors work perfectly. Cure applied to
UEB_L1_Valley: delete the template set, respawn sun/sky_light (real-time capture)/
sky_atmosphere/clouds/height_fog/player_start fresh. Wants: (a) whatever verb/script
creates a level must do the replace-env-set dance (or build from an empty WP map);
(b) `scene op=streaming` (or a new game-truth check) should flag always-loaded actors
whose descriptors won't resolve at runtime — the editor view and the PIE view of the
same map disagreed completely and every editor-side read said "fine". Diagnosis
pattern that worked: `editor_request_begin_play` + census the game world via
`GameplayStatics.get_all_actors_of_class`, compare against the editor world.
