# SPEC-02 — The status block, REPL-style

Status: **core implemented + live-verified 2026-07-02** (see "Implementation status"
below). Ground truth: blender-buttons' SPEC-16 ("the two forced senses") and `_core.py
_status()` — read both before extending. Spatial lint is a *part* of this spec, not the
other way around.

## Sequencing (SPEC-02 → SPEC-03)

SPEC-02 goes first; SPEC-03 (render legibility) is authored as "the third forced sense"
and is a strict extension of the machinery here — it adds a `render:` line to this status
block and reuses this spec's `expect()` suppression grammar, channel discipline, and
provenance. It has no coherent home until the two-senses scaffold exists. The one SPEC-03
primitive that must land *inside* this spec's foundation is the **renderability-gated
read**: this floor runs its own traces (ground check) and AABB reads, and if those reads
aren't filtered to renderable actors they inherit the invisible-poison bug SPEC-03 exists
to kill (blender-buttons G147 — a hidden mesh chosen as a support surface). The
`[N excluded]` slot on the validate line (below) is already wired for that predicate;
SPEC-03 fills it. Build order: SPEC-02 scaffold + the minimal source-filter → SPEC-03's
full render sense on top.

## Why this is the spec that matters

In every review of blender-buttons ever run, the status block was the single most
praised element — above the placement DSL, above the verbs. The reason: it turns MCP's
call-and-response into a REPL. The agent acts, and in the same round-trip *sees* —
state, what changed, what's now broken. It never operates blind, never has to remember
to look, and can never mistake silence for success. That loop, not any individual
check, is what we're porting.

The root cause it solves (SPEC-16's diagnosis — port the reasoning, not just the
mechanism): **the model is a reactor, not an inspector.** It reacts brilliantly to
information put in front of it; it almost never elects to go *get* information it
wasn't handed — and the disposition that skips inspection is the same one that makes
it productive. So diligence cannot live in the model: any design that asks it to
*decide* to verify fails exactly when it's in flow. Perception and correctness must be
pushed into every response, forced.

Corollary that shapes the anatomy: the per-op block is a **single-object spotlight**
(the acted-on actor + scene globals). A relational defect — z-fight, penetration —
needs two objects and the relation between them, so it can *never* appear in the
spotlight; without a separate forced channel its absence reads as "all good" and
manufactures false confidence. That's why validate is its own sense, not more fields
on the block.

## Anatomy (blender-buttons' proven channel order, translated to UE)

Every mutating verb returns: result text → warnings → the two forced senses →
re-ground (periodic) → the status block. Read-only verbs (`feel`, `asset`, `view`)
carry no block — they ARE perception.

1. **Warnings channel** (ahead of the block so they're never lost):
   - *no-op warning* — a mutation that changed nothing can never masquerade as a
     successful edit.
   - *degraded-success warning* — the op worked but harmed something (UE analogues:
     spawn succeeded but overlaps everything; scatter placed 0 instances because rules
     excluded the whole region).
   - generic postcondition `notes` (auto mode-switches, fallbacks taken).
2. **Sense 1 — `feel` delta**: what you just changed, as perception, no verdict
   ("cabin_2 now rests-on terrain, flush-with pad edge").
3. **Sense 2 — `validate` line**: the always-on correctness floor, report-by-exception.
   This is where spatial lint lives (below). One line when clean; findings when not.
   **If the floor is disabled it must say so on every block** ("validate: OFF — floor
   is down") — silence-because-off must never read as silence-because-clean.
   Presentation discipline (blender-buttons `validation.py _render_line`): findings
   list the **new delta only**, capped (~4) with the remainder as a count; declared
   intents collapse to a count ("3 intended"), never re-listed; and the line ends
   with `[N excluded]` when the floor skipped non-renderable actors (SPEC-03's
   predicate) — the floor is never silent about its own blind spots.
4. **Re-ground recap**: after enough churn, a compact scene recap + "re-read anything
   you haven't felt in a while before building on it." blender-buttons triggers on
   *weighted drift*, not raw mutation count (G117) — copy that.
5. **The block itself**: level (dirty/saved), acted_on vs viewport-active (bounds
   always describe the acted-on actor — blender-buttons G76), selected, dims (world
   AABB, rotation-aware, cm), bounds per axis, rot (yaw/pitch/roll), last_action
   {id, verb, summary}. Scatter groups render as one line ("1,847 instances,
   3 species"), never as rows.

Two conventions from around the block, kept:

- **Provenance**: every measurement any verb returns names its source ("↳ measured on
  cabin_2") — a number is never silent about what it was measured on. UE flavor: which
  actor/component, and whether simple or complex collision answered the trace.
- **Scope**: the floor runs after *geometry/placement* ops, not literally every op — a
  rename validates nothing. Declared intents are level-scoped (a "path↔terrain"
  blessing is a fact about this level, cleared on level load); only telemetry persists.

## The validate floor: spatial lint (UE edition)

Runs automatically on the touched delta after every mutation; whole-scene on demand.
UE makes this cheap — traces and penetration depth are native.

- **Ground relationship**: trace from actor base vs terrain — buried/floating, with
  delta AND fix ("base at z=0, terrain 5540 cm above → set z=5540"). Findings always
  carry the corrected value: the trace that found the problem knows the fix.
- **Penetration**: AABB fast pass → penetration depth ("penetrates rock_07 by 12 cm
  along −Y → nudge north 12 cm").
- **Z-fight**: coplanar-overlap heuristic (parallel overlapping faces within ~2 mm) —
  kit walls in the same plane, floors at exact terrain height, duplicate transforms.
- Scatter instances validate at generation time (the per-point trace already runs);
  sweeps sample rather than exhaust.

## Suppression discipline (port verbatim — this is load-bearing)

blender-buttons allows **no "ignore"**. The only way to quiet a finding is a positive,
justified declaration: `validate(op="expect", a=..., b=..., reason=...)` — the reason a
falsifiable design claim ("path gravel seats 3 cm into terrain by design"), optionally
depth-bounded (`max_depth`) so a blessed 3 cm clip can't hide an 11 cm one. Intent-free
defects — z-fights, duplicate transforms — are never suppressible at all. Contact
within the resting/flush epsilon (≲1 cm, consulting `feel`'s relations) is not a
finding in the first place.

Two refinements from blender-buttons that matter *more* at UE scale:

- **Class-level declaration + the G125 hint** (`validation.py:556-570`): `expect`
  accepts a population/group subject, not just an actor pair — and when ≥6 new
  findings all involve one substrate, the floor *offers* the class declaration in a
  hint ("2,314 of these involve 'terrain' — if it's a settled scatter, declare
  scatter:trees↔terrain once") instead of leaving the agent to bless instances one
  by one. In UE this is load-bearing, not convenience: a single scatter is thousands
  of terrain contacts; per-instance blessing is impossible by design, per-class
  blessing is one reasoned line.
- **Bidirectional tripwire** (`validation.py:543-554`): a declared-intended contact
  that *vanishes* is itself a finding ("intended clip path↔terrain no longer
  present"). Blessings can't rot silently, and over-blessing produces a visible
  pile, not quiet. Auto-GC declarations whose subject no longer exists
  (`_prune_dead_intents`) so a deleted actor never leaves a permanent tripwire.

## Sweep tier

`validate(op="run")` over the whole scene (or targets) — compiler-style verdict:
"PASS — 214 actors, no issues" or findings, one per line, each with its fix. Run
before screenshots and at milestones. Severity: errors + warns inline; notes
sweep-only. Silence discipline: clean = one line; no lint section that always prints.

## Non-goals

Aesthetic judgment (Ryan's), render-artifact detection beyond the coplanar heuristic,
physics-sim correctness, perf budgets. M1's status block already exists — this spec
upgrades it to the full two-senses form rather than inventing a new mechanism.

## Implementation status (2026-07-02)

Landed in the runtime and live-verified over the RC bridge. New module
`runtime/ue_buttons/validate.py` (the floor + intent registry + feel delta + drift
re-ground), the registry/accumulator in never-reloaded `_state` (`intents`, `drift`), the
full anatomy in `verbs._status_block`, a `validate` verb, and the `validate` MCP tool in
`server/main.py`.

**Done + verified live:**

- The REPL block on every mutating verb: warnings → Sense 1 (`feel:` delta) → Sense 2
  (`validate:` line) → periodic re-ground → the single-object spotlight (acted-on bounds,
  blender-buttons G76). Read-only verbs carry no block.
- The three detectors, each finding carrying its FIX, rebuilt on UE AABB + world trace
  (cm): **ground** (`floater floats 350.0cm above ground … → drop base to z=200.0`;
  buried is symmetric; a trace miss is an HONEST "can't verify", never a silent pass —
  closes the B3 class of silence), **penetration** (`jammer penetrates probe_a by 40.0cm
  along X → nudge [40,0,0]`), **z_fight** (coplanar overlapping faces; full coincidence →
  "DUPLICATE transform").
- Suppression grammar: `expect` requires a reason, rejects intent-free `z_fight`, collapses
  a blessed contact to a count ("1 intended"), honours a `max_depth` envelope (deeper than
  blessed still fires), and a tag token blesses a whole class. `forget` retires it.
- Bidirectional VANISHED tripwire (a declared contact that moves apart fires), the ≥6
  class-declaration hint (blender-buttons G125), auto-GC of dead-subject intents.
- Sweep tier `validate op=run [targets] [verbose]`; report-by-exception (`validate: clean`
  when clean, `[N excluded]` slot reserved for SPEC-03's predicate).

**Deliberately deferred (honest gaps, tracked):**

- **Spatial-verb floor** — `landscape`/`path`/`scatter` currently ANNOUNCE that the actor
  floor is off for the edit ("validate: OFF for this edit — … `validate op=run` to sweep")
  rather than validating at generation time. SPEC-02 wants scatter instances validated as
  they're placed (the per-point trace already runs) and a terrain reshape to re-flag actors
  it buried. Next milestone.
- **Provenance line** — the block names the acted-on actor, but a returned trace does not
  yet carry `↳ measured on <actor/component>, simple|complex collision`. SPEC-20 shape.
- **Registry lifetime** — `intents`/`drift` live in `_state`, so they survive a hot-reload
  but not a level change (no level-load hook — gaps.md G16). Persist-into-level +
  clear-on-load is future, shared with SPEC-03's state reconciliation.
