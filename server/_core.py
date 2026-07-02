"""Thin transport core for the ue-buttons MCP server.

The server holds NO scene state. Every verb becomes one Remote Control HTTP call that
runs `ue_buttons.dispatch(...)` inside the editor; the runtime prints one `UEB>>>{json}`
line into LogOutput, which we extract and parse. This mirrors blender-buttons' server/
_core.py, with RC-over-HTTP replacing the TCP socket to the Blender addon.
"""
import json
import os
import time
import urllib.request

from mcp.server.fastmcp import FastMCP

from server._instructions import INSTRUCTIONS

mcp = FastMCP("ue-buttons", instructions=INSTRUCTIONS)

RC_HOST = os.environ.get("UE_RC_HOST", "localhost")
RC_BASE = f"http://{RC_HOST}:30010"
SENTINEL = "UEB>>>"

# Self-bootstrapping snippet: real editor startup runs init_unreal.py (which puts
# Content/Python on sys.path), but if the editor predates the deploy we add it here too,
# so `import ue_buttons` never fails mid-session. Runs via ExecuteFile (multi-line +
# captures print → LogOutput). params are embedded as a PYTHON literal (repr), not JSON —
# JSON's true/false/null aren't valid Python.
_SNIPPET = """import sys, os
_p = os.path.normpath(os.path.join(unreal.Paths.project_content_dir(), 'Python'))
_p in sys.path or sys.path.insert(0, _p)
import ue_buttons
ue_buttons.dispatch({verb!r}, {params})
"""


def _rc_execute(python_code, timeout=60):
    body = json.dumps({
        "objectPath": "/Script/PythonScriptPlugin.Default__PythonScriptLibrary",
        "functionName": "ExecutePythonCommandEx",
        "parameters": {"PythonCommand": python_code,
                       "PythonCommandExecutionMode": "ExecuteFile"},
    }).encode()
    req = urllib.request.Request(RC_BASE + "/remote/object/call", data=body,
                                 headers={"Content-Type": "application/json"}, method="PUT")
    resp = json.load(urllib.request.urlopen(req, timeout=timeout))
    return resp


def call_ue(verb, params=None, timeout=60):
    """Run one verb in the editor and return its parsed result dict. Never raises to the
    tool layer — transport/parse failures come back as {"error": ...}."""
    params = params or {}
    code = _SNIPPET.format(verb=verb, params=repr(params))
    try:
        resp = _rc_execute(code, timeout=timeout)
    except Exception as e:
        return {"error": f"remote control unreachable ({e}). Is the editor running with "
                         f"Remote Control on {RC_BASE}?"}
    out = "".join(l.get("Output", "") for l in resp.get("LogOutput", []))
    for line in out.splitlines():
        if line.startswith(SENTINEL):
            try:
                return json.loads(line[len(SENTINEL):])
            except json.JSONDecodeError as e:
                return {"error": f"bad UEB payload: {e}", "raw": line}
    # No sentinel line → a Python-level error before dispatch could print (e.g. import).
    cr = resp.get("CommandResult") or ""
    return {"error": "no UEB response from runtime", "command_result": cr[:800]}


def render(result):
    """Turn a runtime result dict into the human-facing text: the payload minus the
    status block, then the status block verbatim (it's pre-formatted by the runtime)."""
    if not isinstance(result, dict):
        return str(result)
    if "error" in result:
        return f"⚠ {result['error']}" + (f"\n{result.get('traceback','')}"
                                          if result.get("traceback") else "")
    status = result.pop("status", None)
    head = json.dumps(result, indent=2)
    return head + (f"\n{status}" if status else "")


def poll_screenshot(wsl_path, timeout=15.0, interval=0.5):
    """Wait for an async screenshot file to land on the NTFS share (gaps.md G8). Returns
    True if it appears within the timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if wsl_path and os.path.exists(wsl_path):
            return True
        time.sleep(interval)
    return False
