# SPEC-05 — Verb alignment: UE-native names, legible provenance

> This MCP server aims to accomplish the heroic undertaking of letting an LLM drive UE5
> to completion. Pragmatism is chief among all things: we ship pragmatic, working code
> that is easy to reason about, maintain, and predict — over rigid ideas about how the
> codebase should be.

Status: **DRAFT — fleshed out 2026-07-03, awaiting the user's sign-off.** This spec fixes
the shape of the whole future surface; nothing in SPEC-06..09 (deixis, probes, lint,
runtime lint) should land until the decisions here are agreed, because they all add verbs
and ops that must be born aligned.

Ported doctrine — the two blender-buttons sources, both read in full before this draft:
- `blender-buttons/docs/SPEC-05-verb-collapse.md` — one verb per native surface; lean on
  the model's training data so schemas specify args instead of teaching concepts; the
  taxonomy is self-closing when it mirrors the native UI's own organization; docker-shape
  (one binary per verb, subcommands inside); schema ergonomics (Addendum A).
- `blender-buttons/docs/SPEC-20-verb-provenance.md` — provenance legible at the call
  site; mandatory native-cousin tags; no from-scratch cousin reimplementations;
  provenance derived from the build, never model memory; version anchoring.

## Goal (the user's words, 2026-07-03)

This server will eventually expose **hundreds of tools/ops**. They must be effortless for
the agent to intuit, and the way that stays true at scale is a **near 1-to-1 mapping onto
UE5 constructs**. At ~10 verbs an agent can memorize a private vocabulary; at hundreds it
cannot — the only documentation that scales is the model's own training data, and that
data is written in UE's words. Every op named by its UE construct is an op the agent
already knows before reading the schema; every privately-named op is a permanent tax on
every future session. The taxonomy is also self-closing: when the surface mirrors UE's
own organization, a new op has exactly one obvious home, named by the construct it drives.

## The naming law: a 2×2

Everything in this spec reduces to one matrix. For any verb or op, ask two questions:
*is the thing it drives a UE construct?* and *is the name a UE word?*

|  | **names a UE word** | **names a non-UE word** |
|---|---|---|
| **drives a UE construct** | ✅ NATIVE — the goal state (`foliage`, `transform`, `asset`) | ❌ the **scatter sin** — our word hides the native thing; training-data reflexes can't find it |
| **drives our invention** | ❌ the **landscape sin** — native word promises capabilities we don't have; every trained reflex misfires | ✅ MACRO/SENSE — honest negative-space naming (`terrain`, `feel`, `validate`) |

Both live exhibits came from this repo, one in each forbidden cell:
- **`scatter`** drives UE's Foliage system (`InstancedFoliageActor.add_instances`, minted
  `FoliageType` assets) under a word UE doesn't use. The G40 debugging session had to
  *discover* that scatter = foliage before it could enumerate the user's selection.
- **`landscape`** builds StaticMesh terrain (because UE 5.8 Python cannot author real
  Landscape) under the exact name of the native system it is not. The name invites every
  Landscape reflex in the training data — sculpt layers, paint layers, grass types — and
  the verb can honor none of them.

**The law is fractal: it applies to ops exactly as to verbs.** `foliage op=paint` (UE's
Foliage-mode tool name) is native-cell; `terrain op=carve` (our op on our thing) is
macro-cell; `transform action=nudge` is a small scatter-sin (UE's word is Move) and gets
renamed. Corollary before naming anything: check whether UE has a word for it (against
the build/docs, not memory — R3), and check the word isn't already taken by a *different*
UE concept.

## The shared-language test (the user's addition, 2026-07-03)

The verb vocabulary is not just the agent's API — it is the **spoken language of the
partnership**. The human never reads MCP schemas; they know UE from its UI, tutorials,
and docs. When the agent narrates its work ("I ran a scatter"), a non-UE word leaves the
human with nothing to look at; "I painted foliage" points at a dropdown they can open.
The same alignment that serves the model's training data serves the human's — both
learned UE from the same corpus.

This adds two tests to the 2×2:
- **NATIVE cell, tightened:** the UE word should be one the human can literally SEE in
  the editor UI — a mode label, panel title, menu entry, or component name — not merely
  API vocabulary. (The current roster passes: foliage/outliner/level/play/viewport/
  transform/select/add/asset/material/spline/history are all UI-visible labels.)
- **MACRO/SENSE cell, tightened:** "any non-UE word" is not enough — blender-buttons'
  `clad`/`graft`/`flute` don't collide with Blender and would STILL leave a human blank.
  Our inventions must be **ordinary, self-describing English**: `terrain`, `carve`,
  `reseed`, `feel`, `validate` all survive being spoken aloud in a sentence with no
  glossary ("I carved the terrain along the trail").

Litmus for every future name: say the sentence "I <verb>ed the <op>…" to the user. If
they'd have to ask what it means, the name is wrong — even if the 2×2 cell is right.

**Agent-only verbs (the user's ruling, 2026-07-03).** Custom verbs are permitted for
functionality specific to the AGENT — senses that exist because the agent is blind
(`feel`, `validate`). The human never conceptually invokes these, so they are exempt
from the UI-visible-label bar; the plain-English bar still applies (their results get
narrated: "feel says the gap is 12 cm" must parse). This is bb's SENSE family, stated
as a rule: an agent-only verb is legitimate exactly when there is NO UE surface for
what it does — the moment UE ships one, the verb becomes a cousin and R2 applies.

**Pragmatism clause (the user's ruling, 2026-07-03).** The law is a default, not dogma.
Deviating from the UE word is fine when the agent and server are OBVIOUSLY better off
and the reason is easily defensible — `landscape`→`terrain` is the canonical example:
the UE word actively mis-teaches, so leaving it is the harm. What is banned is
**arbitrary uniqueness** — a different word with no defense beyond taste or habit
(`scatter` when Foliage exists, `nudge` when Move exists). Operational form: every
deviation carries its one-sentence defense in the schema (the R1 cousin line usually IS
that defense); a deviation that can't state its defense in one sentence reverts to the
UE word.

We deliberately do NOT adopt blender-buttons' `buttons-<purpose>-macro` verb-name prefix.
bb needed a namespace to group ~31 macros living among ~150 native ops; we have a handful
of macros and the negative-space rule already prevents impersonation. Instead every macro
verb/op carries a **MACRO tag as the first line of its schema description** (see
ergonomics below). Revisit if the macro count ever grows past a dozen.

## The shape: verbs → ops, and nothing in between

- **Root verbs are MCP tools, bounded by UE's own surface list** — editor modes, main
  panels, main-menu entries, named systems. The set can only grow when we take on a new
  UE surface (Sequencer, Niagara, Blueprint, …), which is exactly when growth is honest.
  Expected steady state: ~20 verbs, hundreds of ops.
- **Ops are the second and last level.** One discriminator param, named **`op`** on every
  verb — the current `op=`/`action=` split is an unforced inconsistency and dies in this
  spec. No sub-verbs, no third level: if an op wants sub-modes, those are params. The
  docker analogy holds: `docker container prune --filter`, not `docker container prune
  images`.
- **No new flat tools per op, ever** (bb's rejected alternative: separate tools re-inflate
  the count; `oneOf` unions render inconsistently across MCP clients). One verb = one
  tool = one readable schema.
- **Senses keep plain non-UE names** (`feel`, `validate`) — nobody mistakes them for menu
  items, and they are the house style shared with the sister project.

## The verb roster

### Now (the rename/redistribution cutover)

| Verb | UE construct (provenance) | Ops after cutover | Change |
|---|---|---|---|
| `add` | “+ Add” / Place Actors panel (NATIVE) | spawn by asset/class, relational `place=` grammar | keep — ergonomics never demote a native op (bb litmus) |
| `select` | editor selection / Select menu (NATIVE) | `op=set` (labels), `op=clear`, `op=user` — read the USER's live selection (SPEC-06 deixis) | gains `op` discriminator; deixis lands here |
| `transform` | Move/Rotate/Scale gizmos + Details▸Transform (NATIVE) | `op=move` (was `nudge`), `op=rotate`, `op=scale`, `op=resize` (ours: absolute world-dims; tagged) | rename `nudge`→`move`; `action=`→`op=` |
| `asset` | Content Browser / Asset Registry (NATIVE) | `op=packs / inventory / describe / find / whats_new` | `instance_material` moves out (→ `material`); `action=`→`op=` |
| `material` | Material / Material Instance editors (NATIVE, **new**) | `op=instance` (from asset), `op=assign`, `op=params`; later the G40 motion certificate reads | born aligned; small at first |
| `foliage` | **Foliage editor mode** (NATIVE — wraps `InstancedFoliageActor` + `FoliageType`) | `op=paint` (was create — UE's tool name), `op=erase` (region remove), `op=reseed` (was regenerate; our word, our concept), `op=describe`, `op=remove` | **rename of `scatter`** — the exhibit-A fix |
| `terrain` | — (MACRO; cousin: UE Landscape, unauthorable from Python in 5.8) | `op=create / shape / flatten / describe / remove` + **`op=carve` (moves in from `path`)** | **rename of `landscape`** — the exhibit-B fix |
| `spline` | SplineComponent (NATIVE) | `op=create` (points/route), `op=describe` (waypoints, `at_fraction`), `op=surface` (macro op, tagged: the visible strip), `op=remove` | **rename/refactor of `path`**: the curve is native; carving terrain along it belongs to `terrain op=carve along=<spline>` |
| `outliner` | the Outliner panel (NATIVE) | `op=census` (default scene read), `op=reconcile` (ours, tagged: ueb-registry diff/GC) | **from `scene`** — UE has no user-facing “scene”; the actor census IS the Outliner |
| `level` | Level / World Settings / World Partition (NATIVE) | `op=streaming` (from scene), SPEC-04 lifecycle (`new/save/load/list`) as it lands | **from `scene`** + SPEC-04 home |
| `play` | Play In Editor (NATIVE) | `op=census` (was scene `pie_census`), `op=start / stop`; SPEC-09's scripted runs later | **from `scene`**; B8 PIE-guard doctrine lives here |
| `viewport` | the Level Viewport camera (NATIVE — **no pixels, ever**) | `op=camera` (get/set pose), `op=frame` (aim at actor/region), `op=looking_at` (trace the user's view — SPEC-06 deixis) | reinstated WITHOUT vision: pose/frustum math only. `feel op=framing/visible` stay in `feel` — they are geometric senses about any hypothetical eye, not reads of the user's actual one |
| `history` | Edit▸Undo History / transaction stack (NATIVE) | `op=list / undo_to` | keep |
| `feel` | — (SENSE) | `describe / distance_between / gap_between / is_aligned / render_state / framing / visible` | keep; plain name by law |
| `validate` | — (SENSE) | `run / expect / forget / intended`; SPEC-07/08 add the rule engine + `scope=selection\|label\|all` sweeps | keep |

The `scene` verb dissolves entirely — its four ops were an outliner read, a
world-partition read, a PIE read, and our registry reconcile, i.e. four different UE
surfaces sharing a non-UE word. That dissolution is the strongest single proof the law
finds real seams.

### Reserved (future UE surfaces — names claimed now so nothing squats on them)

`sequencer`, `niagara`, `blueprint`, `build` (Build menu: lighting/nav/HLOD),
`modeling` (Modeling editor mode / Geometry Script), `fracture` (Chaos), `mesh_paint`,
`data_layers`, `pcg` (if its Python surface matures — see the foliage ruling), `landscape`
(reserved for the REAL system if Python ever authors it — the strongest reason `terrain`
must not wear the name). Environment lighting (sun/sky/fog/clouds) needs no verb: those
are placed actors (`add` + future `details`) and UE's own grouping surface is the Env.
Light Mixer panel — decide when the need is live, against the build.

### Capacity audit (2026-07-03): does the pattern carry 300–500 ops?

Yes — estimated per-verb op inventories, from what each UE surface actually contains:
`asset` 25–40 (Content Browser: import/migrate/redirectors/references/audit/collections…),
`material` 15–25, `foliage` 15–20 (paint family + FoliageType settings), `level` 10–20,
`terrain` 10–20, `transform` 10–15, `spline` 10–15, `outliner` 10–15, `play` 10–15,
`select` ~10, `viewport` 8–12, and `add`/`validate`/`feel`/`history`/`build` 5–15 each —
**~150–220 ops on the current roster alone**. Reserved surfaces carry the rest:
`sequencer` 20–30, real `landscape` 20–30, `modeling` 30–50 (Geometry Script), plus
`blueprint`/`niagara`/`pcg`/`fracture`/`data_layers` ~10 each — **~350–500 total at
~25 verbs**. The load-bearing fact: it is UE's own information architecture organizing
the count, not our taxonomy — the editor organizes thousands of operations this way.

Two flagged obesity risks: `modeling` and `sequencer` are whole applications wearing a
verb. If either bloats, UE itself provides the split seams (Modeling mode's native tool
palettes: Create / PolyModel / Deform / UVs / Bake) — even the failure mode resolves to
UE's taxonomy, not an invented one.

### `details` — the one genuinely hard call (deliberately deferred)

UE's Details panel is the per-actor/component property editor — arguably the most-used
surface in the editor, and a natural `details op=get/set path=…` verb. Deferred because
it is a **god-verb risk**: every future verb's ops could be expressed as details-sets,
and the moment lazy op-design starts routing through raw property paths, the aligned
surface rots from inside. Rule if/when it lands: `details` is the escape hatch for the
long tail, and any property set the agent reaches for twice gets promoted into a real op
on its owning verb.

## Schema ergonomics (bb Addendum A, ported and extended)

1. **`op` is a `Literal`** → the schema emits an enum; legal ops are structural, not prose.
2. **Every op-specific param is tagged** `tag(T, "[op] …")` so the fat signature filters
   down per op.
3. **Args stay regular across ops** — shared vocabulary (`label=`, `at=`, `place=`,
   `region=`, `along=`) identical across verbs; a verb's params are never a union of
   unrelated signatures.
4. **R1 cousin line** — first line of every MACRO verb/op description:
   `MACRO ≈ <UE feature> — <what differs>`. E.g. `terrain`: “MACRO ≈ UE Landscape (Python
   cannot author Landscape in 5.8) — StaticMesh terrain; no layers, no grass types.”
5. **Per-op API citation** — each op's docstring line ends with the `unreal.*` surface it
   drives: `paint — InstancedFoliageActor.add_instances`. This makes provenance legible
   at the call site (SPEC-20's core demand) and is verified against the code during the
   audit, not recalled.
6. **The status block is a hard invariant** (SPEC-02/03, unchanged by any rename): every
   act-verb reply carries it; senses don't. The two forced senses and the render line
   survive the cutover untouched.
7. **The schema weight budget (the user's ruling, 2026-07-03).** Fat schemas are the
   accepted price of ~350–500 ops behind ~25 tools — but the fat is op COUNT, not prose.
   The model must be able to GUESS an op's behavior from its name plus a one-line
   summary; that's what the alignment buys, so spend it. Concretely:
   - **Document the delta, never the concept.** `foliage op=paint` needs zero words
     explaining what foliage painting is — training data owns that. It needs only what
     differs here: our region grammar, the author-time motion gate, cm units. Schema
     length is proportional to **distance from UE**, not to functionality size: native
     ops are nearly free; macros pay full documentation freight (which is itself
     pressure toward native design).
   - **One line per op**, ending in its API citation. Params whose names are guessable
     (`density`, `region`, `seed`) get no prose; only non-obvious params earn a tag.
   - **No defensive robustness** — no exhaustive constraint prose, no re-stated
     defaults, no "must be positive" boilerplate. A wrong guess should be corrected by
     a self-correcting error (the established enumerate-the-valid-values pattern), not
     pre-empted by documentation the model pays for on every single call. Runtime
     errors are paid once when hit; schema prose is paid every turn forever.

## The vision: ground truth throws itself at the agent (HATEOAS)

The user's statement of the ultimate goal (2026-07-03): get ground truth to the agent as
easily as possible — the relevant data should practically THROW ITSELF at the agent, and
staying in intent space should be effortlessly trivial. The mechanism, borrowed from
REST's HATEOAS: **every finding, warning, and state read carries the next legal move as
a ready-to-fire MCP command.** A `validate` finding doesn't just describe the defect —
it says "here's the error → if you want to change it, here's the command:
`material op=params target=… wind_weight=0`". The agent never translates a finding into
a verb call by reasoning; the response already contains the affordance.

This is the through-line of everything already built and everything planned: the status
block (ground truth after every act), the forced senses (perception you can't skip),
self-correcting errors (the valid values arrive WITH the failure), the author-time gate
(the warning arrives WITH the two escape-hatch commands), and SPEC-08's findings format
(every finding names its fix command). Verb alignment is this vision's precondition: an
affordance is only effortless if the command it hands you is one you — and the human —
already understand on sight.

And it goes beyond the reactive cases (errors, warnings). The full form (the user,
2026-07-03): **the server's herculean deterministic compute lavishly feeds the agent
affordance grapes.** The server PRECOMPUTES the action space so the agent never derives
it. The worked example: modular building assets — the server precalculates the snappable
joints, so the agent asks "I have this wall piece, what are its snappable joints?" and
receives the joints by id + description, ranked by proximity to the work site, WITH an
example snap command ready to fire. The agent's move is pure intent selection ("snap the
east joint to the corner post"); every coordinate, tolerance, and rotation was
deterministic compute the server already did. Division of labor, stated once: **anything
deterministically computable is the server's job to compute and serve unasked; the
agent's context is spent exclusively on intent.** (UE even hands us the native construct
for the worked example: StaticMesh **Sockets** — precomputed snap points would surface
under the native word, `asset op=sockets`.)

## How the MCP feels to use (the target experience)

A UE-fluent agent lands with zero repo priors and works from reflex:

```
asset op=find query="pine"                 → families, dims, tris, motion/spire tells
add label="cabin" asset="Cabin_A" place="ground" at="map:C4"
terrain op=carve along="valley_trail" blend_margin=400
foliage op=paint meshes=["Bush_Tree","Bush_1"] region=… density=…
   ⚠ 2 mesh(es) carry vertex-masked wind … the safe kind      ← author-time gate (G39/G40)
   [status block: outliner delta, feel delta, render line]
validate op=run scope=all                   → rule-engine findings, numbered, actor-labeled
play op=census                              → game truth; auto-ends PIE (B8)
select op=user                              → “the user has 1 actor selected: …” (deixis)
```

Every noun in that transcript is a UE noun. The agent never asks “which verb owns X?” —
the answer is “whichever UE surface owns X,” which it already knows. The inverse also
holds and matters as much: when the agent reads UE docs/forums to solve a problem
(“use the Foliage fill tool”), the solution's vocabulary IS the verb surface's vocabulary
— no translation layer in either direction.

“The verb is the mode context” (bb's auto mode-switch) translates to UE as **world-state
guards, not editor modes**: Python drives systems directly, so act-verbs instead
auto-handle PIE (end Play before mutating — B8 standing doctrine, owned by `play`),
game-thread dispatch, and level-loaded checks. The agent never hand-manages editor state.

## Rules (ported, UE-translated — unchanged from the stub, now with teeth)

- **R1 — native-cousin tag, mandatory** (ergonomics rule 4 above).
- **R2 — no from-scratch cousins.** If UE ships it and Python can drive it, wrap it.
  Ruling made now: **`foliage` wraps the Foliage system, not PCG.** PCG is 5.x's modern
  procedural-scatter, but its 5.8 Python surface is thin where Foliage's is proven
  (add_instances works today). `foliage` carries a PCG cousin tag; revisit when PCG's
  Python matures (R3 check, not a memory check).
- **R3 — provenance from the build.** Native-vs-macro is read from the verb's actual
  `unreal.*` calls; cousin claims verified against the live 5.8 build. Today's proof of
  necessity: three model-memory misses in one session (`validate_loaded_asset` absent,
  `has_vertex_colors` unexposed, mesh-description API absent).
- **R4 — version anchoring.** The server instructions carry a version-stamped “UE 5.8
  deltas vs your reflexes” primer (seed: no Landscape authoring from Python, no numpy in
  the editor venv, no Spline+HISM component-add, the three R3 misses above; grows as the
  audit finds more). First dispatch of a session compares attached UE version to the
  verified-against version and warns on drift.

## Migration plan (staged, each stage live-verified then pruned from here)

1. **Discriminator unification** — `action=` → `op=` everywhere; `transform nudge→move`.
   Mechanical, one commit, recipes/docs updated in the same commit.
2. **The two headline renames** — `scatter`→`foliage` (ops: paint/erase/reseed/describe/
   remove), `landscape`→`terrain`. State keys, persisted registries, and
   `dogfood_levels.md` recipes migrate in the same commit; G40's author-time gate lands
   on `foliage op=paint` when SPEC-07 builds it.
3. **The `scene` dissolution** — `outliner` (census, reconcile), `level` (streaming +
   SPEC-04 lifecycle), `play` (census/start/stop). `scene` dies in the same commit the
   three are born; no alias period (a wrong-cell name kept alive keeps mis-teaching).
4. **`path` → `spline` + `terrain op=carve`** — the carve op moves to the thing it
   mutates; the spline keeps the curve, waypoints, and (tagged macro op) surface strip.
5. **Ergonomics pass** — Literal `op` enums, `[op]` param tags, R1 cousin lines, per-op
   API citations, on all verbs.
6. **R4 anchoring** — primer + drift tripwire.
7. **New verbs** (`material`, `select op=user`, `viewport`) land with SPEC-06+, born
   aligned.

Renames are breaking; there is exactly one consumer (this partnership), the surface is
young, and every day of delay adds recipes/docs/gaps written in the old words. Cut hard,
no deprecation shims. `guidance_for_llms` / README / CLAUDE.md sweep rides stage 5.

## Verification story

- **The schema-only test** (bb standard): a fresh agent with no repo priors, given only
  the verb list and schemas, correctly (a) predicts what each verb drives, (b) reaches
  for the right verb from UE-phrased requests — “paint some pines on the hillside” →
  `foliage`, “flatten a pad for the cabin” → `terrain op=flatten`, “what is the user
  looking at?” → `viewport op=looking_at`. Run it as a real probe: a clean-context
  subagent quizzed against the post-cutover schemas.
- **The live pass**: every renamed/redistributed op dispatches over the RC bridge with
  behavior identical to its pre-rename twin (same handlers underneath — the cutover moves
  names, not engine code), status block intact, history/undo intact.
- **The audit artifact**: the roster table above, with every op's API citation confirmed
  by reading the handler — committed as part of this spec when the cutover lands.
- **The human test**: every verb/op name is either a label visible in the editor UI or
  ordinary English — checked by reading each name aloud in a work-narration sentence;
  none should require the user to ask "what's a ___?".

## Open questions for the user

1. `outliner` vs keeping `scene` for the census read — the law says outliner; the
   counterargument is that `scene` is cross-DCC lingua franca. (Recommendation: outliner.
   We are optimizing for UE training data, not DCC generality.)
2. Should `viewport` land now (it is small and SPEC-06 wants it) or with SPEC-06?
   (Recommendation: with SPEC-06 — no speculative verbs, even aligned ones.)
3. `details` — agree to defer under the god-verb rule above?
4. Op-level names where UE has no word (`reseed`, `carve`, `whats_new`) — any the user
   wants renamed while renaming is cheap?
