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

### G1 — Undo interleaving desync (design limit, M1)
Status: OPEN (accepted limitation for M1, documented not fixed)

The editor's transaction/undo stack is **shared** with the human's own in-editor edits.
`undo_to(id)` issues N `TRANSACTION UNDO` console commands where N = ops-after-id in our
`_state.history`. That count is only correct while our history is 1:1 with the stack —
a manual edit pushed between our ops shifts the stack and our undo would eat the manual
edit (or stop short). blender-buttons hit the identical class of bug (its gaps.md E1:
history↔undo desync wiped a 27-op build).

M1 mitigation: keep history strictly 1:1 (read-only/nav verbs never log, never push a
transaction). Post-M1: detect external mutation (blender-buttons SPEC-15 interlock) and
refuse to undo across a foreign edit rather than silently eating it.

### G4 — `transform` on a non-centered-pivot foreign actor
Status: OPEN (M1 add only spawns centered-pivot BasicShapes)

Placement/transform math assumes actor location == AABB center (true for BasicShapes).
`set_actor_location` sets the PIVOT, not the bounds center — so nudging/placing a
pre-existing actor whose pivot isn't centered will be off by the pivot→center delta.
Fix when M1's `transform` needs to move imported/foreign actors: read the pivot-to-
bounds-center offset and correct. Ported note from blender-buttons placement.py caveat.

### G5 — `feel distance_between` ANY uses centre-to-centre, not nearest-surface
Status: OPEN (M1 approximation)

blender-buttons' distance_between(axis=ANY) returns true nearest-surface distance via a
BVH query both directions. M1 returns centre-to-centre (labelled as such in the result).
Port the BVH/geometry nearest-surface path when perception depth is needed (M2).

### G8 — Async screenshot never lands when editor is backgrounded
Status: OPEN (M1 partial — camera works, file capture unreliable headless)

`view` correctly positions the orbit camera (`set_level_viewport_camera_info` verified),
but neither `AutomationLibrary.take_high_res_screenshot(...)` nor the `HighResShot`
console command produced a PNG within ~30 s — no file, no subfolder. Both are async and
need the render thread to produce a frame; with the editor unfocused (WSL-driven, window
in background) the viewport isn't rendering, so the write never happens. This is the
exact risk SPEC-00 flagged.

Options to try (in order): (a) server-side poll with a longer timeout while the editor
window is foregrounded — confirm it's purely a background-throttle issue; (b) enable
viewport realtime + `editor_invalidate_viewports()` before the shot; (c) fall back to an
editor viewport client capture / `FViewport::TakeHighResScreenShot`. Server `view` should
poll `screenshot_wsl` with a timeout and return the image if it lands, else the path + a
"capture pending — is the editor foregrounded?" note. The relational build + `feel` +
undo (the exit-test core) are proven independent of this.

### G6 — Undo buffer depth vs blender-buttons E1
Status: OPEN (verify, don't assume)

blender-buttons E1: a shallow (32-step) undo buffer + history↔undo desync wiped a 27-op
build. UE's transaction buffer is byte-sized (default ~32 MB), not step-count, so the
step trap likely doesn't apply — but VERIFY a long M1 build (table = 5 ops, then a
bigger arrangement) undoes fully via repeated `TRANSACTION UNDO` before trusting it.

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
Status: OPEN (palette knowledge for Ryan; E2/E6 adapt)

SPEC-01 expected "32 prebuilt cabin Blueprints" in Modular_Rural_Cabin. Reality (from
`asset packs`/`find`): the 32 Blueprints are modular *pieces* (Wall_*, Roof_*, Porch_*) plus
a few prop BPs (Mailbox, Outhouse, Trash_Bin); the 5 fully-built cabins ship as **World**
assets (level maps), which place via level-instancing, not `spawn_actor_from_class`. So E2's
"spawn one prebuilt cabin Blueprint" is satisfied by a prebuilt one-actor building BP
(Outhouse) — verified spawning as a single ground-snapped actor. For E6, a "prebuilt cabin"
means either level-instancing a cabin World (a new mechanism, not yet a verb) or composing
from modular pieces as E2 did. Flagged for Ryan (asset curation): if whole-cabin BPs are
wanted, they'd need to be authored from the World assets, or a `level-instance` placement
path added behind `add`.

### G8 update — hamlet 3D hero shot still blocked by background throttle (E6)
Status: OPEN (reconfirmed 2026-07-02) — view(map) is the working visual; 3D shot needs foreground

E6's mechanical verification passed end-to-end through the verbs (terrain described, path
carved + queried, cabin relations felt — front↔back 400.0 cm, roof over walls — scatter
counts + a live "no instance within the lane clearance" spot check: nearest tree 990 cm vs a
575 cm clearance). The visual half split as G8 predicts: `view(map)` renders the labelled site
plan reliably (server-side, no async capture), but `view(shot=True)` from path level produced
no PNG — the WSL-driven editor is backgrounded so the viewport never renders a frame. The
camera IS positioned correctly (returned transform is exact), so the 3D "does it read as a
place?" judgement is Ryan's step: foreground the editor (the shot then lands) or walk it in
PIE. The determinism check holds by construction and was verified for its one stochastic part
(scatter: same seed ⇒ identical 801/665/… instance counts on re-run); terrain (pure height
function) and relational placement are deterministic, so rebuilding from the same calls
reproduces the hamlet within tolerance.

### G15 — `landscape describe` reports the feature height-function, not the post-carve/flatten mesh
Status: OPEN (found 2026-07-02, Level 1 dogfood)

`landscape describe` samples the pure-Python height function built from the *feature list*
(`terrain.py`), which is exactly what makes it "agree with world traces" (SPEC-01 E-note) —
**until** a `flatten`/`carve` edits the actual mesh without touching the feature list. After
Level 1's `path carve` flattened the southern trail bed to z=0, `describe` at those points
still reported the pre-carve grade (−825..−269 cm) while a real `trace_ground` returned the
carved surface (flat 0.0). So the two sources of truth that are *supposed* to agree
(describe ⇄ trace) silently diverge post-edit — and `describe` is the one that's now lying,
because it never sees flatten/carve.

Why it matters: `describe` is sold as the honest sampler for planning `along=`/`facing=`
placement and reading grade. If it ignores carve/flatten, an agent plans against a surface
that no longer exists. Fix options: (a) record flatten/carve deltas into the height model so
`describe` composes them, or (b) make `describe` trace the *actual* mesh (authoritative but
slower + subject to the B3 cook race), or (c) at minimum flag in the result that N
flatten/carve edits have been applied since the feature list and describe may be stale.
Relates to B3 (the bad drape is what carve baked in) — fixing B3 removes the *wrong* carve,
but describe-vs-mesh divergence remains for any legitimate carve.

### G16 — no level lifecycle verb; ueb `_state` outlives the level (stale scatters/paths persist across a level change)
Status: OPEN (found 2026-07-02; ties to the "scene controls" question — load/save/new/clear)

Driving Level 1 in a fresh `Untitled_2` level, `view(map)` reported **2 paths / 4 scatters**
when only 1 of each had been created this session. Cause: runtime `_state` (scatters, paths,
history) lives in the editor Python process, **not** in the level — so the prior hamlet
session's `trees`/`undergrowth`/`rocks` scatters and `lane` path were still in `_state` after
the editor had been pointed at a different level, where none of their actors exist. `scene`
correctly showed 0 ueb actors (state and reality had drifted apart); map/describe trusted the
stale state. Removing the ghosts by hand (`scatter remove`, `path remove`) all returned
`components_cleared: 0` — confirming pure state ghosts, no geometry.

The surface has **no level lifecycle at all**: no new / open / load / save / clear verb
(`LevelEditorSubsystem` + `EditorLoadingAndSavingUtils` *are* scriptable in 5.8, unlike
Landscape). Two things wanted: (1) a `level` verb (or `scene(action=new|open|save)`) with a
dirty-check guard so it can't silently discard unsaved work, and — for the WP template
question — clone the WP map rather than start a non-WP blank; (2) reconcile `_state` against
the actual level on a level change (drop or flag entries whose actors/foliage are absent), so
perception never trusts ghosts. Until then: a session building in a fresh level inherits the
previous session's phantom populations. Workaround used for Level 1: explicit `remove` of each
stale label before trusting the map.

### G17 — auto-follow camera: snap the viewport to whatever the agent just mutated (toggleable)
Status: OPEN (requested by Ryan 2026-07-02 — "I never want to guess what the agent is doing")

The human watches the live editor viewport, but nothing moves the camera to where the
agent is working — a build far from the current view is invisible until someone flies
over. Wanted: after every mutating verb, aim the viewport at what was touched,
automatically, so the human always sees the agent's hands.

This is small, not a spec — the design fits here:

- **One call site, not N.** Every mutating verb already flows through the shared
  dispatch/status path, which already computes the touched bounds to report them. Hook
  there: `if follow and mutated: frame_bounds(touched_bounds)`. No per-verb changes.
- **One helper.** `frame_bounds(bounds)`: camera at a distance sized by the bounds
  radius (fit with margin), ~30–40° pitch down, aimed at the center — via
  `set_level_viewport_camera_info`, already live-verified working (G8: positioning
  works; only async *file capture* needs foreground, and a watching human means
  foreground anyway).
- **Group/region ops frame the group.** scatter/landscape/path touch a region, not an
  actor — frame the population/edit-region bounds (already known to the verb), never a
  single instance.
- **Toggle, default ON.** Runtime flag exposed as `view(action="follow",
  enabled=true|false)`. Ryan's default is watching; OFF is for when the human is
  flying the viewport themselves (the camera is shared — follow fights manual
  navigation by design; that's the feature, the toggle is the escape).
- **Honesty convention:** when disabled, the status block says `follow: OFF` — same
  pattern as `validate: OFF` — so the agent knows the human may be flying blind.
- **Never enters history.** The camera move is perception-side: no `ueb:` transaction,
  not logged, `undoable` untouched. A camera nudge must never shift the shared undo
  stack (G1).

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

---

### G22 — adding a new reloadable module needs an editor restart to fully take effect
Status: OPEN (accepted dev-loop limitation; documented — the workaround is cheap)

`dispatch` hot-reloads the modules in `_RELOADABLE`, but that list is built in `__init__.py`
— the one module hot-reload deliberately NEVER re-execs (it also holds the `from . import
render` line). So when a brand-new module is added to the package (SPEC-03's `render.py`),
a *running* editor session's `_RELOADABLE` is stale: it doesn't list the newcomer, and
`__init__` won't re-run to pick it up without a restart.

Symptom seen live (2026-07-02, landing SPEC-03): the first `validate op=run` after syncing
`render.py` returned WITHOUT the new `[N excluded]` slot, even though the code was correct —
a first-dispatch transient. A forced `importlib.reload(render); importlib.reload(validate)`
in a probe, then the identical dispatch, produced the expected `[1 excluded]`. Nothing was
wrong with the code; the running session just hadn't threaded the newcomer through its
(never-reloaded) reload list yet.

Workaround (cheap, no restart): after syncing a NEW module, force-reload it once from a
probe (`importlib.reload(<mod>)` for the new module + every reloadable importer of it), or
just restart the editor. Editing an EXISTING reloadable module is unaffected — this only
bites the first time a module is *introduced*. Not worth engineering around (a startup-time
`__init__` already lists it correctly for every subsequent session); worth remembering so
the next new-module landing doesn't read a first-call transient as a bug.
