# SPEC-03 — Render legibility: the third sense

Status: proposal, 2026-07-02. Rewritten after studying how blender-buttons solves the
same problem — because it already does, maturely, and this spec is mostly a port with
UE-specific links added. Written the moment the surface's blindness became undeniable: a
`scatter` reported 6,236 instances — mesh assigned, `visible=true`, `inst_z == ground_z`
at every checkpoint, spread across the whole terrain — and *nothing* drew. Every data
probe said "forest." The renderer said "empty." No verb could tell the difference.

Read first: SPEC-02 (status block + spatial lint — this is its sibling sense). Sister-repo
ground truth to read before implementing, with the exact code this ports:
`blender-buttons/extension/common.py:470-571`, `extension/introspect.py:524-713`,
`extension/lint.py`, `extension/validation.py`, `server/_core.py:180-329`,
`extension/handles.py:1-135`, and its `docs/SPEC-16` (forced senses) + `SPEC-20`
(provenance). blender-buttons never needed a *streaming* concept (CPU meshes, one process,
immediate registration); UE's async register/stream/asset chain is what makes "present in
data" and "drawn on screen" two different facts — so the port keeps its whole doctrine and
adds the residency links that have no Blender ancestor.

## The borrowed doctrine: verify without a frame, and never verify *with* one

blender-buttons' lint module opens with the thesis this spec exists to bring to UE
(`extension/lint.py` header): return *"compiler-style verdicts the agent can act on
**without a render** — instead of burning renders and image tokens on a question with an
exact geometric answer."* And its render verb is blunter still (`server/verbs/render.py`):
*"THE IMAGE IS FOR THE HUMAN, NOT THE AGENT. Do NOT read it back… LLM vision is unreliable
at this level of precision, and it self-confirms… The render cannot catch your own mistake;
it launders it. Verify with GROUND TRUTH instead."*

That is the posture SPEC-03 adopts wholesale: the rendered frame is an output for the
human, never the agent's verification path. Everything below answers "will this draw, is it
framed, is it seen, is it big enough" as **numbers and booleans**, computed from the state
that produces the image — because that state is legible and the image is not.

## The core steal: renderability is a *filter at the source*, not a separate query

The single most important design decision in blender-buttons is not a verb. It is that
"will this show up" is applied at the **source of every physical read**, so a
non-renderable object can never silently poison a spatial answer. One predicate defines
"in the renderable scene," and resting/contact/support/validate/framing all consume it
(`extension/common.py:470-494`, `scene_mesh_objects`):

```python
def _hidden(o):
    if o.hide_viewport or o.hide_render:   # data flags — never raise
        return True
    try:
        return o.hide_get()                # view-layer eval — CAN raise…
    except RuntimeError:
        return True                        # …and a raise means "excluded here" = hidden
```

The docstring records the bug that forced it (G147): a hidden scatter-source mesh at the
origin was being chosen as the support surface under a plate. **This is exactly the class
of defect Level 1 is exposed to** — `trace_ground` has no renderability gate, so it will
snap an actor (or a scatter instance) to whatever collision the ray hits first, visible or
not. The fix is architectural, not a new verb:

> **Every physical read in the UE runtime — `trace_ground`, scatter ground-sampling,
> `scene`, `feel`, placement — filters to renderable actors first, and names anything it
> skipped.** A trace that could only have hit a non-renderable / unstreamed / hidden actor
> returns "no renderable ground here," not a silent z.

The UE renderability predicate (the analogue of `_hidden`, richer because UE has more ways
to be invisible): an actor/component contributes to the rendered scene **iff** it is
*resident* (its WP cell is streamed in, its data layer active + editor-visible),
*registered* (has a scene proxy), *shown* (no `is_temporarily_hidden_in_editor` / `hidden`
/ `hidden_in_game`; component `visible`), *bounded* (non-zero AABB), and *materialised*
(no null slots / default-material substitution). Links marked ★ are UE-only, no Blender
ancestor.

## The gating chain (what the sense reports)

A primitive draws **iff every link holds.** The sense walks the chain and names the first
break, as data — cheapest/most-common failure first:

1. ★ **Resident** — owning WP cell streamed in; data layer active + editor-visible.
2. ★ **Registered** — component has a scene proxy (the G14 HISM bug, promoted to a field).
3. **Shown** — no hide flag set; `is_temporarily_hidden_in_editor` is a *different* flag
   from `is_visible()`, and checking one while trusting the other is the miss that made
   this spec. blender-buttons keeps `viewport_visible` and `render_visible` as **separate
   fields, never conflated** (`extension/objects.py:1126-1131`) — do the same.
4. **Bounded** — world AABB extent non-zero.
5. ★ **In range** — start/end cull distance, `min_draw_distance`, `bounds_scale`.
6. **Materialised** — every slot resolves to a real material; flag when the engine
   **default material is substituting** (the "someone forgot to assign" tell —
   blender-buttons flags `"no material slot"` at `extension/lint.py:345`).
7. ★ **Has render data** — mesh LOD0 tri-count > 0, non-zero render bounds; Nanite enabled
   or fallback present.
8. **On-screen size** — from an observer, projected pixel size ≥ ~1 px (§ computed
   visibility).

Links 1–7 are booleans; link 8 is a number. None require a frame.

## Where it plugs in: the third forced sense (not a pile of new verbs)

SPEC-05's verb-collapse rule holds — this adds **no top-level verbs**. It extends the three
perception verbs and the validate floor, exactly as blender-buttons folds renderability
into `feel`/`validate`/`scene` and puts a `render:` line in its status block
(`server/_core.py:227-285`, which also carries a `viewport:` shading line and an
`engine_unavailable` warning that never presents a dead render engine as clean).

- **The status block gains a `render:` line** (SPEC-02 Sense 2's sibling): after a
  geometry/placement op, the touched delta is walked through the gating chain.
  `render: DRAWS` when clean; by exception, `render: 32 foliage comps unregistered → …` or
  `render: population in unloaded data layer 'Foliage' → streaming(activate)`. Same
  discipline as validate: **clean is printed, not silent** (blender-buttons prints
  `validate: clean` as literal text, `extension/validation.py:626`), and **OFF announces
  itself on every block** (`render: OFF — floor is down`) so silence-because-disabled can
  never read as silence-because-drawing.
- **`scene` gains streaming/residency** — WP grid load state, data layers + runtime state,
  the editor's loaded region, and per-actor "which cell/layer owns it, is it resident."
  This is the collection-scoped blindness the surface most lacks and the prime suspect
  whenever a correct-by-every-metric build renders as nothing. Backing:
  `WorldPartitionSubsystem`, `DataLayerManager.get_data_layer_runtime_state`; where the
  binding can't reach the editor cell hash, parse `wp.info` console output (the same
  adoption pattern as the `SceneTools._trace_world` trace backend and console
  `TRANSACTION UNDO`).
- **`feel` gains a render-state deep-dive** — `feel(op="render_state", target=…)` walks the
  full chain for one actor/component/population and returns the per-link verdict + the fix,
  the on-demand detail behind the block's one-line summary (as `feel` is the detail behind
  the spatial line).
- **`view` gains computed visibility** — below.

## Computed visibility: the camera family (port almost verbatim)

blender-buttons computes framing/occlusion/size entirely from matrix math + raycasts over
the evaluated geometry — never a screenshot. Port these into `view` (which already owns the
camera: `orbit`, `map`; add `framing` / `visible`):

**(a) Projected screen size + clipping + behind-camera** — `camera_coverage`
(`extension/common.py:545-571`): project the world AABB corners through the view, take the
frame-space min/max.

```python
for c in world_bbox_corners(obj):
    co = world_to_camera_view(scene, cam, c)     # UE: FSceneView::WorldToScreen / project
    us.append(co.x); vs.append(co.y); depths.append(co.z)
return {"frac_w": umax-umin, "frac_h": vmax-vmin,        # screen size as frame fraction
        "in_front": any(d>0 for d in depths),
        "clipped": [edges where u/v spill past 0..1]}
```

`frac_w`/`frac_h` are the "too small to see" and "is it framed" numbers, computed. UE has
every primitive (`FSceneView::WorldToScreen`, actor bounds).

**(b) Occlusion — is it actually seen or hidden behind terrain** — raycast from the camera
to sampled target points; a hit on a *different* actor = occluded
(`_occlusion_fraction`, `extension/common.py:524-547`). UE already has the ray:
`SceneTools._trace_world` / `LineTraceSingle`. "Is the tree behind the ridge from here" is
a trace, not a render.

**(c) Visible *front-facing* surface (the subtle one, G131)** — whole-bbox occlusion reads
~100% for a recessed-but-visible part (liquid seen through a mug's mouth). Sample only
front-facing points (normal toward camera) and count unoccluded ones
(`_visible_surface`, `extension/common.py:550-582`). Port it: a valley floor seen through a
gap in the canopy shouldn't read as hidden.

**(d) Provenance for the number (G22/G36) — the number is meaningless without its
reference.** `world_to_camera_view` fits to the render aspect, so coverage % silently
shifts with resolution; blender-buttons makes the reference explicit on every reading
(`_frame_ref`, `extension/introspect.py:635-651`) and **resolves the camera exactly as
render does** so the preflight *is* the render's ground truth (G36). UE port: every framing
number states the viewport it was projected against (resolution + FOV), and reads the
*actual* editor perspective-viewport camera
(`UnrealEditorSubsystem.get_level_viewport_camera_info` — already used by `view`).

Together these distinguish, as numbers, the four cases I could not tell apart in Level 1:
*sub-pixel* vs *off-frustum* vs *occluded* vs *genuinely absent*.

## Suppression discipline (port verbatim — the self-policing part)

blender-buttons allows **no "ignore."** Its taxonomy maps cleanly onto render findings:

- **Intent-free render defects are never suppressible at all** — unregistered component,
  null material slot, empty render data, sub-pixel-when-it-should-be-hero. These are the
  render analogue of z-fights/non-manifold (`_INTENT_FREE`,
  `extension/validation.py:38-39`): there is deliberately no "false-positive" or
  "tolerance" tag, "those would just be the easy dodge wearing a different hat" (SPEC-16).
- **The few genuinely intentional cases are blessed by a reasoned positive assertion, never
  an ignore** — e.g. "this population lives in a data layer that's intentionally streamed
  out for this shot." The only affordance is `validate(op="expect", …, reason=…)` — a
  *required* reason ("an assertion you can't justify is a bug you're hiding"), **scoped to
  the specific `(check, subject)` pair** (not the bare actor, so blessing one hidden LOD
  proxy doesn't blind the next), that **collapses to a count** ("1 intended") rather than
  silencing, and is a **bidirectional tripwire**: a blessed-hidden population that becomes
  *visible* is itself a finding, just as a declared-intended clip that vanishes fires in
  blender-buttons (`validation.py:543-554`). Over-blessing produces a visible pile, not
  quiet.

## Provenance (SPEC-20 ported): every render number names its basis

blender-buttons stamps every spatial measurement with the geometry it was read on —
`evaluated` (what renders) vs `cage` (editable), plus which modifiers were live
(`measurement_provenance`, `extension/common.py:78-94`; `↳ measured on …`,
`server/_core.py:288-293`). The rule (SPEC-20 R3): derive from the build, never from model
memory — "version-stale and self-confirming, the same failure mode as reading your own
renders." UE analogues to stamp:

- which **component** answered (path-name, since WP shards names — the G14 lesson);
- **simple vs complex collision** answered a trace (SPEC-02 already calls for this);
- **LOD0 / Nanite-fallback** for a tri/bounds read;
- for a framing number, **which camera + which frame reference** (resolution + FOV).

A render/coverage number is never silent about what produced it.

## State reconciliation: clean / dirty / orphaned (ports handles.py; closes G16)

blender-buttons keeps **no parallel server-side store** — the Blender datablocks *are* the
registry, and named anchors diff against them (`extension/handles.py:1-135`). On every read
it recomputes a provenance signature and classifies:

- **clean** — matches the mint-time snapshot within ε; use silently.
- **dirty** — moved under it, but still resolves; flagged with drift *attribution*
  (**self** = an agent op explains it / **external** = the loud alarm).
- **orphaned** — the provenance won't replay (backing gone).

Dead entries auto-GC (`_prune_dead_intents`, `validation.py:103-114`) so a deleted subject
never leaves a permanent un-clearable tripwire. This is the mechanical cure for **G16**
(ueb `_state` outliving the level — the phantom hamlet scatters): a `reconcile` read (folded
into `scene`/`validate`, not a new verb) diffs `_state.scatters`/`paths`/actors against the
editor's *own* foliage tally and actor registry, classifies each clean/dirty/orphaned with
attribution, and GCs the orphans — instead of trusting a self-reported count in a vacuum
(the 6,236 I re-derived should have been checked against what the editor thinks it has).

## How the three senses now compose (SPEC-02 + this)

- **feel delta** (Sense 1): what you changed, as perception, no verdict.
- **validate** (Sense 2): the *spatial* floor — buried/floating/penetration/z-fight.
- **render** (Sense 3, this spec): the *renderability* floor — the gating chain verdict.

All three report by exception, print "clean" as text, and announce themselves when OFF.
The through-line, and why this is a server concern before a scene concern: **"the data all
looks right" is the failure mode, not the success signal.** Until the server walks the
render-gating chain as data, every build is verified by construction — and by construction
is exactly the proof this spec exists to retire.

## Non-goals

Aesthetic judgment (Ryan's). Pixel-accurate render correctness, lighting/shadow/exposure
quality (blender-buttons *does* model exposure/DoF deterministically — a later spec may
port that; out of scope here). Perf budgets. Anything that requires *interpreting* an image
rather than *querying* the state that produced it — the entire premise is that the state is
legible and the image is not.
