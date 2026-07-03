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
