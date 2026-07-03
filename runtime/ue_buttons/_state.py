"""Module-wide mutable state — the ONE module hot-reload must never touch.

`dispatch` reloads the handler/helper modules on every call (dev flag) so runtime
edits land without an editor restart. If this module were reloaded too, every reload
would wipe the history log and the label registry — the exact state that must survive
an edit. So the reload list in __init__ deliberately EXCLUDES _state, and every other
module reaches this state via `from . import _state` (a rebind to the same live module,
never a reload). Blender-buttons keeps the same discipline (extension/state.py).
"""

# Dev flag: when True, dispatch reloads handler modules before routing. Flip to False
# to freeze the runtime (marginally faster, no reload surprises) once things are stable.
DEV_RELOAD = True

# NOTE on the reload boundary (Q2): dispatch reloads the handler/helper modules but NOT
# this one, so the history log + counters survive runtime edits. The tradeoff: adding or
# renaming something IN this module won't take effect until _state is force-reloaded
# (importlib.reload) or the editor restarts — and a force-reload WIPES history by design.
# That's correct: a _state schema change is a code change, not a live runtime tweak.

# ── history / undo ────────────────────────────────────────────────────────────
# One entry per mutating op, in order. Kept 1:1 with the editor's transaction stack:
# each logged op corresponds to exactly one `begin/end_transaction` labeled `ueb:<id>`,
# so `undo_to(id)` = issue (len(history) - index_after_id) console TRANSACTION UNDOs.
# The 1:1 invariant is load-bearing — blender-buttons gaps.md E1 records the day it
# desynced and undo(2) wiped a 27-op build back to the startup file. Read-only and
# nav verbs NEVER append here (see NON_LOGGING_VERBS in verbs.py).
history = []          # [{"id","verb","summary","label"}]
_undone = []          # ops undone and available to redo (cleared on any new op)
_counter = [0]


def reserve_op_id():
    """Mint the next op id BEFORE the transaction opens, so the transaction label
    (`ueb:<id>`) and the eventual history entry carry the identical id. Monotonic
    counter — lives here, so it survives hot-reloads of the handler modules."""
    _counter[0] += 1
    return f"op{_counter[0]:03d}"


def log_op(op_id, verb, summary, label):
    """Record a completed mutating op under a PRE-RESERVED id. One call per transaction
    keeps history 1:1 with the undo stack (gaps.md G1)."""
    history.append({"id": op_id, "verb": verb, "summary": summary, "label": label})
    _undone.clear()   # a new op forks history; any redo branch is dead
    return op_id


def mark_undone(n):
    """Move the last n ops from history onto the redo stack — mirrors the N console
    undos just issued, so history stays 1:1 with the live transaction stack."""
    if n <= 0:
        return
    moved = history[-n:]
    del history[-n:]
    _undone.extend(reversed(moved))


def last_op():
    return history[-1] if history else None


# ── asset measurement cache (SPEC-01 E1) ───────────────────────────────────────
# Loading a StaticMesh to read its bounds/pivot/materials is the one expensive step in
# the `asset` verb (registry tags give Nanite/tris for free, but not dimensions). The
# measured dict is cached here keyed by asset package path, so the first `inventory` of a
# 381-mesh pack pays the load once and every later call is registry-cheap. Lives in
# _state precisely so a handler hot-reload (which reloads asset.py) never drops it. The
# on-disk `whats_new` snapshot is separate (survives editor restart); this in-memory
# cache is invalidated when whats_new detects the registry changed under it.
dims_cache = {}       # {asset_path: {measured dict}}
dims_cache_loaded = [False]   # disk cache hydrated into dims_cache exactly once per session

# ── SPEC-01 domain registries (survive handler hot-reload; live in never-reloaded _state) ──
# Terrain / path / scatter carry declarative state the actor alone can't reconstruct — the
# feature list that synthesised a heightfield, the waypoints behind a spline, the seed+rules
# behind a scatter population. Keyed by label so describe/regenerate/view(map) can reason
# about them and rebuild deterministically. Persisted to disk by their verbs where restart
# survival matters (terrain heightfields especially).
landscapes = {}       # {label: {origin, size, base_height, resolution, features:[...]}}
paths = {}            # {label: {points:[[x,y,z],...], width, tangents:[[x,y],...]}}
scatters = {}         # {label: {meshes, region, density, seed, rules, counts}}

# ── SPEC-02 validate floor (lives here so a handler hot-reload never wipes it) ──
# The declared-intent registry (`validate op=expect`) and the epistemic-drift accumulator
# behind the periodic re-ground. Both describe THIS level's arrangement; they are correct
# to survive a runtime edit but should reset on level load — there is no level-load hook
# yet (gaps.md G16), so for now they die only on editor restart. Auto-GC in validate.py
# (`_prune_dead_intents`) keeps the registry from accumulating dead subjects.
intents = []          # [{check, a, b, reason, status, source, max_depth?, depth_at_decl?}]
drift = [0.0]         # single-cell accumulator (list so it survives `from . import _state`)


def cache_dims(path, measured):
    dims_cache[path] = measured
    return measured


def cached_dims(path):
    return dims_cache.get(path)


def invalidate_dims(paths=None):
    """Drop measured dims for `paths` (list) or the whole cache (None). Called by
    whats_new when the registry changed, so re-measurement picks up re-imports."""
    if paths is None:
        dims_cache.clear()
    else:
        for p in paths:
            dims_cache.pop(p, None)
