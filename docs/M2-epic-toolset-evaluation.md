# M2 — Epic Unreal MCP / EditorToolset evaluation

Status: 2026-07-02. Deliverable for SPEC-00 addendum #2 ("enable it in UEButtons,
inventory toolsets against that test"). Source-read evaluation of UE 5.8's experimental
`EditorToolset` (20 toolset modules, ~10.5k LOC) as a **hidden backend** for ue-buttons
verbs. Live `:8000/mcp` verification is pending an editor restart (plugins now enabled +
auto-start configured; see below).

## The test (from the addendum)
Epic toolsets are candidate *backends* our verbs dispatch to internally — **never** an
agent-facing surface. Adopt one only if, hidden behind a ue-buttons verb, it (A) beats
what we'd write against Remote Control + `unreal.*`, AND (B) fits intent space (reject
coordinate-soup params, alien return shapes, asset-path-heavy workflows). **Maturity is a
reliability bar, not an adoption reason.**

## Architecture reality (shapes every verdict)
These are **not** JSON RC endpoints. Each tool is a UFunction from a typed Python static
method whose params/returns are **live `unreal.*` objects** (`Actor`, `Transform`,
`LinearColor`, `MaterialInstanceConstant`, …). There is **no return envelope** — tools
return the bare value; failures go to UE's script-error channel, not `{success,error}`.
Most mutating tools **require you to already hold the object handle** (no resolve-by-label).

This is actually a clean fit for ue-buttons' *runtime* layer specifically: our runtime is
already in-editor Python holding actor handles, so "wiring a toolset behind a verb" =
`import editor_toolset...` and call the static method, then reshape the return + add our
own status envelope. It is a poor fit for anything at the RC/server layer.

## Verdicts

### ADOPT as internal backend / borrow the logic
- **`primitive.py` bounding-box→scale math** (`primitive.py:40-50`): loads the mesh, reads
  `get_bounding_box()`, computes scale from real cm dims. The one true
  dimensions-over-coordinates piece. Our `add` already does `dims/100` for BasicShapes;
  adopt this generalized form when `add` grows beyond BasicShapes to arbitrary meshes.
- **`scene.py` perception/placement primitives** — `trace_world` (`:293-308`),
  `_snap_to_ground` (`:627-645`), `find_actors` (`:64-98`), `actor.py get_actor_bounds`
  (`:331-344`). `trace_world` + `_snap_to_ground` are genuinely *new* capability
  (physics-aware placement) worth pulling behind `feel`/`add` for M2 perception depth —
  they'd be tedious to reimplement against RC.
- **`helpers.require_editable` / `compile_blueprint`** (`helpers.py:30-76`): level-instance
  edit guards + BP recompile correctness — keep in back pocket for when we touch BP actors
  or level instances.
- **Blueprint text DSL — `write_graph_dsl` / `read_graph_dsl`** (`blueprint.py:1438-1502`,
  backed by `blueprint_dsl.py`): a round-trippable S-expression IDL (`event`/`fn`/`if`/
  `for`/`switch`/…) that transpiles text→nodes→compile and decompiles back. **The standout
  — and it directly affects addendum #3** (see below).

### SKIP — use Remote Control + `unreal.*` directly
- **`transform`** — `actor.py set_actor_transform` is transform-in + worldspace flag
  (`:120-152`); fights nudge/resize-by-cm/rotate-by-deg. REJECT.
- **spawn as a public shape** — `scene.py` spawn takes a raw `Transform` + `/Game/...`
  asset path (`:100-150`); coordinate-soup + path-heavy. Keep our own spawn; borrow only
  snap/trace internally.
- **`material` verb** — `material_instance.py` makes persisted MaterialInstance*Constant*
  assets (needs folder + asset name + a parent material exposing the param) and **never
  assigns them to an actor** — not the "constant-color MID, applied to what I just added,
  no asset paths" goal. `material.py` is a full node-graph authoring beast (wrong
  altitude). Use `unreal.MaterialEditingLibrary.create_dynamic_material_instance` via RC;
  borrow only the `LinearColor`/param-update sequencing knowledge.
- **`select`, `view`, `history`** — **no backend exists** (grep-confirmed: no selection
  tool, no camera/screenshot tool, no standalone undo tool). Build entirely on RC, as we
  already have. (`programmatic.py`'s transactional script runner, `:764-875`, is worth
  *studying* for `history`, but there's no undo tool to adopt.)

## Impact on addendum #3 (logic moonshot) — worth Ryan's eye
The addendum ranked logic paths: (1) Epic MCP toolsets where they exist, (2) clipboard-
text seam + editor APIs, (3) generated C++ + Live Coding. This eval found that path (1)
is **more concrete than assumed**: Epic ships a first-party, round-trippable **Blueprint
text DSL** (`read/write_graph_dsl`). A text-in/text-out logic artifact is exactly the
altitude an agent verb wants — it is strictly more intent-aligned than the clipboard-text
seam (path 2). Recommendation for the eventual logic spec: **wrap `write_graph_dsl`/
`read_graph_dsl` rather than rebuild a transpiler or lean on clipboard text.** (Caveat:
still expects `find_node_types()`/`get_node_type_pins()` discovery first, and is keyed off
`Blueprint`/`EdGraph` handles + asset paths.)

## Net
EditorToolset is mature and correct, but it's an **object-handle, transform-and-path**
toolset — a poor *public* match for intent-space verbs (most map to REJECT). Its value is
a handful of *internal* primitives: primitive sizing math, world-trace / ground-snap /
bounds, level-edit guards, and the Blueprint text DSL. Wire those behind verbs when the
relevant verb lands; use RC for everything else. Our differentiated layer (small verb
surface, relational placement, auto-status, dimensions-over-coordinates) stands unchanged.

## Enablement state (this session)
- `UEButtons.uproject`: `ModelContextProtocol` + `EditorToolset` enabled (both ship
  precompiled in the installed 5.8 engine — no C++ build).
- `Config/DefaultEditorPerProjectUserSettings.ini`: `bAutoStartServer=True`,
  `ServerPortNumber=8000`. Server auto-starts on :8000/mcp on next launch; coexists with
  our RC server on :30010. (Also startable via `-ModelContextProtocolStartServer` launch
  flag or the `ModelContextProtocol.StartServer` console command.)
## Live verification (post-restart, 2026-07-02)
Editor restarted with the plugins enabled. Confirmed live:
- **Our stack survived the change**: `init_unreal.py` auto-loaded `ue_buttons` on real
  startup — `dispatch('scene')` works with **no** sys.path bootstrap. RC on :30010 intact.
- **Epic MCP up on :8000**: `initialize` handshake succeeds; capabilities advertise tools
  + resources. `tools/list` returns exactly three meta-tools — `list_toolsets`,
  `describe_toolset`, `call_tool` — because `bEnableToolSearch=True` (default): toolset
  tools are discovered on demand and dispatched via `call_tool`, not registered natively.
  (Epic's HTTP transport is full streamable-HTTP: a POSTed request's response arrives on a
  separate GET SSE stream. Not on our path — see next.)
- **The real adoption path works**: our in-editor runtime can `from editor_toolset.toolsets
  import scene, primitive` directly and the backend methods are present/callable
  (`find_actors`, `trace_world`, `PrimitiveTools`). So when we adopt a primitive, ue-buttons
  imports the toolset module in-runtime and calls the static method — we do **not** go
  through :8000 (that HTTP surface is for external MCP clients). Exact per-tool keyword
  signatures are pinned at wire-time for the specific verb being backed.
