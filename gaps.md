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

First built instance of the pattern (SPEC-10, 2026-07-05): `pcg op=generate` is
two-call fire/collect. PCG generation is ASYNCHRONOUS — the graph advances only on the
editor's tick, which a single blocking dispatch can't force (Python holds the game
thread), so an in-call poll can never observe completion. So generate FIRES the graph and
returns `{"pcg":"generating"}`; the next call with the same label COLLECTS the settled
per-mesh census and applies the WPO cure (mirrors `play op=census`'s two-step). This is
the async-job shape for a verb whose slow work is off-thread; the still-open wedge below
is the different case — a single ATOMIC game-thread load that no fire/poll split can chunk.

B6's fixes hold: `terrain op=carve` batches its flatten features into ONE mesh rebuild (38-disc
carve round-trips in <0.5 s, was ~30 s dark), and `asset inventory measure=True` bounds each
batch by wall-clock (`seconds=`, default 20 s) as well as count. But the wall-clock check
runs BETWEEN mesh loads — a single cold Nanite mesh whose first load takes >60 s would still
wedge the bridge, and any future long game-thread verb inherits the same trap. The general
cure is an async job + progress pattern (kick the work off the dispatch path, poll a
`job_status`), or per-verb chunking as each new slow path appears. Until then: after any
timeout, poll `/remote/info` and RE-READ state before re-issuing — timed-out work usually
completed invisibly.

### G50 — no lighting surface: a cave interior is pitch black and the agent can't even say so
Status: OPEN (found 2026-07-04, L2 dogfood — predicted verbatim by the level brief)

The L2 cabin sits inside a sealed rock chamber lit only by what bounces through a 5 m
mouth. The verb surface has no way to author a light (the template sun/skylight are the
only sources, and they're outside), and no way to *perceive* darkness (perception is all
geometry — nothing reads luminance at a point). Two gaps in one: an authoring verb
(`add what=point_light` family or a `light` verb — SPEC-worthy, UE owns the word Light)
and a numeric light-level sense to make "it's too dark in here" a measurable finding
instead of a human complaint. PIE-tier check candidate for SPEC-09.

### G62 — the agent keeps falling back to raw `scripts/probe.sh` editor Python for whole capability categories the verb surface doesn't cover
Status: OPEN (found 2026-07-05, UEB_ScenicWood dogfood)

Driving a real level to completion repeatedly forced hand-written editor Python over
`scripts/probe.sh py '...'` — *outside* the legible intent-driven verb surface: unverifiable
by the status block / `feel` / `validate`, invisible to `history`, unreplayable, and
un-requestable by the user (they can only ask ME; there's no verb behind it). Every such
fallback is the "coordinates, not intent" anti-pattern this project exists to kill, and each
one is a missing verb the dogfood surfaced *by need, not speculation* — the signal to promote
it. Categories hit THIS session, all currently shell-only:

- **Lighting** — sun pitch/yaw/intensity/temperature, skylight fill, fog. See G50 (this is
  its predicted recurrence: sun raised −10→−20 via `set_actor_rotation` over probe; the
  user then had to be taught the editor Details panel by hand because no verb exposes it).
- **Ambient audio** — placing `AmbientSound` actors and authoring randomizing `SoundCue`
  graphs (Loop→Modulator→Random-without-replacement), 2D/looping/volume. No `sound`/`audio`
  verb. A whole imported SFX pack was wired AND torn down entirely in Python.
- **Material authoring** — creating/editing Materials & instances via `MaterialEditingLibrary`
  node graphs (RVT writer master + RVT Output node, RVT-reader mound mat, translucent
  edge-fade path-blend), reparenting MIs. The `material` verb today only assigns/reads —
  it cannot AUTHOR. (Also why the path-blend shipped invisible: no way to author+preview a
  blend through a verb, so a fragile translucent hand-build slipped through unverified.)
- **Procedural mesh generation** — baking a StaticMesh (cosine-falloff dome) via GeometryScript.
- **Instanced placement off a data source** — reading a foliage stand's per-instance
  transforms and co-locating a second instanced mesh at each (the RVT mounds). Foliage
  can't co-locate two stands or place a non-inventory mesh.
- **Arbitrary actor/component property edits** — assign a material to any actor, register an
  RVT on a component, force-dirty+save a light, etc.

Resolution: NOT one mega-verb — triage into SPEC-worthy verbs as each earns it (`light` is
the clearest next, already G50; a `sound` verb and material-authoring support after). Going
forward, treat "I had to reach for `probe.sh`" as a first-class gap signal, logged here, not
a silent convenience.


### G63 — SPEC-16 level-diff does not split WorldPartition `removed` into deleted vs streamed-out

Status: OPEN (found 2026-07-06, SPEC-16 verification step 6)

`get_all_level_actors()` enumerates only LOADED actors, so on a World-Partition map an actor
that merely streamed out of the editor's loaded set is indistinguishable from a real deletion
— both just leave the loaded set and land in the diff's `removed` bucket. SPEC-16 ships the
HONEST interim: whenever `removed` is non-empty on a partitioned map, the payload carries a
`removed_note` disclosing the ambiguity ("a `removed` actor MAY have streamed out rather than
been deleted…") instead of asserting a deletion that might be streaming. Verified live: the
disclosure fires on a removal on a partitioned map; the differ is provably blind to the
stream-out-vs-delete distinction, so the disclosure covers both.

Resolution (the real split, deferred per author ruling 6): `unreal.WorldPartitionBlueprintLibrary.get_actor_descs()`
is the reachable source — it returns the FULL actor-descriptor list (confirmed live: 140
descs on the crater map, persisting across an unload) regardless of load state. Split the
bucket: a key gone from the loaded set but STILL in `get_actor_descs()` → `unloaded`
(streaming, not loss); gone from the descriptors too → `removed` (real deletion). Wire the
descriptor GUIDs to the snapshot's GUID keys. Not built yet — the disclosure is the honest
stand-in until it is. (Note: a clean SYNCHRONOUS editor stream-out could not be forced from
Python this session — `unload_actors` refused freshly-spawned/unsaved and always-loaded
actors — so the split's trigger side wants its own live check when built.)

### G64 — no verb for sculpting a REAL Landscape; the raw path crashes the editor and bounds can't verify it

Status: OPEN (found 2026-07-07, "four middle tiles" session — a subset of G62, promoted for
its crash + honesty stakes; SPEC-17 territory)

A user asked to modify a real stock Open-World `Landscape` (not the `terrain` DynamicMesh
substitute) confined to four selected `LandscapeStreamingProxy` tiles. There is no verb, so
it fell to raw `scripts/probe.sh` Python — and the naive path **crashed UE twice** (GPU TDR,
RC bridge "Connection reset by peer"). Root cause: a degenerate whole-landscape heightmap
(all proxies at the −256 m floor) handed to `force_layers_full_update()` recomposites the
entire WorldPartition landscape in one synchronous GPU burst. Two traps produce the
degenerate RT: the **export-trap** (export writes GPU-only; `read_render_target_raw_pixel`
reads it as zeros and a material `TextureSample`/`draw_material` cannot read/accumulate onto
it → edges collapse to the floor) and a silently-zeroed material (`TextureSampleParameter2D`
rejects an RT). Compounding it, **`get_actor_bounds` can't verify the result**: it is a
bounding BOX, so it reported a clean "+30 m mound" for what a ground-trace-vs-pristine diff
revealed to be a terraced RING averaging +15 m, 400 m wide — the box did not lie, it was the
wrong instrument, and the human's eyes caught the over-claim (see [[the-cathedral-principle]]).

Resolution (deferred — SPEC-17): a `terrain op=sculpt_landscape` (or similar) verb that is
**safe by construction** — builds the height RT via `clear`+additive masked `draw_material`
(never export-sampling), imports into a **separate additive edit layer** (`edit_layer_idx≥1`)
at the **native quad resolution** (stock 8×8 default-scale landscape = 2016×2016), with
neutral `R=128/255,G=0` (`height=R·256+G`, 32768 = zero elevation) and the bump on the low
byte (G) for smooth steps. It must self-verify with **ground traces, not bounds**, refuse any
import whose result would drive proxies to the floor, and honestly report that an additive
bump is NOT spatially confined (wide falloff — ~32/64 proxies moved from a center mask; true
per-tile confinement is unsolved). Interim rule now enshrined in `GUIDANCE_FOR_LLMS.md`
("Sculpting a REAL Landscape by raw heightmap import is a CRASH HAZARD" + "an envelope is not
a shape"): until the verb exists, do not freehand landscape imports.
