# SPEC-08 — Lint: whole-level sweeps

Status: **IMPLEMENTED + live-verified 2026-07-04** (`validate.lint` + `rules.sweep`;
verification trace at the bottom). The G41 hazard facts below are live-verified and
non-negotiable. One design item deferred with cause: registering rules as editor
validators (see that section).

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

**DEFERRED at implementation time (2026-07-04), by the ratchet:** the table holds zero
`static`-tier rows — R1 and R2 are both `census`-tier (the defect lives in the
asset×usage pairing, which an asset-scoped validator can't see). There is nothing to
register and therefore no experiment to run. Build the adapter when dogfooding produces
the first genuinely asset-only row; the open question below is answered then.

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

## Verification trace (2026-07-04, all over the bridge)

1. **Seeded-defect scratch level:** planted four defect classes on UEB_Scratch (a
   pivot-WPO pine painted `force=true`, a standalone actor wearing a PerInstanceRandom
   material, a ground-defective rock, a fully-coincident duplicate pair) →
   `scope=all` found ALL FOUR: F1 R1/breaks, F2 R2/breaks, duplicate-transform
   z-fight, ground findings — 8 findings total (the extras are real consequences of
   the seeds: the dup pair also penetrates), every one carrying a `next`. Cleanup
   followed the G47 rule (referencers first, polite deletes, the in-use unsaved
   material left to evaporate).
2. **Known-positive fixture:** L1 reports EXACTLY `F1 [breaks] pine_forest (1916
   instances, SM_Pine_Tree_01..05): … (R1/G40)` and nothing else — after fixing a real
   pre-existing bug this fixture caught: `substrate_labels()` derived only from the
   session registries, so a level REOPENED after an editor restart validated its own
   terrain and spline strip as floating actors (6 false findings). Cure: a ueb
   DynamicMeshActor is always a substrate (the runtime spawns that class only for
   terrains and strips) — class is the durable tell, registry or no registry.
3. **Scope resolution:** `scope=understory` → clean (1/1 subjects, floor honestly
   n/a for a substrate); `scope=pine_forest` → the R1 finding; `scope=selection`
   (selection set to an actor) resolves and lints it; a bogus scope errors with the
   known stand labels (editor-derived, restart-proof) and a next.
4. **Budget honesty:** an already-expired deadline → `subjects 0/3` plus "rule sweep
   stopped at 0/3 subjects (seconds budget) — re-run to continue; the certificate
   cache makes the second pass fast". (A warm L1 lint completes in <0.1 s, so a
   realistic budget never trips there — the mechanism is exercised, the scale isn't.)

Engine-validator layer: 13/13 L1 assets checked, all valid — consistent with G41's
finding that stock validation is a floor, not a roof (it still says VALID on the G40
material). The `scope=`/`seconds=` params on the `validate` MCP tool were verified
END-TO-END through the real tools after the client reconnect (same day): the L1 sweep
returned F1 with full coverage, and a bogus scope carried its affordances
(known_stands + next) all the way to the client.

## Sequencing

After SPEC-07 (lint is that engine at scale plus engine-validator wrapping). SPEC-09
covers what static lint can't see, and is gated on this spec's dogfooding.
