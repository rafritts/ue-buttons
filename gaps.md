# gaps.md — ue-buttons

Every friction point the agent hits while driving UE becomes a numbered gap here.
Ported discipline from blender-buttons: a gap is **fixed and live-verified against the
running editor before it is cleared** (checked box). "Verified" means the fix was
exercised over the RC bridge and the log/screenshot/`feel` confirms the new behavior —
not that it compiles. Keep the reasoning, not just the diff.

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

### G2 — `get_actor_bounds` on non-spatial actors returns zero AABB
Status: OPEN (cosmetic; handle in `scene`/`feel`)

`WorldDataLayers` and similar management actors report origin/extent = 0. `scene` and
`feel` should filter to actors with a real spatial footprint (has RootComponent w/
geometry) so the tree isn't polluted and `feel` never divides by a zero extent.

### G3 — Deprecated world getter
Status: OPEN (trivial)

`EditorLevelLibrary.get_editor_world()` warns deprecated in 5.8. Use
`unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()`
everywhere in `_ue.py`. Tracked so no deprecated call sneaks into the runtime.

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

### G7 — Perception drowns in engine scaffolding (Open World template)
Status: FIXED 2026-07-02 (live-verified) — tag-scoping

First live `feel describe` reported `table_top` "rests_on" three `WorldPartitionHLOD`
proxies: the default map is Open World, so ~135 `LandscapeStreamingProxy` /
`WorldPartitionHLOD` actors have real, sprawling AABBs crossing z≈0. blender-buttons
never had this — its scene was essentially all agent-created. The zero-extent filter
(G2) doesn't catch them (they have real bounds).

Fix: `_ue.spawn_basic_shape` tags every spawn `ueb`; `scene` and `feel` scope to
ueb-tagged actors by default (with an `include_all` escape hatch), reporting the count
of untracked actors so the scaffolding is acknowledged, not hidden. Tags live on the
actor (survive editor restart, unlike an in-memory registry). Verified: after the fix,
`feel table_top` in an arrangement reports relations only to other ueb parts.

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

### G9 — `asset inventory` full-pack measurement blocks the bridge; payload too heavy
Status: FIXED 2026-07-02 (live-verified) — lazy measurement + disk cache + compact return

First `inventory` of Megaplant (381 static meshes) loaded every mesh synchronously in one
RC call to read bounds/pivot. Two problems, both observed live:
- **Blocks the bridge for minutes.** RC serialises calls; the load ran >120 s, so every
  other verb queued behind it and timed out. "Acceptable once" (SPEC-01) is true for the
  *work*, but not when it's one un-interruptible RC call — the editor kept churning after
  the HTTP client gave up.
- **94 KB return.** Full per-variant dicts × 381 meshes is far past "keep per-asset dicts
  small; let describe carry the detail" (SPEC-01). Too heavy to hand an agent.

Fix (three parts):
- **Disk-persistent dims cache** (`Saved/ueb_dims_cache.json`): measured dims survive
  editor restart, so the load cost is paid once *ever*, not once per session. Loaded lazily
  into `_state.dims_cache` on first use; re-measurement re-invalidated by `whats_new`.
- **Lazy, bounded measurement.** `inventory` is registry-cheap by default: families +
  variant names + tris + Nanite come free from the registry (no load); dims/pivot are
  filled from cache where present, `null` otherwise. `inventory(measure=true, budget=N)`
  measures up to N *uncached* meshes this call (default 60 ≈ well under the RC timeout),
  persists, and returns `{measured, remaining, complete}` so repeated calls converge
  without ever blocking. `describe`/`inventory(family=…)` measure just the few they touch.
- **Compact return.** Top-level `inventory` returns one compact dict per family
  (count, variant names, height/dims range, pivot, Nanite); `inventory(family=…)` drills
  into full per-variant detail. Payload for all of Megaplant drops from 94 KB to a few KB.

Verified: cold `inventory` returns instantly with dims=null flags; `measure=true` warms
~60/call and reports progress; warmed re-inventory is 0.04 s; cache reload survives a
runtime hot-reload (dims_cache lives in the never-reloaded `_state`).

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

### G12 — Landscape Python surface is unscriptable in 5.8; terrain is a GeometryScript mesh
Status: FIXED 2026-07-02 (spike + live-verified) — escape hatch taken, per SPEC-01

SPEC-01 flagged `landscape` as highest-API-risk and told me to spike before building. The
spike found the real landscape path is not viable from 5.8 Python:
- **No landscape-creation factory.** `LandscapeImportHelper`, `LandscapeSubsystem`,
  `NewLandscapeParameters`, `LandscapeEditorObject` are all absent from the Python API. You
  cannot instantiate/initialise a blank Landscape's components from script.
- **Height import is render-target-only.** `LandscapeProxy.landscape_import_heightmap_from_
  render_target` needs an *existing* landscape and a GPU render target; there's no file/PNG
  import (the helper class is gone) and no CPU per-pixel RT fill.
- **No numpy.** SPEC-01 assumed "numpy is available in UE's Python — use it." It is NOT.
  All heightfield math must be pure Python (or computed server-side).

Decision (SPEC-01's documented escape hatch): terrain is a **DynamicMesh** built with
Geometry Script — `append_rectangle_xy` (subdivided grid) → `apply_displace_from_per_
vertex_vectors` (heights computed by a pure-Python `height_at(x,y)`) → complex collision on
the DynamicMeshComponent. Live-verified: an 80×80 valley mesh traces at exactly the computed
height (edge z=3840.3 vs computed 3840.0). Consequences, accepted for the hamlet: no
landscape-material layer blending and no landscape foliage painting — but scatter is HISM
(not foliage painting) and ground-conform is a world trace (works on any collidable mesh),
so neither blocks E4/E5/E6. Because the SAME `height_at` drives the mesh, `describe`
sampling, and `view(map)`, they agree with traces by construction. Revisit if the full
valley later needs real landscape materials (a rung-1 problem, not a hamlet one).

### G13 — no editor SplineComponent from Python; path is a pure-Python spline
Status: FIXED 2026-07-02 (live-verified) — Catmull-Rom over stored waypoints

SPEC-01 E3 says `path(create)` should "spawn an actor with a SplineComponent." In 5.8 editor
Python you cannot add a component to a spawned actor at edit time — `add_component_by_class`
and `add_instance_component` are both absent from `Actor`, and constructing a
`SplineComponent` with the actor as outer then registering it doesn't stick. So there is no
clean path to a real, editor-visible SplineComponent purely from script.

Resolution: a path IS its waypoints (SPEC-01's own framing), so the path is modelled as a
pure-Python Catmull-Rom spline over waypoints stored in `_state.paths` — which delivers every
mechanical requirement without a UE spline: draped z (per-waypoint ground trace), `describe`
position+tangent at any fraction, `carve` (flatten the terrain along the curve), and the
`along=`/`facing=` placement terms. Visibility is real too: `carve` cuts a visible bed into
the terrain, and `view(map)` draws the polyline. If an editor-editable spline is later wanted
(human tweaking waypoints in-viewport), the route is a tiny Blueprint with a SplineComponent
that we spawn and push points into — deferred until a human actually needs to drag them.

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
