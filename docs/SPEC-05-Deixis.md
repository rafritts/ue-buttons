# SPEC-05 — Deixis: shared referents between the user and the agent

Status: **DRAFT / STUB** — deliberately rough. The pattern gets nailed down in a live
editor-poking session with the user before this is fleshed out. Do not implement from
this document as-is.

## Problem

The agent can't see; the user can't be expected to know actor labels for 400 scattered
instances. "This tree has no texture" has no resolvable referent today. Every diagnostic
conversation needs a shared way to point.

## Scope (rough)

1. **Selection-as-deixis** — read the *user's* editor selection and return the selected
   things as full ueb-style entries (label, dims, materials, motion verdict). Must resolve
   foliage/HISM clicks down to `(component, instance_index)`, not just the owning actor —
   that resolution is most of the value. Likely a `select` op (`op=mine` / `whom`), not a
   new verb.
2. **Camera-as-deixis** — read the editor viewport pose; trace along its forward vector;
   answer "you're looking at X, Nm away." Same idea for the PIE pawn ("where I'm standing").
3. **Complaint vocabulary** — a short doc section mapping ~15 plain-language symptoms
   ("checkerboard", "flickering", "jelly", "I fell through") to the probe the agent runs.
   Documentation, not code, but part of this spec's contract. Probes themselves are SPEC-06.

## Open questions (to answer by poking the editor together)

- What does the RC bridge actually expose of the user's live selection and viewport camera?
  (Editor subsystems vs. `unreal.EditorLevelLibrary` deprecations; instance-level hit
  proxies may not be reachable from Python at all.)
- Does selection survive between the user's click and the agent's read (focus changes,
  PIE transitions)?
- What's the natural conversational grammar — does the user say "this one" and the agent
  always checks selection first, or is it an explicit verb call?

## Verification story (rough)

The user clicks a tree, says "this one"; the agent names it, measures it, classifies its
motion — live over the bridge, including a foliage-instance click.

## Sequencing

First of the diagnostic family: SPEC-06 (symptom probes), SPEC-07 (lint), SPEC-08
(runtime lint) all consume its referents.
