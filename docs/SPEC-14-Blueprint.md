# SPEC-14 — `blueprint`: gameplay logic through the first-party graph DSL

Status: **DESIGN — spike-proven 2026-07-05, and the spike verdict is a full pass.**
Audience: the agent implementing the verb. Every engine claim below was probed live over
the RC bridge on UE 5.8 (traces at bottom) unless marked **SPIKE-CHECK**.

This is the pivotal verb: it moves ue-buttons from set dresser to game maker. A door
that opens, a pickup, a trigger, a win condition — none exist without it. The historical
assumption "Blueprint graph authoring from Python is impossible" is **dead on 5.8**:
Epic ships a complete, first-party, round-trippable **S-expression graph DSL** in the
EditorToolset plugin (already enabled in UEButtons.uproject — see M2 evaluation, which
predicted exactly this recommendation).

## Decisions already made (do not relitigate)

- **Graph authoring goes through `BlueprintTools.write_graph_dsl` / `read_graph_dsl`**
  (`editor_toolset.toolsets.blueprint.BlueprintTools`) — not hand-built node/pin
  plumbing. The primitives (`create_node`, `connect_pins`, `set_pin_value`,
  `BlueprintGraphPin.try_create_connection`) all exist and are the DSL's own substrate;
  use them only if a dogfooded need exceeds the DSL, and log the gap first.
- **The DSL text is the logic artifact.** `read_graph_dsl` output is the agent's
  perception of a graph; `write_graph_dsl` input is its authoring surface. Text in,
  text out — the exact altitude an agent verb wants. No node-position math, no pin
  GUIDs at the verb surface.
- **Scope guard: gameplay logic only.** Doors, triggers, pickups, counters, state.
  Scene placement stays with `add`/`pcg`/`foliage`; a Blueprint ACTOR is placed in the
  level via the existing `add` machinery once its class exists.
- **BP assets live under `/Game/UEB_BP/<Name>`**, ordinary visible assets, parent class
  `Actor` by default (any loadable class accepted).
- **Verify-by-read is mandatory** (invariant 1): the spike caught `write_graph_dsl`
  reporting success while landing nothing (bad kwarg syntax, unresolved node id). A
  write that isn't confirmed by a read-back diff DID NOT HAPPEN.
- Verb name `blueprint`, `op=` discriminator (SPEC-05 reserved the name).

## Verb contract

### MCP tool (`server/main.py`)

```python
@mcp.tool()
def blueprint(op: Literal["create", "component", "var", "logic", "read",
                          "nodes", "docs", "describe", "remove"] = "describe",
              label: str = None, parent: str = None, component: dict = None,
              var: dict = None, code: str = None, graph: str = None,
              event: str = None, query: str = None) -> str:
    ...
    return render(call_ue("blueprint", p, timeout=120))
```

Docstring must carry the three syntax load-bearing facts (agents will write DSL from
the docstring alone): kwargs are `:PinName value`, node ids come from `op=nodes`, and
class/enum/asset identifiers must be quoted strings.

### Ops

| op | params | effect |
|---|---|---|
| `create` | `label=` (required), `parent=` (class name/path, default Actor) | create `/Game/UEB_BP/<label>` via BlueprintFactory, compile, register |
| `component` | `label=`, `component=` `{class: "BoxComponent", name: "Trigger", props: {...}}` | add a component via SubobjectDataSubsystem, rename, set props, compile |
| `var` | `label=`, `var=` `{name, type: "float\|int\|bool\|string\|name\|...", default?, instance_editable?}` | `add_member_variable` (+ `set_blueprint_variable_instance_editable`), compile |
| `logic` | `label=`, `code=` (DSL text), `graph=?` (default EventGraph), `event=?` (component-bound event to materialize first, e.g. `{component: "Trigger", event: "OnComponentBeginOverlap"}`) | write the DSL, **compile, read back, DIFF, return the read-back text** |
| `read` | `label=`, `graph=?` | `read_graph_dsl` — the graph as DSL text (perception) |
| `nodes` | `label=`, `query=` | `find_node_types(graph, query)` (+ `get_node_type_pins` for exact-one matches) — the node-id discovery surface |
| `docs` | — | `get_graph_dsl_docs()` verbatim (~8.7k chars) — the full grammar, on demand |
| `describe` | `label=` (omitted → all) | variables, components, graphs, events, compile status; for all: the registry roster |
| `remove` | `label=` | delete the asset (G47: report + stop on in-use refusal — a placed instance means the class is live; name the instances) |

`logic` is the heart; everything else exists to make its `code=` writable and
verifiable.

### Errors (HATEOAS — each carries the next legal move)

- unknown `label=` → registry roster + `blueprint op=create`.
- DSL write lands nothing / partially (read-back diff shows a statement missing) →
  **error, not success**, echoing the read-back and pointing at `op=nodes query=<the
  unresolved head>` and `op=docs`. This converts the engine's silent failure into a
  legible one — the single most load-bearing behavior in the verb.
- unknown node type in `code=` (when detectable: `find_node_types` on each call head
  that isn't grammar) → error listing the near-miss ids (`find_node_types` output).
- `component.class` unknown → error naming loadable component classes that matched a
  substring.
- compile errors → surface the compiler messages verbatim + `op=read` next line
  (**SPIKE-CHECK**: where compile diagnostics are readable from Python —
  `compile_blueprint` returned void in the spike; probe `unreal.BlueprintEditorLibrary`
  / the toolset's `compile_blueprint` return or log capture).

## Runtime implementation (`runtime/ue_buttons/blueprint.py`, new module)

Registry (`_state.py`, hasattr-guarded): `blueprints = {}` —
`{label: {asset_path, parent, components: [...], vars: [...]}}`. Rehydrate-on-open by
scanning `/Game/UEB_BP/` (asset registry), like G61. This verb is NOT SPATIAL (it
authors assets, not level actors) — wire into `_VERBS` with history/transaction
semantics matching `material` (asset-mutating verb); placing instances is `add`'s job
and rides `add`'s existing lifecycle.

The proven call sequences (all traced live):

```python
# create
f = unreal.BlueprintFactory(); f.set_editor_property("parent_class", parent_cls)
bp = asset_tools.create_asset(label, "/Game/UEB_BP", unreal.Blueprint, f)

# component
sds = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
handles = sds.k2_gather_subobject_data_for_blueprint(bp)   # [0] = CDO root
params = unreal.AddNewSubobjectParams(parent_handle=handles[0],
                                      new_class=comp_cls, blueprint_context=bp)
handle, fail_reason = sds.add_new_subobject(params)        # fail_reason == "" on success
sds.rename_subobject(handle, unreal.Text(name))
# template object (for events + props): SubobjectDataBlueprintFunctionLibrary.get_object(
#   sds.k2_find_subobject_data_from_handle(handle))  — deprecated in favor of
#   GetAssociatedObject; SPIKE-CHECK the replacement's python name, use it if present.

# component-bound event (materialize before the DSL references it)
BT = editor_toolset.toolsets.blueprint.BlueprintTools
BT.list_component_events(comp_template)                    # discovery
BT.add_component_bound_event(comp_template, "OnComponentBeginOverlap", event_graph)

# logic
eg = unreal.BlueprintEditorLibrary.find_event_graph(bp)
BT.write_graph_dsl(eg, code)          # can succeed silently-empty — ALWAYS read back
after = BT.read_graph_dsl(eg)
unreal.BlueprintEditorLibrary.compile_blueprint(bp)
unreal.EditorAssetLibrary.save_loaded_asset(bp)
```

DSL syntax facts the implementation must encode (all bitten live in the spike):

1. Keyword args are `:PinName value` — `(Development|PrintString :InString "hi"
   :Duration 5.0)`. The form `in_string: "hi"` silently lands nothing.
2. Node ids are category-paths from `find_node_types` — `Development|PrintString`, not
   `KismetSystemLibrary.PrintString` (also silently lands nothing).
3. Member-variable access is `(Variables|Default|GetMyVar)` / `(…|SetMyVar v)`.
4. Class paths, enum values, asset refs MUST be quoted strings.
5. Multi-exec/latent nodes use `(:ExecOut stmts…)` continuations; data outputs
   auto-bind as underscore names, or `(bind var (...))` for explicit naming.
6. `add_event_override(bp, name, IntPoint)` — position is an `IntPoint`, and a
   `Vector2D` fails with a NO-OUTPUT hard error (the bridge returns failure with an
   empty log — budget for that while developing).

Write semantics (**SPIKE-CHECK, shapes op=logic's contract**): the spike's second write
left the first write's event node in place and populated its own — determine whether
`write_graph_dsl` merges by event or appends duplicates when the same event appears in
two writes; if it appends, `op=logic` must either forbid re-writing an existing event
(error + `op=read` first) or clear-and-rewrite the graph (read → merge → write). Decide
from the probe, encode one behavior, document it in the docstring.

New-module reload gotcha applies (editor restart before hot-reload picks up
blueprint.py).

## The acceptance dogfood: one real interaction

Build, through the MCP tools only: a `DoorTrigger` BP — BoxComponent trigger + a
StaticMeshComponent door slab, `OpenSpeed` float var, OnComponentBeginOverlap → (if
open logic) move the slab. Place it in a dogfood level via `add what=blueprint`
(**SPIKE-CHECK**: `add`'s spawn path accepts a BlueprintGeneratedClass — the spike
spawned one via `spawn_actor_from_class(generated_class)`, so wire `add` to resolve
`/Game/UEB_BP/<label>` labels to their generated class). Verify in PIE via the existing
`play` senses (census sees the instance; SPEC-09's traverse/logs eventually verify the
BEHAVIOR — this spec only has to get the logic INTO the level).

## Invariants

1. **A write without a read-back diff did not happen.** Silent-failure is the engine's
   documented behavior here; the verb's contract is that its own success claims are
   verified. Every `op=logic` result carries the post-write `read_graph_dsl` text.
2. **Node ids come from `op=nodes`, never from memory.** Ids are project-dependent
   (plugins add categories — the spike found PCG print nodes shadowing PrintString).
3. **Compile after every mutation; save after compile.** An uncompiled BP lies to
   `spawn_actor_from_class`.
4. Components are renamed at creation (auto-names like `Box` collide on the second add).
5. G47 holds: never force-delete a BP whose instances are placed.
6. The verb authors ASSETS; instances go through `add` (one placement path, one
   labeling scheme, one reconcile).

## Verification plan (live, over the MCP tools, before commit)

1. `op=create label=DoorTrigger` → asset exists, registered, describe shows parent.
2. `op=component` BoxComponent "Trigger" → describe lists it; second add with the same
   name errors.
3. `op=var` OpenSpeed float instance_editable → readable on a spawned instance
   (`get_editor_property` — proven path).
4. `op=nodes query=PrintString` → returns `Development|PrintString`.
5. `op=logic` with the BeginPlay + if/else fixture from the spike → result's read-back
   contains the if/else; deliberately submit the broken kwarg form → verb ERRORS (the
   engine's silence converted).
6. `op=logic` with `event={component: Trigger, event: OnComponentBeginOverlap}` →
   read-back shows `(event OnComponentBeginOverlap(Trigger) (...))`.
7. `add` the BP into a level, PIE `play op=census` sees it; overlap behavior eyeballed
   by the user (their half) until SPEC-09 lands.
8. `op=remove` on a placed BP → G47 refusal naming the instance; after the instance is
   deleted → removal succeeds.
9. Findings → gaps/bugs, per discipline.

## Ground truth — spike traces (2026-07-05, RC bridge, UE 5.8)

1. `BlueprintEditorLibrary` in 5.8 is rich: add_event_override, add_function_graph,
   add_member_variable, compile_blueprint, find_event_graph, find/list pins,
   generated_class, list_graphs/functions/events, pin_type_to_json_schema. Pin objects
   are `BlueprintGraphPin` with `try_create_connection` / `break_pin_links` /
   `can_create_connection` / `list_connected_pins`.
2. `editor_toolset.toolsets.blueprint.BlueprintTools` (EditorToolset plugin, enabled):
   create/delete_node, connect/break_pins, get/set_pin_value, find_node_types,
   find_node_categories, get_node_type_pins, get_node_infos, write_graph_dsl,
   read_graph_dsl, get_graph_dsl_docs (8,665 chars), add_component_bound_event,
   list_component_events, add_variable/add_object_variable/add_struct_variable,
   add_event, add_function_graph/params, arrange_nodes, compile_blueprint.
3. Created SPIKE_BP (parent Actor) via BlueprintFactory; `add_member_variable(bp,
   "OpenSpeed", get_basic_type_by_name("float"))` → True.
4. `add_event_override(bp, "ReceiveBeginPlay", IntPoint(0,0))` → `K2Node_Event`
   (Vector2D position → hard error with EMPTY log output).
5. DSL round-trip proven: wrote `(event EventBeginPlay (Development|PrintString
   :InString "ueb spike alive" :Duration 5.0) (if (> (Variables|Default|GetOpenSpeed)
   1.0) … (else …)))` → read_graph_dsl returned the same structure (defaults
   materialized: color, duration). TWO silent failures first: wrong kwarg form
   (`in_string:`) and wrong node id (`KismetSystemLibrary.PrintString`) both reported
   "write OK" with an unchanged graph.
6. `find_node_types(eg, "PrintString")` → `["Development|PrintString",
   "Class|PCGPrintElementSettings|GetPrintString", …]`.
7. Components: SubobjectDataSubsystem added BoxComponent, renamed "Trigger";
   `list_component_events(comp)` → OnComponentHit/BeginOverlap/EndOverlap/…;
   `add_component_bound_event(comp, "OnComponentBeginOverlap", eg)` →
   `K2Node_ComponentBoundEvent`; read-back shows `(event
   OnComponentBeginOverlap(Trigger) (OverlappedComponent OtherActor …))`.
8. Compile + `generated_class(bp)` → `SPIKE_BP_C`; `spawn_actor_from_class(gc, loc)`
   spawned; `OpenSpeed` readable on the instance (0.0); instance destroyed.
9. Cleanup note: `delete_asset` on the never-saved SPIKE_BP refused (in-use — memory
   references); left transient, vanishes on restart. G47 respected.
