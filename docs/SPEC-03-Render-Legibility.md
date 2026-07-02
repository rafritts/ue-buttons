# SPEC-03 — Render legibility: the third sense

Status: proposal, 2026-07-02. Written the moment the surface's blindness became
undeniable: a `scatter` reported 6,236 instances — mesh assigned, `visible=true`,
`inst_z == ground_z` at every checkpoint, spread across the whole terrain — and *nothing*
drew in the viewport. Every data probe said "forest." The renderer said "empty." The
server had no verb that could tell the difference. This spec is the verb surface that
closes that gap **without ever needing a rendered frame.**

Ground truth to read first: SPEC-02 (the status block + spatial lint) — this is its
sibling sense, not a replacement. blender-buttons never needed this (CPU meshes, one
process, immediate registration); UE's async render/streaming/asset chain makes
"present in data" and "drawn on screen" two different facts, and only the first is
currently perceivable.

## The root problem: placement-correct is not render-correct

SPEC-02's validate floor answers *is it in the right place relative to other things* —
buried, floating, penetrating, z-fighting. It is a **spatial** sense, and its own
non-goals exclude renderability. But whether a primitive actually draws is gated by a
second, orthogonal chain of state that spatial lint never touches. An actor can be
perfectly placed and still be invisible for a reason that has nothing to do with
geometry:

- its component was never **registered** with the render scene (the G14 HISM bug —
  data-correct, no scene proxy);
- it lives in a World Partition cell that isn't **streamed/resident**, or a data layer
  that's **unloaded/hidden** (present in the actor tree, absent from the renderer);
- a **hide flag** is set — `is_temporarily_hidden_in_editor` is a *different* flag from
  `is_visible()`, and checking one while trusting the other is exactly the miss that
  produced this spec;
- it's outside its **cull distance** or `min_draw_distance`, or its **bounds** are zero;
- its **material** slot is null / the default is substituting / opacity resolves to 0;
- the **mesh asset** itself has no render data (empty LOD0, zero render bounds);
- it draws fine but is **sub-pixel** from the actual camera — present, correct, and
  smaller than one pixel, which is visually identical to absent.

Every one of those is a *fact the editor already knows* and the server currently cannot
ask. The disposition SPEC-02 diagnosed — the model is a reactor, not an inspector —
means this can't be fixed by "remember to check rendering." It has to become a forced
sense, reported by exception, on the same footing as the spatial floor.

## The gating chain (the thing the sense reports)

A primitive draws **iff every link holds.** The sense's job is to walk the chain and
name the first broken link, as data. Ordered from cheapest/most-common failure to rarest:

1. **Resident** — the owning actor's WP cell is streamed in and its data layer is
   active + editor-visible. (collection-scoped; see `streaming` below)
2. **Registered** — the component has a scene proxy (registered with the world). The
   G14 check, promoted to a first-class field.
3. **Shown** — none of `is_temporarily_hidden_in_editor` / `hidden` / `hidden_in_game`
   is set on the actor, and the component's `visible` / `should_render` is true.
4. **Bounded** — world AABB extent is non-zero.
5. **In range** — start/end cull distance and `min_draw_distance` don't exclude it at
   the observing distance; `bounds_scale` sane.
6. **Materialised** — every material slot resolves to a real material (no default
   substitution), and the blend/opacity won't render it invisible.
7. **Has render data** — the mesh asset has LOD0 geometry (tri count > 0) and non-zero
   render bounds; Nanite enabled or a fallback mesh present.
8. **On-screen size** — from a given observer, projected pixel size ≥ ~1 px.

Links 1–7 are boolean facts; link 8 is a computed number. None require a frame.

## The verbs

Four read-only verbs (they carry no status block — they *are* perception, per SPEC-02).
Each names the UE backing so this is implementable, not a wish list; where a binding is
thin, the interim backend is named in the same spirit as the trace/undo adoptions
(`SceneTools._trace_world`, console `TRANSACTION UNDO`).

### `render_state(target)` — the per-object draw verdict (links 2–7)

Input: an actor label, a component, or a population label (scatter). Output: the gating
chain as a per-link verdict, plus a one-line `verdict` ("DRAWS" / "HIDDEN: temporarily
hidden in editor" / "NO PROXY: component unregistered" / …). Report by exception — a
clean object is one line; a broken one shows the first failed link *and* the fix, the
way spatial-lint findings carry their correction.

Fields and backing:
- registered / has proxy — `component.is_registered()` where exposed; else infer from
  the foliage/ISM path (G14 recipe guarantees it).
- hide flags — `actor.is_temporarily_hidden_in_editor()`, `is_hidden_ed()`,
  `get_editor_property("hidden")`, component `is_visible()`, `is_visible_in_editor()`.
- bounds — `actor.get_actor_bounds()` / component bounds; zero extent ⇒ finding.
- cull — component `instance_start/end_cull_distance`, `LDMaxDrawDistance`,
  `min_draw_distance`, `bounds_scale`.
- materials — `component.get_materials()`; per slot null-check; `material.get_base_material()`
  / blend mode via the material's `get_editor_property("blend_mode")`; flag when the
  engine default material is the resolved material (the "someone forgot to assign" tell).
- mesh render data — `StaticMeshEditorSubsystem.get_number_triangles(mesh, 0)`,
  `get_number_verts`; `mesh.get_bounding_box()`; Nanite via
  `mesh.get_editor_property("nanite_settings").enabled`.

For a population, this runs per-FoliageType/component and folds to a summary
("32 components, all DRAWS" or "3 components NO PROXY: FT_… unregistered").

### `streaming(target?)` — World Partition residency (link 1, the collection sense)

The one the current surface is most blind to, and the prime suspect whenever a
correct-by-every-metric build renders as nothing. Two modes:

- `streaming()` — enumerate WP grid state: cells and their load state, data layers and
  their runtime state (Activated / Loaded / Unloaded) + editor visibility, and the
  editor's currently-loaded region(s). Backing: `unreal.WorldPartitionSubsystem`,
  `DataLayerManager` / `DataLayerSubsystem.get_data_layer_runtime_state(...)`. Where the
  Python binding can't reach the editor cell hash, fall back to parsing the `wp.info` /
  streaming-status console command output (same adoption pattern as the trace backend).
- `streaming(target=label)` — for one actor: which cell and data layer own it, and
  whether both are resident right now. This is the verb that says, in words, "your
  6,236 instances are in cells that aren't streamed in — that's why the renderer never
  saw them," and turns a day of blind guessing into one call.

### `observe(from)` — camera-relative visibility, computed not seen (link 8)

The sense most in the repo's spirit: instead of *looking* at whether a thing is visible,
*compute* it. Input: a target population/actor + an observer (the live editor perspective
viewport by default, or an explicit `[x,y,z]` + look-at). Output, all numbers:
- nearest-instance distance, and how many instances fall inside the camera frustum;
- **projected pixel size** of a representative instance — pinhole projection from world
  size, distance, viewport FOV and pixel height. "Representative tree projects to 0.8 px
  at the current camera" is a precise, deterministic diagnosis of *present-but-sub-pixel*
  — visually identical to absent, but now a legible fact.
- behind-camera / off-frustum count, so "camera pointed at empty sky" is distinguishable
  from "trees too small" is distinguishable from "trees genuinely absent."

Backing: `UnrealEditorSubsystem.get_level_viewport_camera_info()` (already used by
`view`) for the transform; FOV from the viewport client (or a documented default);
object world-size from `render_state` bounds. Pure server-side math — no frame, no async
screenshot, immune to G8.

### `reconcile(scope?)` — the editor's own registries vs `_state`

Cross-check the server's memory against the editor's ground truth, so counts are never
self-reported in a vacuum. Read the Foliage subsystem's *own* per-type instance tally and
the asset/actor registries; diff against `_state.scatters` / `paths` / actors. Catches
(a) the "I re-derived 6,236, does the editor agree?" question, and (b) the G16 ghosts —
`_state` entries whose actors/foliage don't exist in this level — mechanically instead of
by eye. This is the render-legibility analogue of SPEC-02's provenance rule: a count
names its source and is checked against the authority.

## How it composes with SPEC-02

Render legibility is the **third forced sense**, slotting into the same channel order:

- SPEC-02 Sense 2 (validate) stays the *spatial* floor: placement correctness.
- This adds a *renderability* floor: after a geometry/placement op, the touched delta is
  walked through the gating chain, and the status block gains a `render:` line —
  `render: DRAWS` when clean, or `render: 32 foliage comps unregistered → …` by
  exception. Same discipline as validate: **OFF must announce itself** ("render: OFF")
  so silence-because-disabled never reads as silence-because-drawing.
- `render_state` / `streaming` / `observe` / `reconcile` are the on-demand deep-dives the
  floor points you toward, exactly as `feel` is the deep-dive behind the spatial line.

The through-line, and the reason this is a server concern before it's a scene concern:
**"the data all looks right" is the failure mode, not the success signal.** Until the
server can walk the render-gating chain as data, every build is verified by construction —
and by construction is precisely the proof that this spec exists to retire.

## Non-goals

Aesthetic judgment (Ryan's). Pixel-accurate render correctness (that needs the frame we're
declining to depend on). Lighting/shadow/exposure quality. Perf budgets. Anything that
requires *interpreting* an image rather than *querying* the state that produced it — the
entire premise here is that the state is legible and the image is not.
