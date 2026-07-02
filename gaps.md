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
