# SPEC-04 — Level lifecycle (new / open / save / clear)

Status: proposal, 2026-07-02. Promoted from gaps.md G16, whose want (2) — reconcile
`_state` against the actual level — already landed in SPEC-03 (now `outliner op=reconcile`). This
spec is want (1): the surface has **no level lifecycle at all**, and that is the missing
control the moment an agent builds across more than one session or map.

Read first: SPEC-03's state-reconciliation section (the drift this spec's `clear`/`open`
must trigger a reconcile around) and [[ue-buttons-spec02-status]]/its `_state` model —
because the runtime registry lives in the editor Python process, **not in the level**, and
every verb here changes which level that registry is supposed to describe.

## Why this is needed (the G16 story)

Driving Level 1 in a fresh `Untitled_2`, the (since-deleted) map view reported **2 splines /
4 foliage stands** when
only 1 of each existed this session: the prior session's populations were still in `_state`
after the editor was pointed at a different level, where none of their actors exist. The
surface could perceive and build, but it could not **new / open / save / clear** — so the
human had to drive the level menu by hand, and the registry silently described a level that
was no longer loaded. `LevelEditorSubsystem` + `EditorLoadingAndSavingUtils` are scriptable
in 5.8 (unlike Landscape), so this is buildable, not blocked.

## The verbs (one `level` verb, op-dispatched — SPEC-05 verb-collapse holds)

- **`level op=save`** — save the current level. The default, cheapest safety.
- **`level op=new`** — start a fresh level. **Clone the World-Partition template, never a
  non-WP blank** (the dogfood maps are partitioned; a blank map silently loses streaming,
  data layers, and the residency the render sense reads — SPEC-03 link 1). If the current
  level is dirty, refuse unless `force=true` (below).
- **`level op=open` (path)** — load a named level, same dirty-guard.
- **`level op=clear`** — delete all ueb-spawned actors + foliage in the current level
  (scoped by the `ueb` tag / `ueb_scatter:` component tags, exactly as `outliner`/`foliage
  op=remove` already scope), leaving the engine scaffolding. The "wipe my arrangement, keep
  the map" button.

## The dirty-check guard (load-bearing — never silently discard work)

Every op that abandons the current level (`new`/`open`) first checks
`EditorLoadingAndSavingUtils`/`LevelEditorSubsystem` for unsaved changes. If dirty, the verb
**refuses and reports what's unsaved** rather than discarding it; `force=true` (or an
explicit `save=true` that saves first) is the only way through. This is the same posture as
the outward-facing-action rule: an irreversible discard needs explicit authorization, not a
default. blender-buttons' hard-won lesson (a history desync wiped a 27-op build) applies
doubly to a whole level.

The same dirty signal belongs on the **status block's `level:` line** — `level:
Untitled_1 (UNSAVED)` — on every call, not just at transition time. Every dogfood build
to date has ended stranded in an unsaved `Untitled_1` with the save left as tribal
knowledge for the human; the block flagging it makes the hazard ambient. (Added
2026-07-03 from the post-SPEC-05 L1 retrospective.)

## Reconcile is not optional — it rides every transition

`new`/`open`/`clear` **must** run SPEC-03's `reconcile` (GC orphaned registry entries) as
part of the transition, so the registry can never describe a level that's no longer loaded —
the exact G16 phantom. Additionally (SPEC-03 §reconcile "nice"), fold the silent orphan-GC
into `outliner` default reads (the `_prune_dead_intents` pattern) so a phantom
can't even momentarily appear between a level change and a manual reconcile. After this
spec, "the map shows populations that aren't there" is structurally impossible.

## Provenance / honesty conventions (ported)

- A `level` op that changes the loaded map returns the old and new level names, and the
  reconcile summary (`N orphaned GC'd`) — the transition is never silent about what it
  cleaned.
- `clear` reports the count removed by kind (actors / populations), like `foliage op=remove`.
- Camera/selection are perception-side; a level change resets neither the follow toggle
  (G17) nor declared intents that survive by design — but declared intents whose subjects
  are gone auto-GC on the reconcile, as they already do.

## Non-goals

Level streaming orchestration at runtime (that's SPEC-03 link 1's territory — reading
residency, not authoring it). Sublevels / level instancing as a placement mechanism (that's
the G11 "prebuilt cabin World asset" thread — a separate `add` path, not lifecycle).
Multi-level projects / world composition. Source-control integration on save.
