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
from mcp.server.fastmcp import Image


@mcp.tool()
def scene(include_all: bool = False, op: str = None) -> str:
    """List the scene's actors, grouped by type, with the level name.

    Scoped to ue-buttons-spawned actors by default; pass include_all=True to see the
    whole level (an Open World map has ~135 engine scaffolding actors). Always reports
    the count of untracked actors.

    op="streaming" (SPEC-03 link 1): the WorldPartition residency picture — is the world
      partitioned, its data layers + effective runtime state, and per-actor
      is_spatially_loaded/runtime_grid. Says so plainly when the map isn't partitioned.
    op="reconcile" (SPEC-03, closes G16): diff the ueb registry against the editor's own
      tally — clean / dirty (self|external attribution) / orphaned / untracked — and GC
      orphaned registry entries, so a level change can't leave a permanent phantom.
    """
    if op in ("streaming", "reconcile"):
        return render(call_ue("scene", {"op": op}))
    return render(call_ue("scene", {"include_all": include_all}))


@mcp.tool()
def add(label: str, what: str = None, asset: str = None, dims: list = None,
        place: dict = None, yaw: float = None, facing: str = None) -> str:
    """Spawn a primitive OR a project asset with relational placement.

    Two spawn modes (give exactly one of what= / asset=):
      what:  cube | sphere | cylinder | cone | plane — a primitive at EXACT cm dims.
             ALSO: player_start — "insert the player HERE facing THAT" (G35). RELOCATES the
             level's existing PlayerStart rather than shadowing it (a second start competes
             by priority), seats the capsule on the traced ground, and takes the usual
             place/yaw/facing vocabulary. dims not accepted. Re-running with the same label
             is legal (relocate semantics).
      asset: a project StaticMesh or Blueprint by inventory name (see the `asset` verb) or
             full /Game path — e.g. "Wall_Window_4m", "Branch_Norway_Maple_Live_03", or a
             prebuilt cabin Blueprint. Ambiguous short names error with candidates. Placed
             at NATIVE scale (marketplace dims are placement information, not a resize
             invite); a dims= override scales and warns. A base-pivot mesh (tree/wall) is
             grounded correctly — placement targets its bounds, not its origin.

    label: unique human handle (errors on collision)
    dims:  [x, y, z] size in cm — required for primitives, optional override for assets
    yaw:   spawn rotation in degrees (compass/UE yaw: north=+X, clockwise)
    place: relational placement spec (omit → rest on the floor at origin). Forms:
      {"ground": true}  or  {"on": "ground"}    drop onto the terrain by a downward trace
                                                 (combine with other keys: they set x/y,
                                                 ground sets z)
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
    p = {"label": label, "place": place or {}}
    if what is not None: p["what"] = what
    if asset is not None: p["asset"] = asset
    if dims is not None: p["dims"] = dims
    if yaw is not None: p["yaw"] = yaw
    if facing is not None: p["facing"] = facing
    return render(call_ue("add", p))


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
    op="render_state" (target):    SPEC-03 — walk the render gating chain for one actor or
                                   scatter population: per-link verdict (shown / bounded /
                                   in-range / materialised / render-data) + the fix, and a
                                   DRAWS / WILL-NOT-DRAW verdict. The deep-dive behind the
                                   status block's one-line `render:` summary.
    """
    p = {"op": op, "target": target, "a": a, "b": b, "axis": axis, "side": side}
    return render(call_ue("feel", p))


@mcp.tool()
def view(action: str = "orbit", target: str | list = None, azimuth: float = 45.0,
         elevation: float = 25.0, distance: float = 500.0, shot: bool = False,
         width: int = 1280, height: int = 720, label: str = "terrain",
         fov: float = 90.0):
    """Orbit the editor camera + screenshot, OR the top-down site map, OR computed
    visibility (framing/occlusion as NUMBERS — never read a render back).

    action="map" (label): a labelled top-down site plan of the terrain — shaded height, a
      coordinate grid every 20 m (axis labels in map cm), and markers for every ueb actor,
      path, and scatter region. North=+X (up), east=+Y (right), matching UE yaw. This is the
      grounding for absolute [x,y]: read waypoints/feature centres OFF the map (derived, not
      divined). Rendered server-side (no async-screenshot dependency).

    action="framing" (target, fov): SPEC-03 — project the target's world AABB through the
      editor viewport camera → frac_w/frac_h (screen coverage), est_px (the sub-pixel tell),
      clipped edges, in_front, and a FRAMED / SUB-PIXEL / CLIPPED / OFF-FRAME verdict. Every
      number is stamped with its frame reference (resolution + FOV) — coverage is meaningless
      without it. Answers "is it framed, is it big enough" without rendering a frame.
    action="visible" (target, fov): is the target actually SEEN or hidden behind other
      geometry — raycasts from the camera to the target (occluded_fraction + verdict), not a
      screenshot. Together these tell sub-pixel vs off-frustum vs occluded vs absent apart.

    action="orbit" (default):
      target:    actor label or [x,y,z] world point (default origin)
      azimuth:   deg around +Z, measured from +X toward +Y
      elevation: deg above the ground plane
      distance:  cm from the target
      shot:      capture a screenshot (async; polled on the NTFS share — needs the editor
                 window foregrounded, gaps.md G8)
    """
    if action in ("framing", "visible"):
        return render(call_ue("view", {"action": action, "target": target, "fov": fov}))
    if action == "map":
        import os
        from server import mapview
        data = call_ue("view", {"action": "map", "label": label})
        if isinstance(data, dict) and "error" in data:
            return render(data)
        out = os.path.join(os.environ.get("UE_SCRATCH", "/tmp"), "ueb_map.png")
        mapview.render(data, out)
        return Image(path=out)
    p = {"target": target if target is not None else [0, 0, 0],
         "azimuth": azimuth, "elevation": elevation, "distance": distance,
         "shot": shot, "width": width, "height": height}
    result = call_ue("view", p)
    if shot and isinstance(result, dict) and result.get("screenshot_wsl"):
        landed = poll_screenshot(result["screenshot_wsl"])
        result["screenshot_ready"] = landed
        if not landed:
            result["screenshot_failed"] = True
            result["message_for_user"] = (
                "📷 Screenshot couldn't be captured. The Unreal Editor only renders frames "
                "when its window is focused — while it's in the background (as it is when I "
                "drive it from WSL) there's no frame to save. To get a screenshot: click the "
                "Unreal Editor window to bring it to the foreground, then ask again. (The "
                "camera IS aimed correctly — only the image capture needs focus.)")
    return render(result)


@mcp.tool()
def asset(action: str = "packs", pack: str = None, asset: str = None,
          query: str = None, kind: str = "mesh", family: str = None,
          measure: bool = False, budget: int = 60, commit: bool = True,
          seconds: float = 20.0, parent: str = None, name: str = None,
          textures: dict = None, scalars: dict = None, folder: str = None) -> str:
    """Perception over the project's Content — "what can I build with, and how big is it?"

    All dimensions are centimetres. Marketplace meshes are reported at native scale; the
    dims are placement information, not an invitation to resize (a 400 cm wall is 400 cm
    because its doorframe is human-sized). Pivot is reported per asset — base (origin at
    the foot: trees, walls) vs center — because grounding math depends on it.

    action="packs":                  top-level /Game roots, per-class counts, one-line
                                     character. Cheap (registry only).
    action="inventory" (pack):       COMPACT by default — one dict per inferred FAMILY
                                     (Pine_Tree_01..05 → family Pine_Tree) with variant
                                     names, tris, Nanite, and where measured: height,
                                     footprint (widest of x/y) and aspect_h_over_w — the
                                     SILHOUETTE tells (aspect ≈1 reads as a bush/blob; a
                                     trunk-and-canopy tree runs well above 1 — don't pick
                                     forest species on height alone). Measuring a mesh
                                     means loading it, so dims are filled lazily:
                                       measure=True [budget=N, seconds=S]: warm the dims
                                         cache in bounded batches (≤N meshes AND ≤S seconds
                                         of wall-clock, defaults 60/20 s) — repeat until
                                         complete; never blocks the bridge.
                                       family="Pine_Tree": full per-variant detail for one
                                         family, measuring just those. Measured dims persist
                                         to disk (survive editor restart).
    action="describe" (asset):       one asset in full — dims, pivot, material slots,
                                     collision, dependency/referencer counts. Short name or
                                     full /Game path; errors with candidates if ambiguous.
                                     On a MATERIAL: the vet (G32) — master + parent chain,
                                     domain/blend, exposed parameters, and warnings for
                                     world-position-offset (the mesh will MOVE), a master
                                     outside /Game, or a non-surface domain. Run it BEFORE
                                     dressing anything in an unknown material.
    action="instance_material" (parent, name, textures, scalars, folder):
                                     author a MaterialInstanceConstant of a master —
                                     textures={param: texture name}, scalars={param: value};
                                     param names validated against the master, every set
                                     verified by read-back. folder default /Game/UEB_Materials.
    action="find" (query, kind):     name-substring search; kind=mesh|blueprint|skeletal|
                                     material|any (material finds surfaces for landscape
                                     material= / path surface).
    action="whats_new" (commit):     diff the registry against a persisted snapshot — how
                                     a freshly-downloaded pack becomes visible. commit=False
                                     peeks without updating the snapshot.
    """
    p = {"action": action, "pack": pack, "asset": asset, "query": query,
         "kind": kind, "family": family, "measure": measure, "budget": budget,
         "commit": commit, "seconds": seconds}
    for k, v in (("parent", parent), ("name", name), ("textures", textures),
                 ("scalars", scalars), ("folder", folder)):
        if v is not None:
            p[k] = v
    # measure / family-drill load meshes — give them room; default inventory is cheap.
    timeout = 180 if (measure or family) else 60
    return render(call_ue("asset", p, timeout=timeout))


@mcp.tool()
def scatter(action: str = "create", label: str = "scatter", meshes: list = None,
            region: dict = None, density_per_100m2: float = None, seed: int = 1337,
            rules: dict = None, terrain: str = "terrain", pack: str = None) -> str:
    """Populations, not actors — declare rules, get a reproducible, path-respecting stand.

    One labelled actor holds the whole population (HISM instances), never thousands of rows.
    Ground z + slope come from world traces, so instances conform to the real terrain.
    Spatial verb (not history-undoable); teardown is action="remove".

    action="create":
      meshes:  inventory FAMILY names, optional weight — ["Pine_Tree", "Black_Alder:0.3"]
               (variants randomised per instance). A family that resolves across MULTIPLE
               packs errors with pack-attributed candidates (G31) — scope with pack= or
               pass explicit variant names.
      pack:    scope family resolution to one /Game/<pack> root.
      region:  {"kind":"circle","at":[x,y],"radius":cm} | {"kind":"rect","at":[x,y],
               "size":[w,h]} | {"kind":"polygon","points":[[x,y],...]} | {"kind":"landscape"}
               (the whole terrain). MAP coords.
      density_per_100m2:  instances per 100 m² (or set rules.min_spacing_cm).
      seed:    determinism — same seed + rules ⇒ same stand.
      rules:   {min_spacing_cm, max_slope_deg, align_to_slope (rocks yes / trees no),
               scale_jitter:[lo,hi], yaw_random, clear_margin, clear_of:[path/actor labels,
               regions]}. DEFAULT: every scatter auto-clears existing paths (width/2+margin)
               and buildings (footprint+margin) — the path stays open THROUGH the trees.
               Spacing below the measured canopy width warns (clipped-geometry tell): derive
               min_spacing_cm from the widest scattered family's footprint, never intuition.
    action="describe": counts per family, region, seed, rules — enough to reason/regenerate.
    action="regenerate" (seed): same rules, new dice — the "reroll that stand" button.
    action="remove": delete the whole stand as a unit.
    """
    p = {"action": action, "label": label, "seed": seed, "terrain": terrain}
    for k, v in (("meshes", meshes), ("region", region), ("pack", pack),
                 ("density_per_100m2", density_per_100m2), ("rules", rules)):
        if v is not None:
            p[k] = v
    return render(call_ue("scatter", p, timeout=240))


@mcp.tool()
def path(action: str = "create", label: str = "path", points: list = None,
         route: dict = None, width: float = None, at_fraction: float = None,
         terrain: str = "terrain", blend_margin: float = None, material: str = None,
         lift: float = None, tile: float = None) -> str:
    """Paths as first-class intent — a winding route draped over the terrain (SPEC-01 E4).

    All positions are MAP points: polar {"from":<anchor>,"bearing":deg,"distance":cm}
    (anchor = "center" | actor label | terrain | ["path_label", fraction]) or absolute [x,y]
    read off view(map). Compass: north=+X, bearing clockwise = UE yaw. z is draped onto the
    terrain by tracing. Spatial verb (not history-undoable).

    action="create" (points | route, width):
        points=[map position, ...]  — waypoints; a smooth Catmull-Rom curve runs through them.
        route={"start":<pos>, "start_bearing":deg, "steps":[...]} — a WALK; each step is
          {"bearing":deg,"distance":cm} (absolute) or {"turn":±deg,"distance":cm} (relative —
          the natural encoding of "winding"). Returns every resolved waypoint.
    action="carve" (terrain, blend_margin): flatten the terrain to grade along the route,
        feathered to the path width — cuts the geometric bed (one mesh rebuild). If the path
        already has a surface strip, it is re-draped automatically.
    action="surface" (material, width, lift, tile): make the path VISIBLE — a thin material
        ribbon draped onto the ground along the route (a carve alone is nearly invisible
        without a material contrast, G25). material = a material name or /Game path (find
        one via asset find kind=material — e.g. a dirt/gravel Megascans surface); lift = cm
        above the ground (default 3); tile = cm per texture repeat (default 400). Idempotent:
        re-running replaces the strip. Typical order: create → carve → surface.
    action="describe" (at_fraction): length, waypoints, and (at_fraction) the world point +
        tangent + bearing there — the hamlet's skeleton for `along=`/`facing=` placement.
    action="remove": forget the path (and delete its surface strip).

    Placement (on add/scatter): place={"along":{"path":label,"fraction":f,"side":"left|right",
    "offset":cm}} puts a thing beside the path; add(facing=label) turns it to face the path.
    """
    p = {"action": action, "label": label, "terrain": terrain}
    for k, v in (("points", points), ("route", route), ("width", width),
                 ("at_fraction", at_fraction), ("blend_margin", blend_margin),
                 ("material", material), ("lift", lift), ("tile", tile)):
        if v is not None:
            p[k] = v
    return render(call_ue("path", p, timeout=180))


@mcp.tool()
def landscape(action: str = "create", label: str = "terrain", size: list = None,
              origin: list = None, base_height: float = None, features: list = None,
              region: dict = None, height: float = None, blend_margin: float = None,
              at: list = None, replace: bool = False, resolution: list = None,
              material: str = None, uv_tile_cm: float = None) -> str:
    """Terrain as a heightfield — you describe landforms, the runtime synthesises the mesh.

    All coords are MAP centimetres (converted to terrain-local internally). Compass: north=+X,
    east=+Y, bearing clockwise = UE yaw. Terrain is a collidable mesh, so ground-snap / scatter
    / path-drape trace it directly. NOT undoable via history (see the `undoable` field).
    While a ueb terrain exists, ground traces IGNORE the engine template's z=0 Landscape —
    your terrain is the ground, even below zero (though base_height is still the cleaner way
    to keep geometry clear of the template plane).

    action="create" (size, origin, base_height, material): new flat terrain. size=[x_cm,y_cm]
        (hamlet ~[20000,20000] = 200 m); origin = map centre (default [0,0]).
    action="shape" (features, replace, material): apply landform features, composed in order —
        {"kind":"valley","axis":"x|y","floor_width":cm,"wall_height":cm,"roughness":0..1}
        {"kind":"hill"|"ridge","at":[x,y],"radius":cm,"height":cm,"length":cm,"axis":"x|y"}
        {"kind":"noise","amplitude":cm,"scale":cm,"octaves":n,"seed":n}
        {"kind":"plateau","at":[x,y],"radius":cm,"height":cm,"blend_margin":cm}
      replace=True resets the feature list first (idempotent rebuild); default appends.
    action="flatten" (region, height, blend_margin): carve a pad/bed — blend the terrain to a
        level inside region={kind:"circle"|"rect"|"polygon", ...}, feathered over blend_margin.
        height is WORLD z; defaults to the current grade at the region anchor (pad at grade).
    action="describe" (at): bounds, height range, and z + slope sampled at map points
        at=[[x,y],...] — agrees with world traces (same height function built the mesh, and
        the model side composes the actor's live transform + base_height).
    action="remove": tear the terrain down (actor + meta) so create can rebuild from scratch.

    material: a material name or /Game path to assign to the terrain surface (find one via
        asset find kind=material); persists across reshapes. Accepted on create/shape.
    uv_tile_cm: ground-texture repeat in cm (default 400) — one UV tile every uv_tile_cm,
        so a tiling material renders at its authored scale instead of smearing (G33).
        Accepted on create/shape; persists across reshapes.
    """
    p = {"action": action, "label": label, "replace": replace}
    for k, v in (("size", size), ("origin", origin), ("base_height", base_height),
                 ("features", features), ("region", region), ("height", height),
                 ("blend_margin", blend_margin), ("at", at), ("resolution", resolution),
                 ("material", material), ("uv_tile_cm", uv_tile_cm)):
        if v is not None:
            p[k] = v
    return render(call_ue("landscape", p, timeout=180))


@mcp.tool()
def history(op: str = "list", id: str = None) -> str:
    """Inspect or rewind the mutation log.

    op="list":            the ordered op log (id, verb, summary).
    op="undo_to" (id):    undo every op after `id`, via the editor's transaction stack.
                          Note: the undo stack is shared with your manual editor edits —
                          a manual edit interleaved with ueb ops can desync this (gaps.md G1).
    """
    return render(call_ue("history", {"op": op, "id": id}))


@mcp.tool()
def validate(op: str = "run", targets: str = None, a: str = None, b: str = None,
             reason: str = None, check: str = "penetration", max_depth: float = None,
             verbose: bool = False) -> str:
    """The always-on correctness floor — the second forced sense (SPEC-02).

    A spatial-lint floor runs AUTOMATICALLY on the touched delta after every add/transform
    and reports by exception on the status block; this verb is its on-demand + declaration
    surface. Three checks: ground (float/bury vs a trace), penetration (AABB depth), and
    z_fight (coplanar overlapping faces). Every finding carries its fix.

    op="run" (targets, verbose):  sweep the whole scene, or a comma-separated `targets`
        list. verbose lists every finding uncapped. Run before screenshots / at milestones.
    op="expect" (a, b, reason, check, max_depth):  declare a contact INTENDED — the only
        way to quiet a laden finding (there is no "ignore"). reason is required — a
        falsifiable design claim. check=penetration (a↔b) | ground (a↔"ground"). max_depth
        (cm) bounds a blessed penetration so a deeper one still surfaces. a/b may name an
        actor TAG to bless a whole scatter class at once. z_fight is intent-free (rejected).
    op="forget" (a, b, check):  retire a declaration (re-arms the finding).
    op="intended":  list the live declared-intent registry.
    """
    p = {"op": op, "check": check, "verbose": verbose}
    for k, v in (("targets", targets), ("a", a), ("b", b), ("reason", reason),
                 ("max_depth", max_depth)):
        if v is not None:
            p[k] = v
    return render(call_ue("validate", p))


@mcp.resource("guidance://llms")
def guidance_for_llms() -> str:
    """GUIDANCE_FOR_LLMS.md — battle-tested loops and failure modes, served verbatim.
    The server instructions direct the agent here before any multi-step build."""
    return (Path(_PARENT) / "GUIDANCE_FOR_LLMS.md").read_text(encoding="utf-8")


def main():
    mcp.run()


if __name__ == "__main__":
    main()
