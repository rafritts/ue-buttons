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

### G39 — WPO/wind is invisible at author time: the vet misses plugin-master displacement, and scatter/add never surface WPO at all → whole-mesh-bobbing foliage scatters silently
Status: OPEN (found 2026-07-03; the user caught it visually in PIE — "the wind makes the
whole tree sway up and down, trunk and all… they're all Spruce").

What happened: L1's understory scattered ~20k Megaplant `Branch_*` instances (Norway Spruce,
Goat Willow, European Spindle). Their foliage MI's master is the ProceduralVegetation plugin
material `/ProceduralVegetationEditor/.../MA_Foliage_Trees` (OUTSIDE /Game), whose vertex
displacement (`Displacement Power`, `Reduce Branch Displacement`) expects PV-runtime vertex
data the scattered static-mesh instance doesn't carry. Result: the wind WPO displaces the
WHOLE mesh — the trunk bobs vertically instead of the needles swaying. Correct-by-contrast:
the pines (`MI_Pine_Tree_Branches` → /Game `MM_Tree_Branches`) and cabin bushes
(`Bush_1` → /Game `MM_Foliage`) use `Wind Weight` VERTEX-MASKED wind — base anchored, leaves
sway — and look right.

Two blind spots stacked:
  1. The material vet (`asset describe`) reports `has_world_position_offset: true` for the
     /Game foliage masters (caught the pine + Bush_1 WPO correctly) but does NOT set it for
     the plugin master `MA_Foliage_Trees` — only a soft "master lives outside /Game" note,
     even though that master's params (`Displacement Power`/`Reduce Branch Displacement`) are
     literally WPO. So the one material that bobs WORST is the one the WPO flag misses.
  2. Even where WPO *is* detected, neither `scatter` nor `add` SURFACES it — you only see it
     if you manually `asset describe` the material first. So a population of 20k bobbing
     instances was authored with zero warning; the status/`render:` lines said DRAWS and
     moved on.

Fix candidates: (a) WPO detection follows plugin/engine masters too, or treats an
outside-/Game foliage master carrying displacement params as WPO-positive; (b) `scatter`/`add`
echo a one-line WPO/animation notice for the chosen mesh(es) at author time — and distinguish
MASKED wind (`Wind Weight`, base-anchored, fine) from UNMASKED plugin displacement (needs
runtime data → whole-mesh bob); (c) a `feel`/status tell for "this population animates."
Workaround for L1: rebuilt the understory from cabin `Bush_1`/`Bush_Tree` (MM_Foliage,
masked wind), which sway correctly. Megaplant `Branch_*` are unsafe to scatter as plain
instances until the PV-runtime data or a wind-free MI is supplied.

### G38 — `asset inventory`'s aspect "silhouette tell" has no upper bound: a very-thin, low-tri mesh reads as a full tree but renders as a bare spire
Status: OPEN (found 2026-07-03 building L1; cost a forest rebuild).

What/why: the inventory doc teaches the aspect_h_over_w tell as "aspect ≈1 reads as a
bush/blob; a trunk-and-canopy tree runs well above 1 — don't pick forest species on height
alone." Building L1 I picked `Pine_Tree` and weighted the forest toward the TALLEST variant
`SM_Pine_Tree_04` (height 1683 cm, aspect 5.1) — exactly what "tall + high aspect" tells you
to prefer. In the viewport it renders as a near-BARE 16 m pole: a thin trunk with a wisp of
needles at the very top (confirmed by spawning it solo and orbiting close). Its siblings
`SM_Pine_Tree_01` (aspect 1.8) and `_03` (aspect 1.9) render as full leafy pines. The whole
scattered forest (weighted to `_04`/`_02`, the two thin ones) read as sparse invisible poles
from the path — the trees cast tree-shaped shadows but the bodies barely draw.

The tell as written is monotonic ("higher aspect = more tree-like"), but it peaks: past
~3 an aspect-N conifer is a sparse SPIRE/snag, not a fuller tree, and the mesh's tri count
corroborates it (`_04` = 3183 tris over 16.8 m; the leafy `_01` = 9313 tris over 13 m — a
~4× tris-per-metre difference). Both numbers were in `inventory`/`describe`; nothing
synthesised or flagged them.

Fix candidates: (a) inventory flags a canopy-sparsity tell when aspect is very high AND
tris-per-height is low ("sparse spire / likely bare — verify before scattering"); (b) the
doc string caps the aspect heuristic ("aspect ≳3 = thin spire/snag, not a fuller tree");
(c) a cheap "foliage vs bark" material-slot-area ratio as a fullness proxy. Workaround:
eyeball every candidate tree solo (spawn + orbit) before committing a scatter — which is
what the perception surface is supposed to spare you.

### G37 — a ueb terrain that dips below z=0 lets the engine template Landscape render through it, with no warning
Status: OPEN (found 2026-07-03 building L1). Cosmetic-but-glaring: silent in every read,
loud in every screenshot.

What/why: `landscape create` defaults `base_height=0`; I then `shape`d a valley whose
noise floor dips to −827 cm (height_range [−827, 13591]). Ground TRACES correctly ignore
the 129 engine template Landscape actors at z≈0 (scatter/path/drape all sat on my mesh),
so every `feel`/`describe`/status read looked clean. But the template Landscape still
RENDERS: wherever my terrain surface is below z=0, the flat z=0 checker plane sits above
it and shows through as grey checkered sheets across the valley floor (confirmed in an
eye-level orbit shot — big checker patches exactly where the floor bowls under 0).

The landscape doc string already knows this trap ("base_height is still the cleaner way
to keep geometry clear of the template plane") but nothing ENFORCES or WARNS it: neither
`create` (base_height=0 + a valley feature is a foreseeable sub-zero combo) nor `shape`
(which computes height_range and could see min < 0) flags it. The render-legibility floor
(SPEC-03) checks actor draw-gating but not "your ground is occluded by the template."

PRIMARY FIX (a capability gap, confirmed by testing the workaround): there is NO verb to
hide/remove the engine template Landscape actors. Raising base_height only MOVES the
artifact — at base_height=0 the template pokes UP through sub-zero floor dips; at
base_height=1500 (deepest dip cleared) the terrain becomes a raised island and the SAME
template plane is now visible BELOW/BEYOND the terrain's 300 m edge, with a ~16 m cliff
at the border — glaring from any aerial/edge angle (confirmed in a 3/4 orbit shot). So
base_height is a partial workaround that only helps at eye level where the valley walls
occlude the surround. A clean map from all angles needs the template Landscape actually
hidden. Traces already ignore it (guidance says so); the render and the map do not. So:
  (a) [PRIMARY] give the surface a way to hide/destroy the engine template Landscape
      while a ueb terrain is live (or auto-hide it on `landscape create`), since traces
      already treat the ueb terrain as the ground — the template is pure visual noise.
  (b) `shape`/`create` warn when height_range min < ~0 while the template exists
      ("dips below the z=0 template; raise base_height ≥ {abs(min)+margin}") — catches the
      show-THROUGH case, but NOT the raised-island edge case, so it's secondary.
Workaround used for L1: base_height above the deepest dip (clean at eye level / play
perspective, template visible only from high aerials). No script was used — hiding the
template through the surface is simply not expressible today.

### G30 — no job/progress pattern for slow mutations: one pathological asset load can still outrun the HTTP timeout
Status: OPEN (successor to B6, 2026-07-02 — the two concrete offenders are fixed, the
general pattern isn't built. Reviewed 2026-07-03: deliberately deferred again — the
remaining wedge is a SINGLE atomic game-thread asset load, which even a tick-based job
can't chunk (the next dispatch would stall behind it on the game thread anyway); build
the async job + progress pattern when a new concrete offender appears to shape it,
not speculatively.)

B6's fixes hold: `path carve` batches its flatten features into ONE mesh rebuild (38-disc
carve round-trips in <0.5 s, was ~30 s dark), and `asset inventory measure=True` bounds each
batch by wall-clock (`seconds=`, default 20 s) as well as count. But the wall-clock check
runs BETWEEN mesh loads — a single cold Nanite mesh whose first load takes >60 s would still
wedge the bridge, and any future long game-thread verb inherits the same trap. The general
cure is an async job + progress pattern (kick the work off the dispatch path, poll a
`job_status`), or per-verb chunking as each new slow path appears. Until then: after any
timeout, poll `/remote/info` and RE-READ state before re-issuing — timed-out work usually
completed invisibly.
