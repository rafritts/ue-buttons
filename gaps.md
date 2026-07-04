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

### G41 — native-linter wrapping hazards: `MAP CHECK` over RC crashes the editor; Data Validation is silent on real defects
Status: OPEN (recorded 2026-07-03 while testing whether stock UE tooling catches G40's
case; informs SPEC-08 before it's fleshed out.)

Facts, all live-verified today:
- `unreal.SystemLibrary.execute_console_command(None, "MAP CHECK")` issued through RC
  dispatch CRASHED UE 5.8 with `EXCEPTION_ACCESS_VIOLATION reading 0x28` (crash dump
  `UECC-Windows-8966F2934F0D67A9EFF48FA23F91A4E2_0000`; crashed session log ends at
  `Cmd: MAP CHECK`). Do NOT issue MAP CHECK over the bridge again; the earlier in-log
  MapCheck result reported `0 Error(s), 0 Warning(s)` anyway — no rule covers G40's case.
- `EditorValidatorSubsystem.is_object_valid(MM_Tree_Trunk, MANUAL)` → `VALID`: stock
  validators have nothing to say about a defective-under-instancing material. The
  subsystem API surface is `is_asset_valid / is_object_valid / validate_assets_with_settings /
  validate_changelist(s) / add_validator` — no `validate_loaded_asset` in 5.8, and
  `is_asset_valid` wants `AssetData`, not a loaded object.
Conclusion for SPEC-08: UE's native linters are a floor, not a roof — wrap them via the
validator-subsystem APIs (never console MAP CHECK through RC), and expect our own rules
(registered via `add_validator` as Python `EditorValidatorBase` subclasses) to carry the
real weight.

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
