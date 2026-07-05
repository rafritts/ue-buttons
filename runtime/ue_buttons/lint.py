"""`play op=lint` — SPEC-09 runtime lint: PIE-based checks for defects that are invisible
statically and only exist while the game runs (ensures on BeginPlay, over-budget frames,
ground that doesn't hold under the pawn).

TWO-CALL, exactly like `play op=census` — and for two compounding reasons:
  1. PIE spin-up is asynchronous (the game world does not exist in the dispatch that
     requests Play), and
  2. per-frame sampling REQUIRES the game thread to tick freely between start and read,
     which a single blocking dispatch cannot allow (Python holds the game thread).
So call 1 (editor) runs the STATIC pre-scan, starts Play, and arms the sampler; call 2
(in PIE — `play` is B8-exempt) reads the samplers, ends Play, and returns findings.

The pre-scan is not optional politeness: requesting Play with a compile-broken Blueprint
throws a BLOCKING modal ("Blueprint Asset Compilation Error") that hangs the RC bridge on
the game thread until a human clicks it — the two-call pattern would deadlock on call 2.
So a defect that can be seen statically is caught statically here, before Play is ever
requested; PIE is the last resort, never the first reach (SPEC-09 design refresh).

Findings mirror SPEC-08: each carries severity + provenance + a ready-to-fire `next`
(HATEOAS). Build order: logs (this file) → budget (this file) → traverse (next increment).
"""
import os
import time

import unreal

from . import _state
from . import _ue

_KNOWN_CHECKS = ("logs", "budget", "traverse")
_DEFAULT_CHECKS = ["logs"]
_SECONDS_DEFAULT = 10.0
_SECONDS_CAP = 15.0            # G30: v1 keeps every run inside one HTTP dispatch's budget

# We drive UE from Python and do NOT author Blueprints, so the only Blueprints under our
# own content roots are throwaway/WIP spikes — exactly the ones that break and deadlock
# PIE. Marketplace/engine packs ship pre-compiled and are assumed clean; scanning all ~333
# project Blueprints would be slow and would surface their pre-existing warnings as noise.
_AUTHORED_ROOTS = ("UEB", "Maps")

# Log lines the runtime tail treats as findings, most severe first. UE writes
# "LogFoo: Error: msg" / "LogFoo: Warning: msg"; ensures surface as an explicit phrase.
_LOG_ERROR_MARKERS = (": Error:", "Ensure condition failed", "Fatal error", "LogBlueprintUserMessages: Error")
_LOG_WARN_MARKERS = (": Warning:",)
_LOG_TAIL_SAMPLE = 12          # cap sampled lines per severity so a finding stays legible


# ── entry (routed from verbs._v_play when op=lint) ────────────────────────────────────
def run(p):
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if les.is_in_play_in_editor():
        return _collect(p, les)
    return _start(p, les)


# ── call 1 (editor): pre-scan, arm samplers, begin Play ───────────────────────────────
def _start(p, les):
    checks, unknown = _resolve_checks(p)
    if unknown:
        return {"error": f"unknown lint check(s) {unknown}. known: {list(_KNOWN_CHECKS)}"}

    # STATIC pre-scan — always, regardless of requested checks: it guards the bridge from
    # the compile-error modal deadlock, so it must run before begin_play unconditionally.
    broken = _scan_broken_blueprints()
    if broken:
        return {"lint": "blocked",
                "verdict": "COMPILE ERRORS would block Play with a modal — refusing to "
                           "start PIE (it would hang the bridge until a human clicks it)",
                "findings": broken,
                "next": "fix or delete the compile-broken Blueprint(s) above, then re-run "
                        "play op=lint"}

    if "traverse" in checks:
        # traverse needs a route= spline and the game-world trace-walk (next increment).
        return {"error": "the 'traverse' check is not built yet (SPEC-09 in build: "
                         "logs + budget are live, traverse is the next increment). "
                         "Run play op=lint checks=[logs,budget] for now."}

    seconds = min(float(p.get("seconds") or _SECONDS_DEFAULT), _SECONDS_CAP)
    log_path, log_offset = _log_cursor()
    run_rec = {"checks": checks, "seconds": seconds,
               "budget_ms": p.get("budget_ms"),
               "log_path": log_path, "log_offset": log_offset,
               "started": time.time()}

    if "budget" in checks:
        _arm_sampler()

    _state.lint_run = run_rec
    les.editor_request_begin_play()
    return {"lint": "sampling", "checks": checks,
            "note": f"PIE is running the lint window — call play op=lint AGAIN in ~{int(seconds)}s; "
                    "that call reads the samplers, ends Play, and returns findings",
            "pre_scan": "clean (no compile-broken authored Blueprints)"}


# ── call 2 (in PIE): read samplers, end Play, return findings ─────────────────────────
def _collect(p, les):
    run_rec = getattr(_state, "lint_run", None)
    if run_rec is None:
        # Play was started outside op=lint — end it and reset rather than read stale state.
        _disarm_sampler()
        les.editor_request_end_play()
        return {"error": "no lint run in progress — Play was started outside op=lint. "
                         "Play is being stopped; re-issue play op=lint."}

    elapsed = round(time.time() - run_rec["started"], 1)
    findings = []
    if "logs" in run_rec["checks"]:
        findings += _log_tail_findings(run_rec)
    if "budget" in run_rec["checks"]:
        findings += _budget_findings(run_rec)

    # teardown — ALWAYS, even if a check raised (B8: every run ends with Play stopped)
    _disarm_sampler()
    les.editor_request_end_play()
    _state.lint_run = None

    for i, f in enumerate(findings, 1):
        f["n"] = i
    return {"lint": "done", "checks": run_rec["checks"],
            "window_seconds": elapsed,
            "passed": not findings,
            "findings": findings,
            "verdict": ("clean — nothing surfaced in the PIE window"
                        if not findings else
                        f"{len(findings)} runtime finding(s) in a {elapsed}s window")}


# ── static pre-scan: compile-broken authored Blueprints ───────────────────────────────
def _authored_blueprint_pkgs():
    ar = unreal.AssetRegistryHelpers.get_asset_registry()
    out = []
    for a in ar.get_assets_by_class(
            unreal.TopLevelAssetPath("/Script/Engine", "Blueprint"), True):
        pn = str(a.package_name)
        parts = pn.split("/")
        if len(parts) > 2 and any(parts[2].startswith(r) or parts[2] == r
                                  for r in _AUTHORED_ROOTS):
            out.append(pn)
    return out


def _scan_broken_blueprints():
    """Compile each authored Blueprint and flag BS_ERROR. Compiling is how UE decides at
    Play time, so this is the faithful check; it does not dirty the package (verified).
    Near-free in practice — we author ~zero Blueprints, so this set is tiny."""
    findings = []
    for pn in _authored_blueprint_pkgs():
        try:
            bp = unreal.load_asset(pn)
            if not isinstance(bp, unreal.Blueprint):
                continue
            unreal.BlueprintEditorLibrary.compile_blueprint(bp)
            if bp.get_editor_property("status") == unreal.BlueprintStatus.BS_ERROR:
                findings.append({
                    "check": "logs", "severity": "error",
                    "summary": f"Blueprint has unresolved compile errors: {pn}",
                    "provenance": "static compile pre-scan (BlueprintStatus.BS_ERROR)",
                    "next": f"open {pn} to fix the errors, or asset op=delete it if throwaway"})
        except Exception as e:
            findings.append({
                "check": "logs", "severity": "warning",
                "summary": f"could not compile-check Blueprint {pn}: {type(e).__name__}",
                "provenance": "static compile pre-scan (exception)",
                "next": f"open {pn} in the editor to inspect it"})
    return findings


# ── logs: runtime Output Log tail over the PIE window ─────────────────────────────────
def _active_log_path():
    """The log file the running editor is writing to = newest-mtime real .log (backups and
    the cef browser log excluded). Chosen over an in-process sink because a file read is
    certain to work with no engine-callback plumbing."""
    log_dir = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_log_dir())
    if not os.path.isdir(log_dir):
        return None
    best, best_mtime = None, -1.0
    for name in os.listdir(log_dir):
        if not name.endswith(".log") or "-backup-" in name or name.startswith("cef"):
            continue
        path = os.path.join(log_dir, name)
        try:
            m = os.path.getmtime(path)
        except OSError:
            continue
        if m > best_mtime:
            best, best_mtime = path, m
    return best


def _log_cursor():
    """Byte offset at begin_play — call 2 reads the tail from here, so only the run
    window's lines are scanned."""
    path = _active_log_path()
    if not path:
        return None, 0
    try:
        return path, os.path.getsize(path)
    except OSError:
        return path, 0


def _log_tail_findings(run_rec):
    path = run_rec.get("log_path")
    if not path or not os.path.exists(path):
        return [{"check": "logs", "severity": "warning",
                 "summary": "could not locate the active Output Log file",
                 "provenance": "log-tail (no active .log resolved)",
                 "next": "re-run; if it persists the log dir path may have changed"}]
    try:
        with open(path, "rb") as f:
            f.seek(run_rec.get("log_offset", 0))
            tail = f.read().decode("utf-8", "ignore")
    except OSError as e:
        return [{"check": "logs", "severity": "warning",
                 "summary": f"could not read the Output Log tail: {type(e).__name__}",
                 "provenance": "log-tail (read error)", "next": "re-run play op=lint"}]

    errors, warnings = [], []
    for line in tail.splitlines():
        if any(m in line for m in _LOG_ERROR_MARKERS):
            errors.append(line.strip())
        elif any(m in line for m in _LOG_WARN_MARKERS):
            warnings.append(line.strip())

    findings = []
    if errors:
        findings.append({
            "check": "logs", "severity": "error",
            "summary": f"{len(errors)} error/ensure line(s) in the PIE run window",
            "provenance": f"Output Log tail ({os.path.basename(path)}, run window)",
            "sample": errors[:_LOG_TAIL_SAMPLE],
            "next": "read the sampled lines; each names its LogCategory + message to chase"})
    if warnings:
        findings.append({
            "check": "logs", "severity": "warning",
            "summary": f"{len(warnings)} warning line(s) in the PIE run window",
            "provenance": f"Output Log tail ({os.path.basename(path)}, run window)",
            "sample": warnings[:_LOG_TAIL_SAMPLE],
            "next": "triage the sampled warnings; most are benign engine chatter"})
    return findings


# ── budget: per-frame time sampling via the slate post-tick callback ──────────────────
def _arm_sampler():
    _state.lint_frames = []

    def _tick(delta_seconds):
        try:
            _state.lint_frames.append(float(delta_seconds))
        except Exception:
            pass

    try:
        _state.lint_sampler = unreal.register_slate_post_tick_callback(_tick)
    except Exception:
        _state.lint_sampler = None


def _disarm_sampler():
    h = getattr(_state, "lint_sampler", None)
    if h is not None:
        try:
            unreal.unregister_slate_post_tick_callback(h)
        except Exception:
            pass
    _state.lint_sampler = None


def _budget_findings(run_rec):
    frames = list(getattr(_state, "lint_frames", []))
    if len(frames) < 5:
        return [{"check": "budget", "severity": "warning",
                 "summary": f"too few frames sampled ({len(frames)}) to judge frame time",
                 "provenance": "slate post-tick sampler",
                 "next": "re-run with a longer seconds= so the sampler collects more frames"}]
    ms = sorted(f * 1000.0 for f in frames)
    mean = sum(ms) / len(ms)
    p95 = ms[min(len(ms) - 1, int(round(0.95 * (len(ms) - 1))))]
    budget = run_rec.get("budget_ms")
    stats = {"frames": len(ms), "mean_ms": round(mean, 2),
             "p95_ms": round(p95, 2), "max_ms": round(ms[-1], 2)}
    if budget is None:
        # No declared budget → report the distribution, don't judge (not a finding).
        return [{"check": "budget", "severity": "info",
                 "summary": f"frame time over {len(ms)} frames: mean {stats['mean_ms']}ms, "
                            f"p95 {stats['p95_ms']}ms, max {stats['max_ms']}ms",
                 "provenance": "slate post-tick sampler (PIE window)",
                 "stats": stats,
                 "next": "pass budget_ms= (e.g. 16.6 for 60fps) to turn this into a pass/fail check"}]
    if p95 > float(budget):
        return [{"check": "budget", "severity": "error",
                 "summary": f"over budget: p95 frame time {stats['p95_ms']}ms exceeds "
                            f"the {budget}ms budget (mean {stats['mean_ms']}ms, max {stats['max_ms']}ms)",
                 "provenance": "slate post-tick sampler (PIE window)",
                 "stats": stats,
                 "next": "profile the level near the pawn; reduce instance density or draw calls"}]
    return []


# ── shared ────────────────────────────────────────────────────────────────────────────
def _resolve_checks(p):
    raw = p.get("checks")
    if not raw:
        return list(_DEFAULT_CHECKS), []
    if isinstance(raw, str):
        raw = [raw]
    unknown = [c for c in raw if c not in _KNOWN_CHECKS]
    return [c for c in raw if c in _KNOWN_CHECKS], unknown
