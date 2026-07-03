# bugs.md — ue-buttons

Outright defects (wrong output, crash, corrupted state) found while building or driving
ue-buttons. Same discipline as `gaps.md`: a bug is **reproduced, fixed, and the fix
live-verified over the RC bridge**, and then **PRUNED from this file** — a completed bug is
deleted, not left behind with a FIXED banner. This file is the live worklist of what's
still broken; the reasoning behind a fix lives in git history and the code, not here. `B<n>`
numbers are never reused (grep git history for a retired one). Keep the repro and root cause
while a bug is open, not just "fixed".

Distinction from `gaps.md`: gaps are friction, missing capability, or design limits.
bugs are things that are *supposed to work and don't*.

Format: `### B<n> — <title>` · status · repro · root cause · fix · verification.

---

### B7 — MCP tool layer stringifies `view target`, world-point form unreachable

- **Status**: open (found 2026-07-02, L1 replay)
- **Repro**: `view(action="orbit", target=[-1889,2236,576])` through the MCP tool →
  `⚠ no actor labelled '[-1889, 2236, 576]'`. The same params through a raw
  `ue_buttons.dispatch("view", {...})` (list intact) work fine.
- **Root cause**: `server/main.py` types the `target` param as `str`, so the MCP host
  coerces the array to its string repr before it reaches the runtime; the runtime's
  label-or-[x,y,z] duck-typing never sees a list. Any other verb param with a
  union-typed runtime contract but a scalar tool schema has the same exposure.
- **Fix direction**: type it `str | list` (FastMCP/pydantic union) or accept a JSON
  string and parse runtime-side.
