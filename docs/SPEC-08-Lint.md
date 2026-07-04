# SPEC-08 — Lint: whole-level sweeps

Status: **DESIGN — fleshed out 2026-07-03, ready for sign-off. Not implemented.**
Depends on SPEC-07's rule engine landing first. The G41 hazard facts below are
live-verified and non-negotiable.

## Problem

SPEC-07's probes are *targeted* — the user points, the agent checks. Lint is the
*unprompted* version: sweep the whole level, report every finding. It is also where
accumulated tells (G38 sparse-spire, motion verdicts, floaters/sinkers) get a permanent
home instead of living scattered across verbs.

## Verb shape (decided by the user — no new verb)

EXTEND `validate` with a sweep scope:

```
validate op=run scope=selection | label=<x> | all   (default: today's touched-labels behavior)
```

- `scope=selection` is SPEC-06 deixis reused: the user selects the forest and says
  "lint this" — the selection resolves through `deixis.selection()` to stands, meshes,
  and placed actors, and the sweep runs against exactly that referent set.
- `scope=all` is the full-level audit.
- `validate` remains read-only / registry-only and carries no status block of its own
  (it IS perception) — unchanged from SPEC-02.

## What one sweep runs

Three layers, cheapest first, one findings list out:

1. **The spatial floor, widened** — today's `run_validate` checks (ground, penetration,
   z_fight) already sweep scene-wide; they simply join the findings list. Nothing new to
   build; declared intents (`op=expect`) keep quieting laden findings.
2. **The SPEC-07 rule table at firing point 3** — every `static` and `census` tier rule
   evaluated across the scope's asset×usage pairings, via the same census loop the
   status-block warning uses (one level walk, N rules). `pie`-tier rules are listed as
   "not checkable statically — see SPEC-09" rather than silently skipped (no silent caps).
3. **The engine's own validators, wrapped** — a floor, not a roof (both live-verified:
   stock Data Validation returns VALID on the G40 material; Map Check found nothing).
   - Call `EditorValidatorSubsystem.validate_assets_with_settings` over the scope's
     asset set. The 5.8 API surface is `is_asset_valid` (wants `AssetData`, not a loaded
     object), `is_object_valid`, `validate_assets_with_settings`,
     `validate_changelist(s)`, `add_validator` — there is no `validate_loaded_asset`.
   - **HAZARD (G41): never issue `MAP CHECK` as a console command over RC dispatch** —
     it crashed UE 5.8 with `EXCEPTION_ACCESS_VIOLATION reading 0x28` (crash dump on
     record). There is no clean Python API for Map Check in 5.8; we accept living
     without it. Our spatial floor + rule table already out-detect it on everything
     dogfooding has produced.

## Findings format

Numbered, severity-ranked (`breaks` > `degrades` > engine-validator notes), each line:

```
F3 [breaks] pine_forest (1916 instances, SM_Pine_Tree_01..05): pivot-anchored WPO
   (ObjectRadius) on instanced components — rigid float (R1/G40)
   → foliage op=reseed label=pine_forest rules={...}   # ready to fire
```

Every finding carries provenance (which rule, which evidence, which actors/stands) and
a ready-to-fire `next` command — the HATEOAS rule: a finding that only describes is
half-built. The agent acts on findings without translating them into verb calls.

**Decision — no persisted `lint.md`.** Findings are perishable ground truth about the
level; a file would rot the moment the level changes, and re-running the sweep is cheap
(certificate cache). Findings live in the verb result only. Server-side friction the
sweep uncovers still goes to `gaps.md` under the normal discipline.

## Registering our rules for humans

Register the rule table's `static`-tier rows as Python `EditorValidatorBase` subclasses
via `add_validator`, so the SAME rules fire for a human on save/submit inside the
editor, with zero extra rule code (the subclass is a thin adapter over the table).

Open question, to be answered by the first experiment (not on paper): do Python
validator registrations survive the runtime sync/hot-reload cycle, and does a stale
registration double-fire after re-sync? Test: register, sync-runtime, save an asset,
count firings. If hot-reload breaks it, registration becomes opt-in
(`validate op=register_editor_rules`) documented as needing an editor restart.

## Sweep cost and the G30 trap

A full-level sweep can touch every material and mesh. Same defense as
`asset inventory measure=True`: a wall-clock budget (`seconds=`, default 20) checked
between assets, partial coverage reported honestly ("swept 214/300 assets — re-run to
continue; certificate cache makes the second pass fast"). The certificate cache means
repeat sweeps only pay for new/changed assets. If a single atomic load ever wedges the
bridge mid-sweep, lint becomes the concrete offender that finally shapes G30's async
job pattern — that is the designed escalation path, not a failure.

False-positive budget: the ratchet (rules only from dogfooded defects) is the primary
defense — every rule has, by construction, at least one real-world true positive and a
verified negative control. A rule that fires wrongly in dogfooding gets demoted or
deleted the same day, gaps.md discipline.

Sister-repo ground truth: blender-buttons `extension/lint.py` / `validation.py` are the
doctrine source (compiler-style verdicts, scene-wide audits, findings-with-fixes);
translate conventions, don't re-derive.

## Verification plan

1. **Seeded-defect scratch level:** plant N known defects (a pivot-WPO palette painted
   with `force=true`, a standalone actor with a PerInstanceRandom material, a floater,
   a z-fight pair) → `validate op=run scope=all` finds N/N, each with a fireable `next`.
2. **Known-positive fixture:** L1 as it stands today MUST report exactly the known set
   (R1 on the pine stands, the 22% trail grade if a grade rule exists by then) and
   nothing else.
3. **Scope resolution:** select only the understory stand → `scope=selection` reports
   zero rule findings (Bush_1 is masked_wind, safe) while `scope=all` still reports the
   pines.
4. **Budget honesty:** set `seconds=1` on a cold cache → partial-coverage note appears
   with the swept/total count.

## Sequencing

After SPEC-07 (lint is that engine at scale plus engine-validator wrapping). SPEC-09
covers what static lint can't see, and is gated on this spec's dogfooding.
