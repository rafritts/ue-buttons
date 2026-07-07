# SPEC-16 — Level Diff: the whole-outliner blast-radius status block

Status: **DESIGN** (2026-07-06). Audience: the agent implementing it. The **narrow spatial
fingerprint** (class + location + bounds-Z) is **PROVEN this session** — snapshot/diff over
140 actors, `0/0/0` on a no-op, caught a +1000 cm PlayerStart move exactly and nothing
else, sub-second. Everything marked **SPIKE-CHECK** (full-fidelity capture, GUID identity,
World Partition streaming, cost) is unproven — verify it live before relying on it.

## Why this exists

A `terrain` heightmap import dropped ~25% of an Open World map to −257 m (the height-range
floor) and the tool returned **success with no numbers**. Every diagnostic I reached for
lied or was over-fit: the heightmap-texture read returned all-zeros over visible mountains;
per-proxy bounds worked but assumed an 8×8 World Partition grid that most levels don't have.
The lesson underneath all of it: **a mutation's blast radius must be MEASURED and SURFACED,
never assumed** — and the diagnostic must assume nothing about what kind of level it's in.

The North-Star worst case, in the user's words: **if the sun (a `DirectionalLight`) were
deleted as a side-effect of a landscape edit, the tool MUST know and say so.** No
verb-specific cleverness can promise that. Only a whole-outliner before/after diff can.

## The prime principle: maximally truthful (dumbness is the tactic, not the point)

The goal is **truth**; "dumb" is merely how we get it. Do **not** reason about what a verb
"should" have changed. Snapshot the ENTIRE outliner before the op, run it, snapshot after,
diff. Report everything that changed, anywhere, on any actor — ueb-owned or engine
scaffolding. The differ knows **nothing** about landscapes, PCG, foliage, or terrain. It
watches the whole world and reports what moved. Generality is the feature: the same code
that catches a sculpt catches a deleted sun, a nudged rock, a swapped material, a vanished
light — because it special-cases none of them.

"Maximally truthful" has two enemies, and pragmatism arbitrates between them. **False
positives / noise**: a delta that drowns a real change in meaningless ones (a whole-world
diff across a level transition, engine self-heal motion stamped onto the user's op) fails
truth just as surely as silence — false alarms teach the reader to skim, and a skimmed
diff hides the sun-deletion as effectively as no diff. **False negatives / curation**: we
do **not** filter fields by "importance" (the smart-and-fragile trap that eventually hides
a real change). We exclude **only** fields that provably flicker under a **literal no-op**
— transient render/tick/cache state. That denylist is *empirically derived* (§Transient
denylist), never hand-picked. A field is filtered **iff it changes when nothing changed.**
Everything stable-under-no-op is reported, always — because today's "who cares" field is
tomorrow's silent sun-deletion. Pragmatic exemptions on the noise side (level transitions,
the B16 self-heal — see §Wiring) are legitimate exactly when they are *documented and
inherently meaningless*, never when they merely seem unimportant.

## Decisions already made (do not relitigate)

- **Scope = ALL actors** (`get_all_level_actors`, include engine scaffolding). The sun IS
  scaffolding; owner-scoping would blind us to precisely the side-effects we hunt. [proven]
- **Capture = full per-actor state**, not a curated field set. Fidelity mechanism = SPIKE.
- **Identity = a STABLE key (actor GUID)**, not the label. Labels rename and can collide;
  only a stable key lets `removed` mean "gone" instead of "renamed". [SPIKE-CHECK]
- **No false positives is a HARD invariant.** `no-op ⇒ empty diff`, always, enforced by the
  transient denylist and gated by the stability test in the verification plan.
- **It rides the status block.** Every mutating verb auto-brackets
  `snapshot → op → snapshot → diff` and attaches a `level_delta` block. Plus an explicit
  `outliner op=snapshot` / `op=diff` for manual bracketing across several ops.
- **This is observe-and-report, not undo.** Reverting is `history`'s job; this never mutates.

## The primitive

```
snapshot() -> dict[key -> Fingerprint]
  key         = actor stable GUID (SPIKE: actor.get_editor_property("actor_guid"));
                fallback = get_path_name().
  Fingerprint = { label, class, state }
                state = full serialized actor state (SPIKE: T3D text export preferred;
                        reflection property-walk fallback), MINUS the transient denylist,
                        canonically ordered so equal states compare equal.

diff(before, after) -> LevelDelta
  added   = keys in after not in before
  removed = keys in before not in after          # ← the deleted sun lands here
  changed = keys in both whose state differs, each carrying a FIELD-LEVEL sub-diff
            (which property paths changed, before → after)

LevelDelta  (the status-block payload)
  { added:   [{key,label,class}],
    removed: [{key,label,class}],
    changed: [{key,label,class, fields:[{path,before,after}]}],
    summary: "…",
    flag:    null | "OPPENHEIMER: <n> actors changed/removed, max ΔZ <…> m — intended?" }
```

## Capture fidelity — SPIKE-CHECK (the core unknown)

Two candidate implementations of `state`, in preference order:

1. **Full text serialization (T3D)** — the dumbest, most complete capture, the same blob
   the editor's copy uses. SPIKE: find the Python path (candidates: an actor/level export
   util; a copy-actors-to-string call). If it exists and is stable, use it.
2. **Reflection property-walk fallback** — enumerate the actor's editor-exposed properties
   and record each value canonically (nested structs/objects → path or recursive capture).
   More code, no dependency on an export API.

Either way `state` MUST be order-stable (sorted keys) so equal states compare equal, and
must include component sub-objects (a deleted/edited component is a real change).

## Transient denylist — SPIKE-derived (the honesty spine)

Run once per engine version; record the result as a **documented constant** in code:

1. `snapshot(); snapshot();` — diff the two.
2. Every field that differs is transient *by definition* (nothing changed between them).
3. Record those field paths as `_TRANSIENT_DENYLIST`; the fingerprint strips them.
4. Repeat until `no-op ⇒ empty diff` holds across ≥5 consecutive no-op pairs.

Every entry carries a one-line justification: "flickered under a literal no-op." **Nothing
is denylisted for being 'unimportant.'** If a field is stable under no-op, it is REPORTED.

The ≥5-pair gate won't catch *rare* flickers. A false positive found in the wild is promoted
into `_TRANSIENT_DENYLIST` under the same discipline — reproduce the flicker under a no-op,
record the justification — never waved off ad hoc.

## World Partition — SPIKE-CHECK

Only LOADED actors enumerate, so `removed` is ambiguous: truly deleted vs streamed-out.
**Never conflate them.** Split the bucket:

- `removed`  = gone from the WP actor descriptors too → real deletion.
- `unloaded` = still in descriptors, merely not resident → streaming, not loss.

SPIKE: reach the WP actor-descriptor list from Python. If unreachable, **disclose the
ambiguity in the payload** ("N actors left the loaded set; on a WP map this may be streaming,
not deletion") — state the limitation, never bury it.

## Cost — SPIKE-CHECK

Full serialization × all loaded actors, twice per mutating op. Proven cheap for the narrow
fingerprint (140 actors, sub-second). Measure full capture on a heavy level. If it is too
slow for hot paths, ship two modes and let the payload name which ran — never silently
downgrade:

- `spatial` — transform + bounds-Z (PROVEN). Default for cheap, low-risk verbs.
- `full` — complete state (SPIKE). Default for terrain / risky / explicit ops.

## Wiring

- `runtime/ue_buttons/leveldiff.py` — `snapshot()`, `diff()`, `_TRANSIENT_DENYLIST`, mode.
- `verbs.py` — a mutating-verb bracket: capture before → run handler → capture after →
  attach `level_delta`. Applies to terrain / add / transform / foliage / pcg / material /
  spline. Read-only verbs (feel, outliner census, validate, history) skip it. Notes for
  the implementer, all found by holding this list against `verbs.py`:
  - **`level` is exempt.** `op=new/open/clear` swaps the whole world — a whole-outliner
    diff across a transition is 100% added/removed by definition, pure noise; and
    `_level_guard` (G23) already clears cross-level bookkeeping precisely because a dead
    level's state must never stamp a fresh one. `op=save` mutates nothing in-world.
  - **No existing verb set matches this list.** Runtime classification is
    `MUTATING = {add, transform}` and `SPATIAL = {terrain, spline, foliage, pcg}`;
    `material` sits in neither. Introduce a `DIFFED = MUTATING | SPATIAL | {"material"}`
    set rather than overloading the existing ones.
  - **Snapshot AFTER the B16 self-heal.** `handle()` re-sinks template Landscape proxies
    2 km on every dispatch; taking `before` after the self-heal runs keeps that engine
    housekeeping out of the op's delta (on a fresh template level it would otherwise
    stamp a massive ΔZ — and trip the flag — on an op the user never asked to move
    proxies). The sink is B16's disclosure to make, not this diff's noise.
- `outliner op=snapshot` / `op=diff` — manual bracketing across several ops (snapshot once,
  run many verbs, diff against the stored snapshot).
- Status block — `level_delta` collapses to one line when clean (`level: +0 −0 ~1`) and
  expands with the flag when the magnitude trips.

## Verification plan (prove it live)

1. **Stability** — no-op double snapshot ⇒ `added=removed=changed=0`. [PROVEN, spatial;
   re-prove for full fidelity + denylist.]
2. **Move** — nudge one actor ⇒ exactly that actor in `changed`, correct delta, nothing
   else. [PROVEN, spatial.]
3. **Sculpt (the crater)** — heightmap import ⇒ affected proxies in `changed` with bounds-Z
   deltas; flag trips. No landscape knowledge in the differ.
4. **Delete the sun** — `destroy_actor` on the `DirectionalLight` ⇒ it appears in `removed`;
   flag trips. THE headline case. Restore after.
5. **Property-only (material swap)** — reassign a material ⇒ the actor appears in `changed`
   with the material field delta. This is exactly what full fidelity buys over the spatial
   proof (the spatial fingerprint MISSES this — see the earlier `landscape_material` swap).
6. **WP streaming** — force a stream-out ⇒ lands in `unloaded`, NOT `removed`.

## Non-goals

- Not undo/redo — that's `history`. This observes and reports only.
- Not folder / data-layer organization diffing (v2 if wanted).
- Not per-instance foliage diffing — instances live inside one `InstancedFoliageActor`; the
  actor's state covers gross change. Per-instance is a later refinement.

## Provenance

Born from the SPEC-16 crater session (2026-07-06): heightmap sculpting proved possible over
RC (overturning the G12 "Landscape unscriptable" assumption for heightmap authoring), but
exercising it without trustworthy perception put a quarter of the map underwater and
reported success. The map with the crater is saved at `/Game/Maps/UEB_SculptCrater` as
test fixture #3 for the verification plan. This spec is the diagnostic that had to exist
before controlled sculpting (SPEC-17, TBD) is allowed to touch anything real.
