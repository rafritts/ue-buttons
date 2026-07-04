# SPEC-06 — Deixis: shared referents between the user and the agent

Status: **IMPLEMENTED + live-verified 2026-07-03** (`runtime/ue_buttons/deixis.py`; ops on
`select`/`feel`/`play`). The stub's open questions were answered by the first live
experiment (below) before implementation — the pattern was nailed down against the running
editor, not designed on paper.

## Problem

The agent can't see; the user can't be expected to know actor labels for 400 scattered
instances. "This tree has no texture" has no resolvable referent without this surface.
Every diagnostic conversation needs a shared way to point.

## The three reads

1. **`select op=user`** — selection-as-deixis. The user clicks the thing and says "this
   one"; the agent reads the live editor selection and gets full ueb-style entries
   (label, class, dims, meshes, motion verdict, next moves). A foliage click lands on the
   level's `InstancedFoliageActor` — resolved down to its populated components: mesh,
   instance count, owning stand (from the `ueb_scatter:<label>` component tag), motion
   classification. Component-level resolution is enough to diagnose (proven live: G39→G40).
2. **`feel op=looking_at`** — camera-as-deixis. Trace the editor viewport's forward ray:
   "you're looking at X, N m away." Hits attribute to what the user would call them
   (a foliage instance of stand S / the ueb terrain / the surface strip of spline P / a
   placed actor / engine scaffolding), with hit point and distance.
3. **`play op=where`** — the PIE pawn's version, readable MID-PLAY (`play` is exempt from
   the B8 guard): where the player stands + what the player camera looks at, from the
   game world. "Right here, where I'm standing" made resolvable without ending Play.

Every answer carries `next` — ready-to-fire follow-up calls (the HATEOAS rule).

## Implementation notes (what the editor actually taught)

- **Foliage carries NO collision** (G46): painted components report `NoCollision` /
  `ECR_IGNORE` on visibility, so no line trace can ever hit an instance. `looking_at`
  resolves "which tree" by a ray-vs-instance-AABB **math pass** instead
  (`_foliage_along_ray`): instance transforms + mesh bounds are ground truth (derived,
  not divined), components are pruned by bounding sphere before instances are walked
  (17k instances → ~0.2 s round trip), and the math pass wins whenever an instance sits
  nearer than the traced world hit. The gameplay half (pawn walks through trunks) stays
  open as G46.
- The HitResult `component` + `item` fields DO resolve an instance index when a trace
  hits a collidable ISM — that path is kept for projects whose foliage has collision.
- Registry attribution degrades honestly: a terrain/spline whose registry entry is gone
  (reopened level — registries are session-scoped by design) attributes as "a placed ueb
  actor" instead of its richer kind.
- PIE labels are the game world's runtime copies; `play op=where` says so and advises
  mapping back to editor actors by position, not name.

## Complaint vocabulary (documentation — this spec's third deliverable)

Plain-language symptom → the probe the agent runs today. SPEC-07 will fold these into
one-shot symptom probes; until then this is the routing table.

| the user says | the agent runs |
|---|---|
| "this one" / "this tree" (clicks it) | `select op=user` |
| "that thing over there" (aims the viewport) | `feel op=looking_at` |
| "right here, where I'm standing" (in Play) | `play op=where` |
| "it's invisible / I can't see it" | `feel op=render_state target=X` (gating chain), then `feel op=framing` / `op=visible` (sub-pixel vs off-frustum vs occluded vs absent) |
| "it's flat grey" | `feel op=render_state` — engine-default-material tell |
| "checkerboard / grid pattern on it" | `asset op=describe name=<material>` — foliage-card or wrong-domain master on a surface (G32) |
| "it renders like a mirror" | `asset op=describe name=<material>` — wrong master (the pond trap) / roughness |
| "the trees bob / float / jelly" | `select op=user` on a clicked instance → motion verdict (G39; pivot-anchored-WPO-under-instancing is G40) |
| "black screen when I press Play" | `play op=census` (G36) |
| "I fell through the ground" | `feel op=describe target=<terrain>` + a `terrain op=describe` sample at the spot — collision (complex-as-simple) check |
| "I walk through the trees" | known: G46 (foliage has no collision) |
| "it's floating / buried" | `feel op=describe` (rests_on / on_floor), `validate op=run` |
| "it flickers" | `validate op=run` — z-fight band |
| "the path is too steep here" | `play op=where` (where is "here"), then `spline op=describe` grade profile (G45) |
| "things pop in / vanish as I move" | `level op=streaming` + render in-range link (draw distances) |
| "everything is huge / tiny" | `feel op=describe` dims vs. the asset's native size (`asset op=describe`) |

## First live experiment (2026-07-03)

The pattern works end to end. The user selected the forest and said "whole trees float and
rock, no bending" — `EditorActorSubsystem.get_selected_level_actors()` over the bridge
returned the level's `InstancedFoliageActor`; enumerating its `InstancedStaticMeshComponent`s
gave every mesh + instance count + materials; the G39 motion classifier localized the fault
to `MM_Tree_Trunk` on 549 pine instances, and a WPO-subgraph walk found the root cause
(pivot-anchored WPO breaking under instancing — now G40). Answered open questions:
selection IS readable live; a foliage click lands on the IFA, and component-level
resolution was enough to diagnose — per-instance hit resolution matters less than assumed
(and where it does matter, `looking_at`'s math pass provides it).

Follow-on (same session): deixis referents also SCOPE the SPEC-08 sweep — `validate
scope=selection` means "lint what I've selected". One more consumer of the same read.

## Verification trace (implementation day, all over the bridge)

- `select op=user` with nothing selected → the ask-the-user note, no error.
- Simulated foliage click (4 WP-cell IFAs + `player_start` selected) → per-component
  resolution: `understory` Bush_1/Bush_Tree (masked_wind, safe) vs `pine_forest`
  SM_Pine_Tree_01..05 (wpo, the G40 case), stands listed, `next` carried; the
  player_start entry with dims/position rode alongside.
- `feel op=looking_at` aimed at terrain → `'valley', 19.5 m away` with hit point;
  aimed into the forest → `'SM_Pine_Tree_05' of stand 'pine_forest' (instance 0),
  3.0 m away`, resolved by the math pass, 0.2 s round trip.
- `play op=where` mid-PIE → standing at the trailhead, `looking at 'trail_surface',
  4.1 m away`; Play never ended.

## Sequencing

First of the diagnostic family: SPEC-07 (symptom probes), SPEC-08 (lint), SPEC-09
(runtime lint) all consume its referents.
