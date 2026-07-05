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

### G56 — foliage paint accepts a tree whose leaf material needs the Procedural-Vegetation runtime; it renders bare ("dead trees") with no refusal
Status: OPEN (found 2026-07-04, plain-forest dogfood — the user's #1 complaint: "most of the
trees are dead, literally no leaves")

The whole `/Game/UEB_Trees` set (Hornbeam/Norway-Spruce/Silver-Birch, SM_ exports of
Megaplant_Library) has a `..._Foliage` material slot whose master is
`/ProceduralVegetationEditor/SampleAssets/Materials/MasterMaterials/MA_Foliage_Trees` — a
plugin master outside /Game carrying Season/Health/Translucency params that expect
per-vertex runtime data the plain StaticMesh never supplies. On instanced foliage the leaf
cards render invisible/bare, so a full canopy reads as dead winter branches. `asset
op=describe` on the material DOES warn ("master lives outside /Game … engine/plugin
materials often expect runtime data this mesh won't have"), but nothing hoists that into the
paint path: `foliage op=paint` planted 793 of them with only a motion note, no refusal.
Contrast R1/G40, which refuses on WPO. Fix: a paint-time rule (call it R-leaf) that refuses
(force-overridable) when a scattered mesh's material master lives outside /Game under a known
runtime-dependent plugin (ProceduralVegetation, etc.) — "these will render bare as static
foliage; use a self-contained /Game foliage material." Known-good source discovered this
session: `/Game/Modular_Rural_Cabin/Meshes/Foliage/SM_Pine_Tree_0[1-5]` (master MM_Tree_Branches,
masked_wind, self-contained) — same proven pack as the grass/logs.

### G57 — terrain accepts a BLEND_MASKED surface material; the cutout punches see-through holes ("ground clipping through the floor")
Status: OPEN (found 2026-07-04, plain-forest dogfood — the user's #2 complaint)

`terrain op=create material=MI_UEB_Grass` took a material whose blend_mode is BLEND_MASKED
(a grass-blade cutout) and applied it as the terrain surface. A masked material on a solid
ground mesh renders opaque only where the alpha mask passes — everywhere else is a hole you
see straight through to the void, which reads exactly as "the ground is clipping through the
floor." `MI_UEB_Grass` is a trap precisely because it's the material named "Grass" an agent
reaches for as a forest floor.

SECOND trap, same gap (found next pass): the "obvious" opaque replacement `Diorama_Ground`
(MM_Vertex_Color_Blend) is opaque but carries a WATER feature (`Water Darkness` scalar +
low-roughness wet layer); on the terrain with uniform vertex color it rendered the WHOLE
floor as a reflective flat sheen — the user read it as "the forest floor is underwater." So
BLEND_OPAQUE is necessary but not sufficient. Fix: `terrain op=create/shape` should vet the
material and warn on (i) non-opaque blend AND (ii) very-low-roughness / water-ish surfaces
that read as wet — a matte ground wants high roughness. Actually-good floor built this
session: `/Game/UEB_Materials/MI_UEB_ForestFloor` (MM_Vertex_Color_Blend, `Water Darkness`=0,
Rougness 1/2/3 ≈0.9–0.95, tiling `Grass_/Ground_Dirt_/Rocky_Ground_` basecolor+DET textures
from Modular_Rural_Cabin/Textures/Tiling). High roughness is the real cure for the sheen.

### G58 — no verb-surface way to neutralise an instanced-foliage WPO offender; the fix needs a master-graph edit via raw probe.sh Python
Status: OPEN (found 2026-07-04, plain-forest dogfood; the pines' motion is now correctly
fixed via the workaround below)

R1/G40 correctly refuses the pine as instanced foliage. Diagnosis pinned the offender
precisely: the pine's TWO slots split cleanly — `MI_Pine_Tree_Branches` (master
MM_Tree_Branches) is `masked_wind`, per-instance SAFE (leaves sway correctly, exposes
`Wind Intesity`/`Wind Weight` scalars); the rigid float is entirely `MI_Pine_Tree_Bark`
(master **MM_Tree_Trunk**), whose WPO is `pivot_wpo` (ObjectRadius/TransformPosition
object-space → whole instance translates). Key trap: MM_Tree_Trunk's WPO is HARDWIRED in
the master graph — the bark instance exposes only `Color Multiply`/`Roughness`, NO wind
scalar — so no MaterialInstance parameter can disable it, and a MIC override can't either
(same master). (My first attempt zeroed the BRANCH wind, which was the wrong target: it
killed the good leaf sway and left the trunk float untouched.)

ATTEMPT 1 (did NOT work at render time): overrode MM_Tree_Trunk's WorldPositionOffset output
with a Constant3Vector(0,0,0) via `MaterialEditingLibrary.create_material_expression` +
`connect_material_property(..., MP_WORLD_POSITION_OFFSET)` + `recompile_material` + save, and
restored branch wind. `validate scope=pines` went clean and the motion verdict dropped
pivot_wpo→wpo(constant) — but the USER STILL SAW MASSIVE FLOAT. Lesson: a master-graph WPO
override (even with use_material_attributes=False) did not propagate to the already-placed
instanced-foliage components' rendered shader — the static analyzer was satisfied while the
runtime kept the old motion. Do not trust a master WPO edit to fix placed foliage; and note
the analyzer now UNDER-reports (says constant) while the render still moved.

ATTEMPT 2 (reliable, applied): set `world_position_offset_disable_distance = 1` on every pine
foliage component (40 HISM comps across 8 IFAs) AND persisted it on the 5 `FT_pines__*`
FoliageType assets. Semantics: WPO is disabled for instances beyond 1 cm from camera ⇒
effectively always disabled ⇒ trees render planted, no float. This is the deterministic kill.
Downside: it disables ALL WPO on the component, so the (safe) branch masked-wind sway dies too
— the pines are now fully STATIC. Acceptable (no-float was the priority) but sway is lost.

Two sub-gaps this exposed:
  • The verb surface has no way to set `world_position_offset_disable_distance` — the reliable
    knob — so this needed raw probe.sh Python. Real fix: `foliage op=paint rules.wind:"off"`
    should set it on the minted FoliageType (and repaint applies it to components). That's the
    clean, deterministic on-surface fix — simpler than minting WPO-neutered material variants.
  • The motion census reads the MATERIAL GRAPH, not the component's disable_distance, so after
    the WPO kill it still false-positives "886 instances MOVE (unmasked WPO)". The census
    should factor in `world_position_offset_disable_distance` before claiming a stand moves.

### G59 — foliage op=remove leaves an empty FoliageType registration that reconcile keeps reporting as untracked
Status: OPEN (minor; found 2026-07-04, plain-forest dogfood)

After `foliage op=remove label=canopy` (and understory), `outliner op=reconcile` kept listing
`canopy`/`understory` as `untracked, 0 instances` even across repeated removes — the instances
and components are gone but an empty FoliageType/tag registration lingers in the IFA's
used-types list, so the diff never goes fully clean. Harmless (nothing renders) but it means
reconcile can't report a truly empty "0 untracked" after a legitimate stand replacement. Fix:
`op=remove` should also drop the now-unused FoliageType from the IFA (and/or delete the
FT_<label>__* asset when no instances remain).
