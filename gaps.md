# gaps.md — ue-buttons

Every friction point the agent hits while driving UE becomes a numbered gap here.
Ported discipline from blender-buttons: a gap is **fixed and live-verified against the
running editor**, then **PRUNED from this file** — a completed gap is deleted, not left
behind with a FIXED banner. This file is the live worklist of what's still friction; the
reasoning behind a resolved gap lives in git history and the code, not here. "Verified"
means the fix was exercised over the RC bridge and the log/screenshot/`feel` confirms the
new behavior — not that it compiles. `G<n>` numbers are never reused (grep git history for
a retired one). Keep the reasoning while a gap is open, not just the diff.

Format: `### G<n> — <title>` · status line · what/why · resolution.

Gaps are *friction / missing-capability / design*. Outright defects go in `bugs.md`.

---

### G30 — no job/progress pattern for slow mutations: one pathological asset load can still outrun the HTTP timeout
Status: OPEN (successor to B6, 2026-07-02 — the two concrete offenders are fixed, the
general pattern isn't built. Reviewed 2026-07-03: deliberately deferred again — the
remaining wedge is a SINGLE atomic game-thread asset load, which even a tick-based job
can't chunk (the next dispatch would stall behind it on the game thread anyway); build
the async job + progress pattern when a new concrete offender appears to shape it,
not speculatively.)

B6's fixes hold: `terrain op=carve` batches its flatten features into ONE mesh rebuild (38-disc
carve round-trips in <0.5 s, was ~30 s dark), and `asset inventory measure=True` bounds each
batch by wall-clock (`seconds=`, default 20 s) as well as count. But the wall-clock check
runs BETWEEN mesh loads — a single cold Nanite mesh whose first load takes >60 s would still
wedge the bridge, and any future long game-thread verb inherits the same trap. The general
cure is an async job + progress pattern (kick the work off the dispatch path, poll a
`job_status`), or per-verb chunking as each new slow path appears. Until then: after any
timeout, poll `/remote/info` and RE-READ state before re-issuing — timed-out work usually
completed invisibly.

### G48 — placement inside covered space: ground-snap seats actors on the covering geometry
Status: OPEN (found 2026-07-04, L2 dogfood — the exact soft spot the level brief predicted)

Placing the cabin walls at 2D map points *inside the grotto* seated all four on top of the
cave roof slabs: `_place_actor`'s ground snap traces downward from high above, and the first
hit under open sky is the lid, not the floor beneath it. Meanwhile the validator's own
ground check happily reported "floats above ground z=-61.8" for the same actors — the two
traces disagree about what "ground" means under cover. Worked around with explicit
`transform op=move` deltas derived from measured bases. Candidate cure: multi-hit down-trace
that seats on the LOWEST surface that can host the actor's height (or a
`place={"under_cover": true}` opt-in); at minimum the placer and the validator must agree on
which surface is "the ground" so a fresh add can't be born 18 m in the air.

### G49 — no interior/enclosure perception: composing negative space is done blind
Status: OPEN (found 2026-07-04, L2 dogfood)

A cave is negative space, and nothing in `feel` can sense it: hollowness of a kit piece
(is `SM_Tunnel_Cave_9` open-topped? where's its opening?), enclosure of an assembled
chamber (does the lid leak sky?), interior clearance (how much room for a cabin?). All
three had to be answered with hand-written line-trace probes over the bridge — twice.
The probes worked (found the open top, found the skylight holes in `SM_Tunnel_Cave_4`,
verified the sealed lid numerically), which proves the sense is buildable. Candidate:
`feel op=clearance at=[x,y,z]` — a ray fan reporting floor/ceiling/wall distances per
bearing plus sky leaks. Numbers only; fits the vision policy exactly.

### G50 — no lighting surface: a cave interior is pitch black and the agent can't even say so
Status: OPEN (found 2026-07-04, L2 dogfood — predicted verbatim by the level brief)

The L2 cabin sits inside a sealed rock chamber lit only by what bounces through a 5 m
mouth. The verb surface has no way to author a light (the template sun/skylight are the
only sources, and they're outside), and no way to *perceive* darkness (perception is all
geometry — nothing reads luminance at a point). Two gaps in one: an authoring verb
(`add what=point_light` family or a `light` verb — SPEC-worthy, UE owns the word Light)
and a numeric light-level sense to make "it's too dark in here" a measurable finding
instead of a human complaint. PIE-tier check candidate for SPEC-09.

### G51 — terrain feature vocabulary cannot say "steep": no wall-steepness control on valley/ridge
Status: OPEN (found 2026-07-04, L2 dogfood)

The natural encoding of a slot canyon — `{"kind":"valley","floor_width":600,
"wall_height":3500}` — produced a 19°-max broad wash: the valley feature spreads its wall
over the entire remaining half-width. There is no parameter that narrows the wall run.
Workaround that shipped L2: two flanking `ridge` features (radius 2200, height 3800) gave
honest 61–69° walls, but the composition is a trick you have to know, and the result is
"two long mounds on a plain" rather than "a slit cut into a plateau". Candidate:
`wall_width` (or `steepness`) on the valley feature, and document the ridge-pair recipe
until then.

### G52 — the tag-blessing affordance is unfireable: no verb writes actor tags
Status: OPEN (found 2026-07-04, L2 dogfood)

When a placement produces N same-class contacts, the status block advises: "tag the
instances and `validate op=expect a=<tag> b=…` to declare the whole class at once."
No verb can apply that tag — the only tags actors carry are the runtime's own. The
affordance violates the house HATEOAS rule (every suggested next move must be fireable);
L2 fell back to the built-in `ueb` tag (too broad) and pairwise declarations (6 calls
where 1 was advertised). Either add `tags=` to `add`/`select op=set`, or reword the
affordance to advertise only what exists.

### G53 — nothing tells the agent a surface is wearing the engine-default material
Status: OPEN (found 2026-07-04, L2 dogfood — caught by the USER, which is the failure)

L2 shipped with the canyon terrain wearing the default grid: `terrain op=create` was
called without `material=` and nothing ever surfaced that. The user had to SEE it —
precisely what the numbers-only perception contract exists to prevent. The tell is fully
mechanical: a ueb-authored surface (terrain, spline strip) whose slot-0 material is the
engine default (WorldGridMaterial / DefaultMaterial) or empty. Candidates, cheapest
first: a `render:`-line style note on terrain/spline results ("wearing the engine
default — pass material="), and a `degrades` row in the SPEC-08 lint sweep so
`scope=all` catches it at handoff. Fix applied to L2 itself (MI_Rock_1, uv 600) —
the gap is that no sense ever said so.
