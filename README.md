# ue-buttons

Porting the blender-buttons principle to UE5: sidestep the human-optimized interactive
UI and project the domain into agent-space (names, relations, dimensions, legible
perception). Partnership split: human owns taste + experiential playtesting ("does it
feel right"); agent owns precision + mechanical verification ("does it provably work").

## North star (decided 2026-07-02)

**The entire package: a complete, playable game — environment and game systems together,
built and verified through the verbs.** Not pretty-scenes-only (that's blender-buttons
territory projected into UE) and not logic-in-a-graybox — you cannot have complete game
systems without environments. blender-buttons' north star is high-quality character
meshes; this is its UE-scale equivalent.

Checkpoints toward it (the "donut tutorial" ladder — UE has no single donut, it has two,
and we take both):

1. **The environment donut** — decided 2026-07-02: **a forest in a mountainous valley,
   with a winding path through the trees, across hamlets, arriving at a castle.** No
   NPCs or systems — pure environment. This crosses four domains the surface doesn't
   have yet (landscape/heightfield, scatter-at-scale via foliage/PCG, splines for the
   path, asset-library perception over Fab packs), so its donut-sized first slice is
   **one hamlet**: a sculpted terrain patch, a scattered tree stand, a spline path,
   3–4 buildings placed relationally along it, lit and mechanically verified. That slice forces
   all four domains at toy scale; the full valley is then repetition + PCG. Partnership
   split: Ryan curates the asset palette (Fab is a launcher/web click — human step);
   the agent inventories and builds.
2. **The game-systems donut** — Epic's "Your First Game in UE5" shape: ThirdPerson
   template, blocked-out obstacle course, moving platform, button-opens-door, pickups,
   win state. Gated on the logic verb (Blueprint text DSL wrap); serves as its exit test.
3. **The package** — the two fused: a small complete game in a real environment. Agent
   proves it works (functional tests, traces); Ryan judges how it feels.

## Topology (2026-07-02 — supersedes the Mac-mini plan in blender-buttons/experiments)

Everything on one machine, the Windows gaming rig (RTX 4090):

```
Claude (WSL2, ~/workspace/ue-buttons) → localhost:30010 → UE 5.8 editor (Windows, DX12)
```

WSL2 runs in **mirrored networking mode** (`.wslconfig: networkingMode=mirrored`), so
localhost is shared bidirectionally — the Remote Control HTTP server's 127.0.0.1 bind
on the Windows side is directly reachable from WSL. No Tailscale, no port proxy, no
tunnel.

- Engine: `C:\Program Files\Epic Games\UE_5.8` (5.8.0)
- Project: `C:\Users\anvil\Documents\Unreal Projects\UEButtons`
  (WSL path: `/mnt/c/Users/anvil/Documents/Unreal Projects/UEButtons`)
- The project lives on NTFS because the Windows editor runs it; this repo (server code,
  docs, scripts) lives on ext4 for speed. Config files are edited via `/mnt/c`.

## The bridge (proven on Linux 2026-07-01, zero custom code)

```
terminal → HTTP :30010 → Remote Control plugin → editor Python → scene graph
```

Setup is exactly two things, no editor UI required:

1. `.uproject` plugins array: `PythonScriptPlugin` + `RemoteControl`, both enabled.
2. `Config/DefaultRemoteControl.ini` (names verified against 5.8 plugin source;
   editor restart required to pick up changes):

   ```ini
   [/Script/RemoteControlCommon.RemoteControlSettings]
   bEnableRemotePythonExecution=True
   bAllowAnyRemoteFunctionCall=True
   ```

Ports: HTTP **30010** (127.0.0.1), WebSocket **30020** (0.0.0.0 — LAN-exposed; fine for
dev, lock down for real use). A real server should replace `bAllowAnyRemoteFunctionCall`
with a narrow `CustomAllowedRemoteFunctionCalls` list.

`ExecutePythonCommandEx` returns `LogOutput` (stdout lines) + `ReturnValue` in the HTTP
response — a complete REPL. See `scripts/probe.sh`.

## Launching the editor from WSL

```bash
"/mnt/c/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor.exe" \
  "C:\Users\anvil\Documents\Unreal Projects\UEButtons\UEButtons.uproject" &
```

First launch of a fresh project compiles shaders — allow several minutes before the
probe answers.

## M1 — built (2026-07-02)

The foundation from `docs/SPEC-00-Initial.md` is implemented and live-verified against
the running editor. Layout:

```
runtime/ue_buttons/     in-editor half (unreal.*): dispatch + hot reload, _state
                        (never reloaded — holds history + counters), _ue helpers,
                        relational math + placement DSL, the 7 verbs
runtime/init_unreal.py  auto-run at editor startup → makes ue_buttons importable
server/                 thin FastMCP server: 7 @mcp.tool verbs → Remote Control HTTP
scripts/sync-runtime.sh deploy runtime/ → <project>/Content/Python/ (repo = source of truth)
gaps.md / bugs.md       friction + defect worklists (fix → live-verify → clear)
```

Verbs (M1 names — see the SPEC-05 cutover below for today's roster): `scene`, `add`,
`transform`, `select`, `feel`, `view`, `history`. Every mutating verb appends the
auto-status block and runs inside a `ueb:<id>` transaction kept 1:1 with the editor undo
stack. **Exit test passes**: an agent builds a table (top + 4 legs at
corners) via relational placement only, confirms with `feel`, and `undo_to` tears it down
cleanly. Open items live in `gaps.md`.

### Running

```bash
scripts/sync-runtime.sh          # deploy runtime into the UE project
# launch the editor (see below), then this repo's .mcp.json wires the MCP server:
uv run python server/main.py     # or let the Claude Code host start it from .mcp.json
```

`scripts/probe.sh` still verifies the bare bridge / runs one-shot editor Python.

## SPEC-01 — built (2026-07-02)

The environment surface from `docs/SPEC-01-Environment.md` is implemented and live-verified
against the running editor. Surface grows 7 → 11 verbs; `add` grows `asset=`. New runtime
modules:

```
asset.py       perception over Content — packs/inventory/describe/find/whats_new. Families
               + variants, dims/pivot/tris/Nanite; lazy disk-cached measurement (G9).
heightfield.py pure-Python heightfield engine (no numpy) — the one height_at() that backs
               the mesh and describe sampling; + region math for flatten/paint.
terrain.py     terrain as a GeometryScript DynamicMesh (G12: Landscape API unscriptable) —
               create/shape/flatten/carve/describe/remove; complex collision so traces
               conform; material= assignment (G25).
map_ref.py     map-position resolver — polar {from,bearing,distance} + absolute [x,y].
spline.py      routes as Catmull-Rom over waypoints (G13) — create/surface/describe/
               remove; route walking; drape; a draped material ribbon (`surface`)
               that makes the route visible; along=/facing= placement terms.
foliage.py     instanced-foliage populations — paint/describe/reseed/remove; seeded
               jittered-grid sampling, per-point ground trace + slope, auto-clears splines
               & buildings. Instances go through the editor foliage subsystem so they
               render (G14: a hand-built HISM has no render proxy from script).
material.py    MaterialInstanceConstant authoring — op=instance, read-back verified.
```

Verbs added (SPEC-01 names, since renamed): `asset`, `landscape`, `path`, `scatter`;
`add(asset=, yaw=, facing=, place.along/ground)`. Spatial verbs carry an honest `undoable: false` (DynamicMesh/
HISM edits don't sit in the transaction stack). **Exit test (the hamlet) passes end-to-end
through the verbs**: a 200 m valley-edge terrain (rocky ridge, gentle floor, noise), a
5-waypoint winding lane carved to grade, three cabins placed along+facing it on flattened
pads (one composed wall-by-wall from the modular kit on the 4 m grid, two prebuilt BPs), and
~2,600 scatter instances (3 tree species + undergrowth + rocks) that clear the lane and
cabins. Verified mechanically (`feel`: front↔back 400.0 cm, roof over walls; scatter counts;
nearest tree 990 cm vs a 575 cm clearance). The 3D "does it read as a place?" judgement and
PIE walk are the user's step, from their own screen — the agent verifies in numbers, never
pixels (there is no screenshot/render verb; see the vision policy). New friction is in
`gaps.md` (G9–G13) and `bugs.md` (B2).

## SPEC-05 — verb alignment cut over (2026-07-03)

The whole surface was renamed onto UE's own vocabulary in one hard cut (no shims; see
`docs/SPEC-05-Verb-Alignment.md` for the law and `docs/vision.md` for the why). Current
roster — 14 verbs, `op=` the one discriminator everywhere:

| verb | drives | note |
|---|---|---|
| `add` `select` `transform` `asset` `history` | Place Actors / selection / gizmos / Content Browser / Undo History | `transform op=move` (was nudge) · `select op=user` (deixis, SPEC-06) |
| `material` | Material Instance editor | `op=instance` (from asset) |
| `foliage` | Foliage mode (was `scatter`) | `op=paint/describe/reseed/remove` |
| `terrain` | MACRO ≈ Landscape (was `landscape`) | + `op=carve along=<spline>` (from path) |
| `spline` | SplineComponent (was `path`) | curve + surface strip; carve moved out |
| `outliner` `level` `play` | the three surfaces `scene` conflated | census/reconcile · streaming + lifecycle `save/new/open/clear` (SPEC-04) · census/start/stop |
| `feel` `validate` | agent-only senses | + `feel op=looking_at` / `play op=where` (deixis, SPEC-06) |

## Next design step

The two genuinely novel fronts:

- **Logic**: targets Blueprints (decision 2026-07-02; Verse/UE6 deliberately deferred).
  The projection no longer needs inventing — the M2 eval
  (`docs/M2-epic-toolset-evaluation.md`) found UE 5.8's `EditorToolset` ships a
  round-trippable Blueprint **text DSL** (`write_graph_dsl`/`read_graph_dsl`,
  S-expressions, transpile→compile→decompile). The logic spec wraps that behind a
  ue-buttons verb (backend, never surface); generated C++ + Live Coding stays the
  fallback for systems-level logic.
- **Temporal feel**: mechanical ground truth from automation/functional tests, Visual
  Logger, navmesh/EQS queries — the agent proves "it works"; the human judges "it feels".
