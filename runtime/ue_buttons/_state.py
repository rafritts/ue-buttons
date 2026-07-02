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


_shot_counter = [0]


def next_shot_id():
    """Separate counter for screenshot filenames — view is non-mutating and must NOT
    consume an op id (that would put cosmetic gaps in the history numbering)."""
    _shot_counter[0] += 1
    return f"shot{_shot_counter[0]:03d}"
