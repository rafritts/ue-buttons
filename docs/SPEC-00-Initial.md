# SPEC-00 — Initial port: blender-buttons core → ue-buttons

Status: draft, 2026-07-02.
Goal: the smallest foundation on which an agent genuinely succeeds in UE — not a full
port. Most blender-buttons concepts arrive later; this spec picks the load-bearing ones
and maps them onto UE's shape.

## What actually made blender-buttons work

Four things carried the project. Everything else was elaboration.

1. **Legible perception, automatically.** Every mutating tool appends a status block
   (mode, active, selected, dims, bounds, last action). The agent never operates blind
   and never has to remember to look.
2. **Dimensions over coordinates.** Creation takes exact sizes; placement is relational
   (`on`, `left_of`, `at_corner`, `between`). The server computes coordinates; the agent
   never carries them across calls. Raw coords exist only as a documented ripcord.
3. **Visual ground truth.** Screenshots and the 6-panel labeled collage. Mechanical
   queries prove numbers; images prove the thing actually looks right.
4. **A small verb surface.** SPEC-05 collapsed 137 tools into ~15 verbs (one per
   domain). Small surface = the agent holds the whole API in its head.

Plus one process concept: **gaps.md** — every friction point becomes a numbered gap,
fixed and live-verified before it's cleared. That discipline is portable as-is.

## Architecture

```
Agent / LLM harness
      │  MCP over stdio (FastMCP, one verb per @mcp.tool)
      ▼
server/main.py                     (WSL, ~/workspace/ue-buttons)
      │  HTTP PUT localhost:30010 /remote/object/call → ExecutePythonCommandEx
      ▼
Content/Python/ue_buttons/         (runtime module inside the UE project, NTFS)
      │  unreal.* editor subsystems
      ▼
UE 5.8 editor (Windows, DX12)
```

Same two-layer split as blender-buttons (thin MCP server / in-app runtime), with two
UE-specific simplifications:

- **No addon install step.** UE auto-runs `Content/Python/init_unreal.py` at editor
  startup. We deploy the runtime by writing files through `/mnt/c` — the repo is the
  source of truth, a `sync` step copies `runtime/` → `Content/Python/ue_buttons/`.
- **No socket protocol to invent.** Remote Control is the transport. One snippet shape
  for every call:

  ```python
  import ue_buttons; ue_buttons.dispatch("<verb>", <params-json>)
  ```

  `dispatch` prints one line — `UEB>>>{json}` — which the server extracts from
  `LogOutput` and parses. Everything else in LogOutput is passthrough noise/warnings.
  Python-side errors are caught in `dispatch` and returned as `{"error": ...}` so the
  server never has to scrape tracebacks.
- **Hot reload:** `dispatch` lives behind `importlib.reload` on a dev flag, so runtime
  edits don't require editor restarts (blender-buttons' F8-reload equivalent).

Main-thread safety: `ExecutePythonCommandEx` already executes on the game thread —
the queue machinery blender-buttons needed does not exist here. One less moving part.

## Conventions (decide once, bake into every docstring)

| | Blender (blender-buttons) | UE (ue-buttons) |
|---|---|---|
| Unit | meters | **centimeters** (UE native — do not convert) |
| Up | +Z | +Z |
| Front of an object | −Y | **+X** (UE forward) |
| Right | +X | +Y |
| Rotation | Euler XYZ deg | **yaw/pitch/roll deg** (UE Rotator) |

The placement DSL vocabulary (`in_front_of`, `left_of`, ...) keeps its *names* and
remaps to these axes. Docstrings state the convention everywhere sizes/directions
appear, same as blender-buttons.

## Starting verb set (7 verbs — the M1 surface)

One `@mcp.tool` each, action-dict style like blender-buttons verbs
(`add(what="cube", ...)`, `transform(action="nudge", ...)`).

| Verb | Covers | UE mechanism |
|---|---|---|
| `scene` | actor tree (grouped by folder/type), counts, level name | `EditorActorSubsystem.get_all_level_actors` |
| `feel` | `describe(actor)` — rests-on/flush/overlap relations, dims; `distance_between`, `gap_between`, `is_aligned` | `get_actor_bounds` (world AABB) + same relation math as blender-buttons `relational.py` — port nearly verbatim |
| `add` | spawn primitives (cube/sphere/cylinder/cone/plane) with **exact cm dimensions** + `on=` placement spec | `/Engine/BasicShapes/*` are 100 cm meshes → spawn + scale = dims/100; placement resolved server-side from bounds |
| `transform` | nudge (semantic directions), rotate, resize, snap_to, mirror_of | `set_actor_location/rotation/scale3d`, bounds math |
| `select` | select by name/pattern, clear; feeds "active/selected" state | `EditorActorSubsystem.set_selected_level_actors` |
| `view` | set camera by orbit (azimuth/elevation/distance/target), screenshot, later collage | `UnrealEditorSubsystem.set_level_viewport_camera_info`; `AutomationLibrary.take_high_res_screenshot` → file lands in `Saved/Screenshots/` on NTFS → server reads via `/mnt/c` and returns MCP `Image` |
| `history` | log of mutations with IDs; `undo_to(id)` | every mutation wrapped in `unreal.ScopedEditorTransaction` (labels = `ueb:<id> <verb>`), so editor Ctrl+Z and our undo agree; log kept in the runtime module |

**Auto-status** rides on every mutating verb, exactly like blender-buttons:

```
── ue status ───────────────────────────────
  level:      <name> (dirty|saved)
  selected:   [<labels>]
  active:     <label>  dims: [x, y, z] cm  bounds: x=[..] y=[..] z=[..]
  last_action: {id, verb, summary}
────────────────────────────────────────────
```

## Explicitly deferred (port later, in order of likely pull)

- **Mesh-level editing** — UE's Geometry Script covers a lot of blender-buttons
  editmode; big surface, own spec.
- **Materials** — `material` verb (constant-color MaterialInstanceDynamic first).
- **Collage** — 6-panel labeled views; M1 ships single screenshot + orbit only.
- **Groups** — map to World Outliner folders and/or actor attachment; needs a design
  decision, don't guess at it in M1.
- **The two novel fronts** from the handoff (Blueprint logic via generated C++ +
  Live Coding; temporal feel via automation tests / Visual Logger) — separate specs;
  nothing in M1 should block them.
- Asset import, lint, recipes, multi-instance discovery, macros.

## Milestones

- **M0 — bridge (done 2026-07-02).** RC HTTP loop proven from WSL over mirrored
  localhost; spawn/move/destroy verified. `scripts/probe.sh`.
- **M1 — foundation.** Repo layout (`server/`, `runtime/`, `scripts/sync-runtime.sh`);
  `init_unreal.py` + `dispatch` protocol; the 7 verbs; auto-status; `.mcp.json` so this
  Claude session drives the editor directly. Exit test: agent builds a labeled
  arrangement (e.g. table = top + 4 legs at corners) using only relational placement,
  confirms with `feel` + a screenshot, undoes cleanly.
- **M2 — perception depth.** Collage, camera bookmarks, `feel` relation coverage
  brought to parity with blender-buttons `describe()`.
- **M3 — start `gaps.md`** and let real use drive the ordering of the deferred list.

## Addendum (2026-07-02, post-M1) — supersedes parts of the above

Written after M1 shipped and after researching the 5.8 AI landscape. Three updates:

### 1. Milestones M0/M1 are done

Built and live-verified same-day (see README "M1 — built"). The exit test passes.
Remaining milestone numbering continues from M2 as written.

### 2. Epic ships a first-party MCP plugin in 5.8 — evaluate before building more

Unknown when this spec was drafted: UE 5.8 includes an experimental **Unreal MCP**
plugin — an MCP server inside the editor process (loopback HTTP `127.0.0.1:8000/mcp`,
no auth), exposing tools via a Toolset Registry. Shipping toolsets: scene / actor /
material-instance / object, mostly implemented in editor Python. Docs:
https://dev.epicgames.com/documentation/unreal-engine/unreal-mcp-in-unreal-editor

Implications:

- **It does not replace ue-buttons.** Raw toolsets are exactly the 137-tool problem
  blender-buttons' SPEC-05 collapsed. The substrate — verbs, relational placement,
  auto-status, dimensions-over-coordinates — remains the differentiated layer.
- **It may replace parts of our plumbing.** New task (slot into M2): enable it in
  UEButtons, inventory the toolsets, and ride anything mature (e.g. material tools)
  instead of rebuilding it. Both servers coexist (ours via RC :30010, Epic's :8000).
- Caveats observed: experimental, toolset changes require editor restart, no
  Resources/Prompts support.

### 3. The logic moonshot reprices — and targets Blueprints (decision)

The deferred-list framing ("Blueprint graphs are not Python-authorable") was too
pessimistic. Findings:

- Blueprint graphs **are plugin-authorable** via editor C++ APIs (`UEdGraph`/`UK2Node`,
  K2 schema, `FKismetEditorUtilities`) — community-proven (e.g. chongdashu/unreal-mcp
  authors nodes/wires agentically today). Brittle engine-internal surface, but
  engineering, not research.
- A **text serialization of graphs already exists**: copying BP nodes puts an
  object-text export on the clipboard (how blueprintue.com works). A candidate seam
  for reading and templated writing without a bespoke graph compiler.
- Epic's first-party MCP has **no BP graph authoring yet**, but the direction is clear.

**Decision (Ryan, 2026-07-02): target Blueprints now.** UE6 (EA end-2027) will move
gameplay to Verse and eventually deprecate Blueprints; that horizon is explicitly
deferred — do not redesign around Verse, do not propose waiting for it. Path ranking
for the eventual logic spec: (1) Epic MCP toolsets where they exist, (2) clipboard-text
seam + editor APIs for common patterns (trigger→animate→state-change chains),
(3) generated C++ + Live Coding for systems-level logic. Avoid deep investment in a
bespoke K2Node graph compiler — that's the brittlest option and targets the surface
with a public end-of-life intention.

## Risks / open questions

- `take_high_res_screenshot` is async (writes on a later frame) — server polls for the
  file with a timeout. If flaky, fall back to editor viewport client capture.
- `EngineAssociation: "5.8"` project has no C++ — Live Coding path (Blueprint moonshot)
  will eventually force a code project; fine, additive.
- RC security stays wide-open (`bAllowAnyRemoteFunctionCall=True`) while single-machine
  dev; narrow to `CustomAllowedRemoteFunctionCalls` before anything leaves localhost.
- Actor labels vs internal names: labels are the human/agent-facing handle (Blender
  object-name equivalent) but uniqueness is not enforced by UE — the runtime enforces
  unique labels on spawn, erroring on collision like Blender would have.
