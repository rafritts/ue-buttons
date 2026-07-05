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

### G30 — no job/progress pattern for slow mutations: one pathological asset load can still outrun the HTTP timeout
Status: OPEN (successor to B6, 2026-07-02 — the two concrete offenders are fixed, the
general pattern isn't built. Reviewed 2026-07-03: deliberately deferred again — the
remaining wedge is a SINGLE atomic game-thread asset load, which even a tick-based job
can't chunk (the next dispatch would stall behind it on the game thread anyway); build
the async job + progress pattern when a new concrete offender appears to shape it,
not speculatively.)

B6's fixes hold: `terrain op=carve` batches its flatten features into ONE mesh rebuild (38-disc
carve round-trips in <0.5 s, was ~30 s dark), and `asset inventory measure=True` bounds each
batch by wall-clock (`seconds=`, default 20 s) as well as count. But the wall-clock check
runs BETWEEN mesh loads — a single cold Nanite mesh whose first load takes >60 s would still
wedge the bridge, and any future long game-thread verb inherits the same trap. The general
cure is an async job + progress pattern (kick the work off the dispatch path, poll a
`job_status`), or per-verb chunking as each new slow path appears. Until then: after any
timeout, poll `/remote/info` and RE-READ state before re-issuing — timed-out work usually
completed invisibly.

### G50 — no lighting surface: a cave interior is pitch black and the agent can't even say so
Status: OPEN (found 2026-07-04, L2 dogfood — predicted verbatim by the level brief)

The L2 cabin sits inside a sealed rock chamber lit only by what bounces through a 5 m
mouth. The verb surface has no way to author a light (the template sun/skylight are the
only sources, and they're outside), and no way to *perceive* darkness (perception is all
geometry — nothing reads luminance at a point). Two gaps in one: an authoring verb
(`add what=point_light` family or a `light` verb — SPEC-worthy, UE owns the word Light)
and a numeric light-level sense to make "it's too dark in here" a measurable finding
instead of a human complaint. PIE-tier check candidate for SPEC-09.

### G54 — foliage paint mints FoliageType assets into a shared folder; a label reused across levels raises a blocking "overwrite?" modal that stalls the headless build
Status: OPEN (found 2026-07-04, plain-forest dogfood — the user had to click "Yes" on two
editor modals mid-paint for the build to proceed)

`_foliage_type_for` (runtime/ue_buttons/foliage.py:312) mints each stand's
`FoliageType_InstancedStaticMesh` at a level-agnostic path `/Game/UEB_Foliage/FT_<label>__<idx>`.
It calls `EditorAssetLibrary.delete_asset` first to recreate fresh — but when the label
reuses a name from a PREVIOUSLY-SAVED level (this build's `canopy`/`grass` collided with
L1/L2's `FT_canopy`/`FT_grass`, still referenced by those saved maps), the delete is
refused (asset in use) and `AssetTools.create_asset` then throws the editor's blocking
"<asset> already exists — do you want to overwrite?" modal dialog. A headless agent can't
see or answer it; the whole paint hangs until a human clicks Yes. Silent to the MCP layer —
the paint call just blocks. Real capability wedge: any second level that reuses a stand
label (canopy/grass/understory are the obvious defaults) trips it.

Fix direction (pick one, none applied yet): (a) namespace the FoliageType asset by level —
`FT_<levelname>_<label>__idx` — so names never collide across maps (also touches the remove
prefix at foliage.py:617); or (b) when `delete_asset` can't remove an in-use asset, fall
through to a unique minted name (`FT_<label>__<idx>_<n>`) instead of letting create_asset
prompt; or (c) drive create_asset through a path that passes bAllowOverwrite / suppresses
the modal. (a) is cleanest — a stand belongs to its level. HATEOAS next once built:
foliage paint should report the minted FoliageType path so a collision is legible, not a
silent block.

### G55 — add what=player_start seats the capsule ~36cm high (grounds on the arrow-widget AABB, not the capsule)
Status: OPEN (found 2026-07-04, plain-forest dogfood)

`add what=player_start place.at=[0,0]` reported `relocated` and "seat the capsule on the
traced ground," but the very next auto-lint flagged `player_start floats 36.5cm above ground
(base z=83.2, ground z=46.7)`. The relocate put the actor centre at z≈175 = ground + ~128,
but the PlayerStart's capsule base sits at z=83.2 (≈92 below centre) — the seating math used
the actor's full AABB half-height (which includes the upward-pointing direction-arrow
billboard, ~256 tall) instead of the collision capsule, leaving a ~36cm float. Cosmetically
harmless (the pawn drops on spawn) but it's a self-inconsistency: the verb claims a seated
capsule and its own floor-lint immediately contradicts it, forcing a manual `transform move`
to clear the finding. Fix: ground player_start on its CapsuleComponent extent, not the
merged actor bounds.
