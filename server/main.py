"""ue-buttons MCP server — the 7 M1 verbs (SPEC-00).

Each @mcp.tool is a thin projection: it forwards a params dict to the editor runtime via
call_ue and renders the result. All scene logic lives in the runtime; this file is the
agent-facing surface. Conventions everywhere: centimetres, +X forward, +Y right, +Z up,
rotation as [yaw, pitch, roll] degrees.

Run:  uv run ue-buttons        (or: uv run python server/main.py)
"""
import sys
from pathlib import Path

_PARENT = str(Path(__file__).resolve().parent.parent)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

from server._core import mcp, call_ue, render, poll_screenshot


@mcp.tool()
def scene(include_all: bool = False) -> str:
    """List the scene's actors, grouped by type, with the level name.

    Scoped to ue-buttons-spawned actors by default; pass include_all=True to see the
    whole level (an Open World map has ~135 engine scaffolding actors). Always reports
    the count of untracked actors.
    """
    return render(call_ue("scene", {"include_all": include_all}))


@mcp.tool()
def add(what: str, label: str, dims: list, place: dict = None) -> str:
    """Spawn a primitive with EXACT centimetre dimensions and relational placement.

    what:  cube | sphere | cylinder | cone | plane
    label: unique human handle (errors on collision)
    dims:  [x, y, z] size in cm (world size, not scale)
    place: relational placement spec (omit → rest on the floor at origin). Forms:
      {"on_floor": true}                         bottom on z=0 at origin
      {"on": "<label>"}                          centered on top of a reference, resting
      {"under": "<label>"}                       centered beneath a reference
      {"between": ["<a>", "<b>"]}                midpoint of two references
      {"centered_on": "<label>"}                 same center as a reference
      {"at_corner": {"of": "<label>", "corner": "front_left|front_right|back_left|
                     back_right", "top": true, "under": false, "inset": <cm>}}
                                                 a footprint corner (top=on top,
                                                 under=hang below, inset pulls inward)
      {"left_of"|"right_of"|"in_front_of"|"behind": "<label>", "gap": <cm>}
                                                 adjacent (left/right = ±Y, front/back = ±X)
      {"mirror_of": "<label>", "axis": "X|Y|Z"}  mirror about world origin
      {"at": [x, y, z]}                          raw coords (documented ripcord only)
    """
    return render(call_ue("add", {"what": what, "label": label, "dims": dims,
                                  "place": place or {}}))


@mcp.tool()
def transform(action: str, target: str, by: list = None, dims: list = None,
              to: list = None) -> str:
    """Move / resize / rotate an actor by label.

    action="nudge":  by=[dx, dy, dz] cm along world axes (+X fwd, +Y right, +Z up)
    action="resize": dims=[x, y, z] new world size in cm
    action="rotate": to=[yaw, pitch, roll] degrees
    """
    p = {"action": action, "target": target}
    if by is not None: p["by"] = by
    if dims is not None: p["dims"] = dims
    if to is not None: p["to"] = to
    return render(call_ue("transform", p))


@mcp.tool()
def select(labels: list = None, clear: bool = False) -> str:
    """Select actors by label, or clear the selection (clear=True). Feeds the
    active/selected fields of the status block."""
    return render(call_ue("select", {"labels": labels or [], "clear": clear}))


@mcp.tool()
def feel(op: str, target: str = None, a: str = None, b: str = None,
         axis: str = "ANY", side: str = "CENTER_Z") -> str:
    """Relational perception — measure, don't guess.

    op="describe" (target):        dims, bounds, on_floor, and relations (rests_on /
                                   directly_under / flush_left_of / flush_right_of /
                                   flush_in_front_of / flush_behind) to other ueb actors.
    op="distance_between" (a,b,axis): centre-to-centre distance; axis=X|Y|Z|ANY.
    op="gap_between" (a,b):        per-axis empty space (negative = overlap) + touching axes.
    op="is_aligned" (a,b,side):    side ∈ TOP|BOTTOM|FRONT|BACK|LEFT|RIGHT|CENTER_X|
                                   CENTER_Y|CENTER_Z (front/back = ±X, left/right = ±Y).
    """
    p = {"op": op, "target": target, "a": a, "b": b, "axis": axis, "side": side}
    return render(call_ue("feel", p))


@mcp.tool()
def view(target: str = None, azimuth: float = 45.0, elevation: float = 25.0,
         distance: float = 500.0, shot: bool = False,
         width: int = 1280, height: int = 720) -> str:
    """Orbit the editor camera around a target and optionally screenshot.

    target:    actor label or [x,y,z] world point (default origin)
    azimuth:   deg around +Z, measured from +X toward +Y
    elevation: deg above the ground plane
    distance:  cm from the target
    shot:      capture a screenshot (async; the file is polled for on the NTFS share)
    """
    p = {"target": target if target is not None else [0, 0, 0],
         "azimuth": azimuth, "elevation": elevation, "distance": distance,
         "shot": shot, "width": width, "height": height}
    result = call_ue("view", p)
    if shot and isinstance(result, dict) and result.get("screenshot_wsl"):
        landed = poll_screenshot(result["screenshot_wsl"])
        result["screenshot_ready"] = landed
        if not landed:
            result["note"] = ("capture pending — the async screenshot hasn't landed; is "
                              "the editor window foregrounded? (gaps.md G8)")
    return render(result)


@mcp.tool()
def history(op: str = "list", id: str = None) -> str:
    """Inspect or rewind the mutation log.

    op="list":            the ordered op log (id, verb, summary).
    op="undo_to" (id):    undo every op after `id`, via the editor's transaction stack.
                          Note: the undo stack is shared with your manual editor edits —
                          a manual edit interleaved with ueb ops can desync this (gaps.md G1).
    """
    return render(call_ue("history", {"op": op, "id": id}))


def main():
    mcp.run()


if __name__ == "__main__":
    main()
