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

### B14 — pcg op=describe "label omitted → every grove" is unreachable through the MCP tool
Status: OPEN (found 2026-07-05, second pcg dogfood — UEB_PCGMeadow, first drive through
the real MCP tool)

Repro: `pcg op=describe` (no label) → `⚠ no pcg grove labelled 'pcg'` while grove 'wood'
exists. Root cause: the tool signature's `label: str = "pcg"` default is ALWAYS projected
into params, so the runtime (whose `_describe` correctly treats a missing label as
"every grove", pcg.py:430) never sees an omitted label. Fix: `label=None` in the tool
signature, project only when given — the runtime already owns the per-op "pcg" default
for generate/regenerate/cleanup (pcg.py:313/379/406).
