# ue-buttons

Porting the blender-buttons principle to UE5: sidestep the human-optimized interactive
UI and project the domain into agent-space (names, relations, dimensions, legible
perception). Partnership split: human owns taste + experiential playtesting ("does it
feel right"); agent owns precision + mechanical verification ("does it provably work").

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

Verbs: `scene`, `add`, `transform`, `select`, `feel`, `view`, `history`. Every mutating
verb appends the auto-status block and runs inside a `ueb:<id>` transaction kept 1:1 with
the editor undo stack. **Exit test passes**: an agent builds a table (top + 4 legs at
corners) via relational placement only, confirms with `feel`, and `undo_to` tears it down
cleanly. Open items live in `gaps.md` (notably G8 — async screenshot capture).

### Running

```bash
scripts/sync-runtime.sh          # deploy runtime into the UE project
# launch the editor (see below), then this repo's .mcp.json wires the MCP server:
uv run python server/main.py     # or let the Claude Code host start it from .mcp.json
```

`scripts/probe.sh` still verifies the bare bridge / runs one-shot editor Python.

## Next design step

Then the two genuinely novel fronts, where the projection must be invented rather than
ported:

- **Logic**: Blueprint graphs are not Python-authorable — the path is generated C++ +
  Live Coding, or a text DSL compiled server-side. This is the moonshot crux.
- **Temporal feel**: mechanical ground truth from automation/functional tests, Visual
  Logger, navmesh/EQS queries — the agent proves "it works"; the human judges "it feels".
