# SPEC-16 — Level Diff: the whole-outliner blast-radius status block

Status: **IMPLEMENTED + fully verified — CLOSED** (2026-07-06) — `runtime/ue_buttons/leveldiff.py`,
wired into `verbs.py` (auto-bracket on the `DIFFED` verb set) + `outliner op=snapshot|diff`.
Every SPIKE-CHECK resolved live against UE 5.8, green. All six author rulings implemented,
incl. the B16 flag-attribution (strict 4-part signature) and `outliner op=diff verbose=true`.
**All verification steps run live, including step 3 (the founding crater sculpt on
`/Game/Maps/UEB_SculptCrater`) and step 6 (WP stream-out disclosure)** — see §Implementation
status. Step 3 surfaced a first-order finding: a heightmap import lands on a
`LandscapeEditLayer` and bounds stay STALE until `force_layers_full_update()` composites it —
the exact root of the crater session's "success with no numbers." The differ is correct
either way; a sculpt VERB (future SPEC-17) must flush, and a `0/0/0` diff after an unflushed
sculpt is the honest signal it never took.

The **narrow spatial fingerprint** (class + location + bounds-Z) was **PROVEN** the prior
session — snapshot/diff over 140 actors, `0/0/0` on a no-op, caught a +1000 cm PlayerStart
move exactly and nothing else, sub-second. This session proved **full fidelity** too: the
reflection property-walk (incl. component recursion) is reachable, ~0.5 s / 138 actors,
**zero no-op flicker** (the transient denylist ships EMPTY), and it catches property-only
changes (a light dim, a material swap) the spatial fingerprint misses.

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

## Implementation status (2026-07-06)

Built: `runtime/ue_buttons/leveldiff.py` (`snapshot`/`diff`/`render_lines`, the empty
`_TRANSIENT_DENYLIST`, the two modes, the OPPENHEIMER flag, the B16 `_is_b16_sink`
attribution). Wired: `verbs.py` `DIFFED = MUTATING | SPATIAL | {"material"}`, the
before/after bracket in `handle()` (snapshot after the B16 self-heal, skip `op=describe`,
skip on error), the `level_delta` spliced onto the status block; `outliner op=snapshot|diff`
(+ `verbose=true` uncapped dump) for the manual bracket; `_state.level_snapshot` /
`_state.leveldiff_mode`; server `outliner` tool gains `snapshot|diff` + `mode=` + `verbose=`.

**Author rulings implemented (all six):** (1) B16 sink = flag-**attribution** under the
strict 4-part signature — matched proxies stay in `changed`, are summarized by one `⚙`
housekeeping line, and are excluded from the flag; one deviating field drops the exemption
and the flag trips (live-verified: terrain-create shows `⚙ ~129 template proxies sunk 2 km`
with NO OPPENHEIMER, while the step-3 sculpt of the SAME proxy class is NOT attributed and
DOES trip). (2) `full` default. (3) thresholds as-is. (4) `material` in `DIFFED`. (5) cap 25
+ `verbose=true`. (6) steps 3 & 6 run below.

**SPIKE-CHECKs — all resolved live (UE 5.8):**
- **GUID identity** ✅ `actor.get_editor_property("actor_guid").to_string()` — stable hex,
  138/138 stable across reads. Fallback `get_path_name()`. `removed` means gone, not renamed.
- **Capture mechanism** ✅ T3D/actor-export APIs are ABSENT in 5.8 (spiked: every
  `export_*` candidate missing), so the reflection property-walk is THE mechanism, not a
  fallback. UPROPERTYs are the class's `getset_descriptor`s (methods are
  `methodwithclosure_descriptor` → excluded). Component recursion catches material overrides
  + light params.
- **Transient denylist** ✅ EMPTY by construction. Actor+component double-snapshot over 138
  actors → **zero** flickering fields. The no-op ⇒ empty-diff HARD invariant holds out of
  the box (re-verified end-to-end through the runtime).
- **Cost** ✅ full walk incl. components ≈ 0.5 s / 138 actors (~65k fields); two per op.
  Cheap enough to default `full` everywhere. `spatial` (transform+bounds) kept as the honest
  fast-path lever (`_state.leveldiff_mode`), and the payload always names which mode ran.
- **World Partition** ⚠ DISCLOSED, not yet split (gap G63). The `removed`-vs-`unloaded`
  descriptor split is NOT built; instead, on a partitioned map a non-empty `removed` carries
  a `removed_note` stating the ambiguity plainly (state-the-limitation, per charter).
  `WorldPartitionBlueprintLibrary.get_actor_descs()` is the reachable source for the real
  split (confirmed live: 140 descs persisting across an unload) — logged in G63.

**Verification plan results (live, through the runtime):**
1. **Stability** — no-op double snapshot ⇒ `+0 −0 ~0`, full mode. ✅
2. **Move** — nudge one actor ⇒ exactly that actor in `changed`, correct location fields,
   nothing else. ✅
3. **Sculpt the crater (THE founding case)** — on `/Game/Maps/UEB_SculptCrater`: snapshot →
   `landscape_import_heightmap_from_render_target` → `force_layers_full_update()` → snapshot
   → diff ⇒ **64 Landscape proxies in `changed`, bounds-Z −256 m → +178 m (Δ434 m), flag
   TRIPS**, and crucially **NOT** mis-attributed as B16 (varied ΔZ, no hide, not the −2 km
   constant → the strict signature correctly rejects it). Fixture heightmap restored after.
   The flush is load-bearing: without `force_layers_full_update()` the import lands on an
   edit layer and bounds read STALE — the differ then honestly reports `0/0/0` (the sculpt
   did not take), which is the anti-crater. ✅
4. **Delete the sun** — `destroy_actor` on the `DirectionalLight` ⇒ `removed` + OPPENHEIMER
   flag, verb-blind; restored after. ✅
5. **Property-only (material-swap class)** — light intensity 6→3 ⇒ caught in full with the
   `comp:LightComponent0/intensity` field delta; the SAME change in `spatial` mode is
   correctly MISSED (mode named in the payload). ✅
6. **WP stream-out disclosure** — on the partitioned crater map, a non-empty `removed` fires
   the `removed_note` ambiguity disclosure ✅ (proven on the sun deletion; the differ is
   blind to stream-out-vs-delete by construction, so the disclosure covers both). Forcing a
   clean *synchronous* editor stream-out from Python to exercise the trigger side directly
   was not reachable this session (`unload_actors` refused freshly-spawned + always-loaded
   actors); `get_actor_descs()` reachability for the real split is confirmed. Both recorded
   in G63.

## Author rulings (2026-07-06, closing the implementation questions)

**1. B16 first-create sink → flag-attribution under a STRICT signature; the listing stays
complete.** The other two exits are rejected: filtering the template family hides a real
Landscape sculpt (sink and sculpt are indistinguishable by diff alone — the crater must be
CAUGHT), and pre-hiding before the `before` snapshot leaves a hidden template with no ground
if the create then fails. The exemption is an **attribution, not a silence**: an actor joins
the pure-sink subset iff (i) template Landscape proxy class, (ii) ΔZ exactly the −2 km sink
constant, (iii) hidden-flag transition consistent with B16, (iv) NO other field deltas.
Matching actors remain in `changed` but are summarized as a labeled line — "~128 template
proxies sunk 2 km — B16 self-heal, engine housekeeping, not your op" — and don't count
toward the flag thresholds. **One actor deviating by one field → the exemption is off and
the flag trips normally.** A real sculpt never matches (varied ΔZ, no hide, not the
constant). This is not verb knowledge in the differ; it is the tool attributing its own
documented side-effect, which truth demands anyway.

**2. `full` as the universal default — confirmed.** Cost was the only reason to hedge and
it is measured cheap. Recorded caveat: 0.5 s was at 138 actors and scales with actor count;
if a heavy level hurts, that is a measured re-decision later — the payload names the mode
either way. Do not pre-optimize add/transform.

**3. OPPENHEIMER trip points confirmed as-is** (any removal; max |ΔZ| ≥ 100 m; ≥ 20 actors
changed/removed) — **including deliberate large moves tripping.** The flag is a question;
an occasionally-rhetorical question costs one line, while suppressing "expected" moves would
require exactly the verb knowledge the differ must not have. Tune with evidence if it nags.

**4. `material` stays in DIFFED.** `+0 −0 ~0` on `op=instance` is not nothing — it is proof
of no actor side-effect from an asset-authoring op, for ~1 s, and it future-proofs the day
material assigns to an actor.

**5. Field cap 25 with disclosed `+N more (capped)` — confirmed for the auto-bracket.**
`outliner op=diff` (the explicit diagnostic) additionally gets `verbose=true` for the
uncapped dump.

**6. Steps 3 and 6 are REQUIRED before the spec closes.** Step 3 is non-negotiable — the
spec exists because of the crater: open `/Game/Maps/UEB_SculptCrater`, run a heightmap
import, see the proxies land in `changed` with bounds-Z deltas + flag. Step 6 is amended
since the descriptor split is not built: verify a forced stream-out lands in `removed`
WITH the `removed_note` disclosure firing (the limitation working as disclosed), and log a
gap for the real `unloaded` split.

## Provenance

Born from the SPEC-16 crater session (2026-07-06): heightmap sculpting proved possible over
RC (overturning the G12 "Landscape unscriptable" assumption for heightmap authoring), but
exercising it without trustworthy perception put a quarter of the map underwater and
reported success. The map with the crater is saved at `/Game/Maps/UEB_SculptCrater` as
test fixture #3 for the verification plan. This spec is the diagnostic that had to exist
before controlled sculpting (SPEC-17, TBD) is allowed to touch anything real.
