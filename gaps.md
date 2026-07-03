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
