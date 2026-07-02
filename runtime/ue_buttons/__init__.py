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
import traceback

from . import _state          # NEVER reloaded — holds history + label state (Q2/G-reload)
from . import _ue
from . import relational
from . import asset
from . import terrain
from . import landscape
from . import map_ref
from . import path
from . import scatter
from . import verbs

# Reload order matters: dependencies before dependents, and _state is absent by design.
_RELOADABLE = [_ue, relational, asset, terrain, landscape, map_ref, path, scatter, verbs]

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
