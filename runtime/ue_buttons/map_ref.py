"""Map-position resolution (SPEC-01) — the one place a 2D map point becomes [x, y].

Two forms resolve to the same internal point:
  * polar (preferred): {"from": <anchor>, "bearing": <deg>, "distance": <cm>} — how humans
    give directions; keeps the agent relating to things it placed.
  * absolute: [x, y] in map cm — legal, but expected to be READ OFF view(map), not invented.

Compass: north = +X, east = +Y, bearing measured clockwise from north — numerically identical
to UE yaw. Anchors: "center" (map origin), an actor label, a named terrain, ("path", fraction)
a point along a path, or raw [x, y]. All arithmetic happens here so the model never dead-reckons.
"""
import math

from . import _state
from . import _ue


def resolve(pos):
    """Resolve a map position (polar dict or absolute [x,y]) to [x, y] in map cm."""
    if isinstance(pos, dict):
        if "from" in pos or "bearing" in pos:
            ax, ay = _anchor(pos.get("from", "center"))
            b = math.radians(pos.get("bearing", 0.0))
            d = pos.get("distance", 0.0)
            return [ax + d * math.cos(b), ay + d * math.sin(b)]     # N=+X, E=+Y, cw from N
        if "at" in pos:
            return [pos["at"][0], pos["at"][1]]
    if isinstance(pos, (list, tuple)) and len(pos) >= 2:
        return [float(pos[0]), float(pos[1])]
    raise ValueError(f"cannot resolve map position: {pos!r}")


def _anchor(a):
    """Resolve a polar anchor to [x, y]."""
    if a is None or a == "center":
        return [0.0, 0.0]
    if isinstance(a, (list, tuple)):
        # ("path_label", fraction) → a point along a path
        if len(a) == 2 and isinstance(a[0], str):
            return _path_point(a[0], a[1])
        return [float(a[0]), float(a[1])]                            # raw-coord anchor
    if isinstance(a, str):
        act = _ue.find_by_label(a)
        if act is not None:
            c = _ue.bounds(act)["center"]
            return [c[0], c[1]]
        meta = _state.landscapes.get(a)
        if meta is not None:
            return [meta["origin"][0], meta["origin"][1]]
        raise ValueError(f"unknown anchor '{a}' (not an actor, terrain, or 'center')")
    raise ValueError(f"unknown anchor form: {a!r}")


def _path_point(label, fraction):
    from . import path as _path
    pt, _tan = _path.point_and_tangent(label, fraction)
    return [pt[0], pt[1]]
