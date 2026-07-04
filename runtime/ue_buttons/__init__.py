"""ue_buttons runtime — the in-editor half of the bridge.

Deployed to <project>/Content/Python/ue_buttons/ (synced from the repo). The MCP server
never imports this; it POSTs a one-line snippet over Remote Control:

    import ue_buttons; ue_buttons.dispatch("<verb>", <params-json>)

`dispatch` routes, catches every error, and prints exactly one line —

    UEB>>>{...json...}

— which the server greps out of LogOutput. Everything else in LogOutput is passthrough
noise. Python-side errors become {"error": ...} so the server never scrapes tracebacks.
"""
import importlib
import json
import sys
import traceback

# DEV_RELOAD re-execs handler modules each dispatch. importlib.reload trusts a cached .pyc
# when its recorded source mtime matches the source — and on WSL→NTFS those mtimes collide
# after a re-sync, so reload silently runs STALE bytecode (gaps.md G20, hours lost). Writing
# no bytecode at all removes the trap: every reload compiles straight from source.
sys.dont_write_bytecode = True

from . import _state          # NEVER reloaded — holds history + label state (Q2/G-reload)
from . import _ue
from . import relational
from . import asset
from . import material
from . import heightfield
from . import terrain
from . import map_ref
from . import spline
from . import foliage
from . import render
from . import validate
from . import level
from . import deixis
from . import verbs

# Reload order matters: dependencies before dependents, and _state is absent by design.
# render before validate/verbs — both consume its source-filter predicate (SPEC-03).
_RELOADABLE = [_ue, relational, asset, material, heightfield, terrain, map_ref, spline,
               foliage, render, validate, level, deixis, verbs]

SENTINEL = "UEB>>>"


def dispatch(verb, params=None):
    if _state.DEV_RELOAD:
        for m in _RELOADABLE:
            importlib.reload(m)
    try:
        result = verbs.handle(verb, params or {})
    except Exception as e:
        result = {"error": f"{type(e).__name__}: {e}",
                  "traceback": traceback.format_exc()}
    # One line, no embedded newlines — json.dumps default is single-line.
    print(SENTINEL + json.dumps(result, default=str))
    return result
