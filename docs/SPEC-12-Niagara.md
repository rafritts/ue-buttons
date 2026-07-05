# SPEC-12 — `niagara`: curated VFX as an intent verb

Status: **DESIGN — spike-proven 2026-07-05.** Audience: the agent implementing the verb.
Every engine claim below was probed live over the RC bridge on UE 5.8 (traces at bottom)
unless marked **SPIKE-CHECK** — those you verify live before relying on them.

## Problem

Static worlds read as dead. Fire in a hearth, smoke from a chimney, spray at a
waterfall, fireflies at dusk — a dozen curated effects buy disproportionate life, and
the surface has no way to author any of them. UE owns the word (Niagara), so the verb
is `niagara` (SPEC-05 reserved it).

## Decisions already made (do not relitigate)

- **Systems are used AS-IS + per-instance parameter overrides.** This is NOT the pcg
  duplicate+tune pattern, and the spike says it can't be: `NiagaraEditorLibrary` does
  not exist in 5.8 Python, `NiagaraSystem` exposes no emitter/module/parameter surface
  (`exposed_parameters` isn't a property; the param-fn scan over the loaded asset came
  back empty). All tuning happens on the spawned **NiagaraComponent** via the typed
  `set_niagara_variable_*` / `get_variable_*` family, which is complete (float, int,
  bool, vec2/3/4, linear_color, quat, position, matrix, actor, object).
- **Curated palette, same discipline as pcg's.** Each entry names the system asset AND
  its known user parameters (name, type, default, meaning). Parameter names cannot be
  discovered from Python — they are palette data, curated once per entry by reading the
  system in the editor UI (or its docs) when the entry is authored.
- **Perception = numbers only**: active flag, bounds, parameter read-back. No
  screenshots (vision policy). Whether an effect *looks* right is the user's half of
  the partnership.
- Verb name `niagara`, `op=` discriminator, per the SPEC-05 law.

## Verb contract

### MCP tool (`server/main.py`)

Thin projection over `call_ue("niagara", p, timeout=60)`, `pcg` tool as the template
(project optional params only when given — the B14 lesson).

```python
@mcp.tool()
def niagara(op: Literal["spawn", "set", "describe", "remove", "palette"] = "spawn",
            label: str = None, effect: str = None, place: dict = None,
            params: dict = None) -> str:
```

Docstring seam: "Curated particle effects (Niagara systems) — fire, smoke, bursts,
ambient motes. Placement uses the same relational vocabulary as `add`. For mass mesh
placement use `pcg`; for scene geometry use `add`."

### Ops

| op | params | effect |
|---|---|---|
| `spawn` | `effect=` (required, palette name), `label=`, `place=` (the `add` placement dict — at/on/near/inside, relational DSL) | spawn a ueb-tagged `NiagaraActor`, `set_asset`, apply `params=` overrides, `activate(True)`, register; return pending stub |
| `set` | `label=`, `params=` ({name: value}) | apply overrides to a live effect; values typed per the palette entry |
| `describe` | `label=` (omitted → all effects) | active flag, system, bounds, current param values (read back live via `get_variable_*`) |
| `remove` | `label=` | destroy actor + unregister |
| `palette` | — | list entries: name, system asset, params (name/type/default/meaning), placement notes. The discoverability surface — unknown `effect=` errors carry this list (HATEOAS) |

### The fire/collect seam

`comp.is_active()` reads **False in the spawning dispatch** and True on the next one —
activation lands on an editor tick the blocking dispatch can't observe (same physics as
pcg generate, G30 pattern). `spawn` therefore returns `{"niagara": "activating"}` plus
the registry entry; the next `describe` (or any dispatch's status walk) reads the real
active flag. Do NOT poll in-call. An effect whose `is_active()` is still False on
collect is a **warning finding** with the palette entry and a re-`spawn` next line —
never silent.

### Errors (each carries the next legal move)

- unknown `effect=` → error + palette list + `niagara op=palette`.
- `set` with a param name not in the entry's curated list → **error before touching the
  component**. This is load-bearing: `set_variable_float` with a wrong name is a
  **silent no-op** (probed: no throw, no effect), so the palette list is the only wall
  between the agent and unverifiable writes.
- unknown `label=` → the G60-style error: live effect labels + describe next line.
- duplicate `label=` → error (ueb labels are unique).

## Runtime implementation (`runtime/ue_buttons/niagara.py`, new module)

Mirror `pcg.py`'s shape. Wire into `verbs.py` `_VERBS` + the `SPATIAL` set (status
block yes, undo no, teardown is `remove`). Registry:

```python
# _state.py — hasattr-guarded init (never hot-reloaded)
niagara_fx = {}   # {label: {effect, actor_name, params, pending}}
```

Extend `outliner op=reconcile` (prune dead actors), `level op=clear` (ueb-tag sweep
already catches NiagaraActor — confirm), rehydrate-on-open like G61 groves (meta
rebuilt from the actor: system asset basename → palette reverse-lookup, params read
back via `get_variable_*` for the entry's curated names). Add `NiagaraActor` to
`_ue.substrate_labels()`'s class tells so the floor lint never flags a smoke column as
"floating" (the B11 lesson).

Spawn path: reuse `add`'s placement resolution + tagging helper — `place=` takes the
exact dict `add` takes; a fire "inside the hearth" or "on the chimney top" must go
through the same relational machinery, not fresh math.

New-module reload gotcha (from SPEC-10 build): `niagara.py` won't be in the editor's
running `_RELOADABLE` until an editor restart — manual
`importlib.reload(ue_buttons.niagara)` after each sync while developing.

## First palette entries

Engine-shipped systems found by asset-registry scan (17 total on this install; full
list in the trace). Curate from:

- `/Niagara/DefaultAssets/Templates/Systems/FountainLightweight` — the spike's proven
  system; upward particle fountain. Entry name `fountain`.
- `…/Systems/DirectionalBurst`, `…/RadialBurst`, `…/SimpleExplosion` — one-shot bursts.
- `…/Systems/AttributeReaderTrails` — trails.

**SPIKE-CHECK per entry at curation time**: open the system once in the UI (or read its
asset) to record real user-parameter names; verify each with a `set` + `get_variable_*`
read-back before shipping the entry. The templates are sprite-material generic — expect
"placeholder-grade" visuals; marketplace FX packs (fire/smoke) become entries the same
way when installed. Ship `fountain` + one burst first; that's enough to dogfood.

## Invariants

1. **Never `set` a parameter name that isn't curated in the palette entry** — wrong
   names no-op silently (probed). The palette is the contract.
2. **Activation is observable only on a later dispatch** — spawn returns pending;
   collect gates on `is_active()`. Zero-active on collect is a warning, never silence.
3. **Every mutating result carries `label`** (SPATIAL status block).
4. Placement goes through `add`'s relational machinery — no fresh coordinate math.
5. Palette assets are referenced, never mutated (they're engine plugin content —
   read-only mounts anyway).

## Verification plan (live, over the MCP tools, before commit)

1. `op=palette` lists entries; `op=spawn effect=<bad>` errors with the list.
2. `op=spawn effect=fountain place={...}` on a dogfood level: actor ueb-tagged, visible
   to outliner/feel, pending → next describe shows `active: true`, bounds sane.
3. `op=set` round-trip: write a curated param, `describe` reads the new value back.
4. `op=set` with a bogus param name errors BEFORE the component is touched.
5. `op=remove`: actor gone, registry pruned, reconcile clean.
6. Save → reopen: effect persists, rehydrates into the registry, still active
   (**SPIKE-CHECK**: `auto_activate` survival across reopen was not probed).
7. Dogfood: a fire/fountain in the L2 cave or the next level brief; findings →
   gaps.md/bugs.md per house discipline.

## Ground truth — spike traces (2026-07-05, RC bridge, UE 5.8)

1. Classes present: `NiagaraActor/System/Component/FunctionLibrary/ParameterCollection/
   SystemFactoryNew`. **Absent: `NiagaraEditorLibrary`** (no graph/emitter editing).
2. Asset scan: `get_assets_by_class(NiagaraSystem)` → 17 systems: DefaultSystem,
   VectorFieldVisualization, 6 HairStrands emitters, `/Water/Effects/Niagara/Shoreline/
   NiagaraShore_System`, and the Templates/Systems family (AttributeReaderTrails,
   DirectionalBurst(+Lightweight), FountainLightweight, MinimalLightweight, RadialBurst,
   SimpleExplosion, RenderTargetTexturePainter). `/Niagara` content root: 1,157 assets.
3. Live drive: spawned NiagaraActor at z=20000, `comp.set_asset(FountainLightweight)`,
   `auto_activate=True`, `activate(True)` → `is_active()` **False in-call, True next
   dispatch**. Bounds readable (origin x=116, ext 244×128×128 — the system's initial
   puff). Actor destroyed cleanly.
4. Component API: full typed `set_niagara_variable_*` + `get_variable_*` family;
   `set_variable_float("SpawnRate", 500)` **no-throws even when the name doesn't
   exist** (silent no-op hazard). `reset_system`/`reinitialize_system` present.
   `NiagaraSystem` asset side: zero param/user functions exposed.
