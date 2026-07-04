"""ue-buttons MCP server — the SPEC-05 verb surface.

Each @mcp.tool is a thin projection: it forwards a params dict to the editor runtime via
call_ue and renders the result. All scene logic lives in the runtime; this file is the
agent-facing surface. Verbs are named by the UE surface they drive (SPEC-05's 2×2 law);
`op` is the one discriminator everywhere. Conventions: centimetres, +X forward/north,
+Y right/east, +Z up, rotation as [yaw, pitch, roll] degrees, bearing = UE yaw.

Run:  uv run ue-buttons        (or: uv run python server/main.py)
"""
import sys
from pathlib import Path
from typing import Literal

_PARENT = str(Path(__file__).resolve().parent.parent)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

from server._core import mcp, call_ue, render


@mcp.tool()
def add(label: str, what: str = None, asset: str = None, dims: list = None,
        place: dict = None, yaw: float = None, facing: str = None,
        force: bool = False) -> str:
    """Spawn a primitive OR a project asset with relational placement — the Place Actors
    panel / "+ Add" button. (EditorActorSubsystem.spawn_actor_from_*)

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
    facing: a spline label — turn the actor to face the route it was placed along
            (perpendicular, toward the route; from ON the route itself — placed along= it,
            within its width — it means the tangent: looking down the path, G42)
    force: override a SPEC-07 gate refusal (e.g. R2: the mesh's materials carry
           per-instance nodes that render as constants on a standalone actor) — spawns
           anyway with a warning note, and the census keeps flagging it
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
      {"grid": {"anchor": "<label>", "module": <cm>, "cell": [i, j]}}
                                                 modular composition (G10): centre exactly
                                                 i×module along x / j×module along y from
                                                 the anchor's centre, z level with it —
                                                 spans a fixed module (a 4 m-grid room)
                                                 instead of abutting face-to-face
      {"along": {"spline": "<label>", "fraction": f, "side": "left|right", "offset": <cm>}}
                                                 beside a spline at a fraction of its length
      {"at": [x, y, z]}                          raw coords (documented ripcord only)
    """
    p = {"label": label, "place": place or {}}
    if what is not None: p["what"] = what
    if asset is not None: p["asset"] = asset
    if dims is not None: p["dims"] = dims
    if yaw is not None: p["yaw"] = yaw
    if facing is not None: p["facing"] = facing
    if force: p["force"] = True
    return render(call_ue("add", p))


@mcp.tool()
def transform(op: Literal["move", "resize", "rotate"], target: str, by: list = None,
              dims: list = None, to: list = None) -> str:
    """The Move / Rotate / Scale gizmos + Details▸Transform, by actor label.

    op=move:   by=[dx, dy, dz] cm along world axes — set_actor_location
    op=resize: dims=[x, y, z] new world size in cm — set_actor_scale3d off native size
    op=rotate: to=[yaw, pitch, roll] degrees — set_actor_rotation
    """
    p = {"op": op, "target": target}
    if by is not None: p["by"] = by
    if dims is not None: p["dims"] = dims
    if to is not None: p["to"] = to
    return render(call_ue("transform", p))


@mcp.tool()
def select(op: Literal["set", "clear", "user"] = "set", labels: list = None) -> str:
    """Editor selection by label. op=set (labels=[...]) | clear — feeds the
    active/selected fields of the status block. (EditorActorSubsystem selection)

    op=user (SPEC-06 deixis): read the USER's live selection — when they say "this one",
    ask them to click it and run this. Each selected thing comes back as a full entry
    (label/class/dims/meshes/motion verdict + next moves); a foliage click lands on the
    whole InstancedFoliageActor and is resolved down to its populated components
    (mesh, instance count, owning stand, motion) — enough to diagnose "these trees bob".
    """
    return render(call_ue("select", {"op": op, "labels": labels or []}))


@mcp.tool()
def outliner(op: Literal["census", "reconcile"] = "census",
             include_all: bool = False) -> str:
    """The Outliner panel — what is in the level.

    op=census (default): actors grouped by type, with the level name. Scoped to
      ueb-tagged actors; include_all=True for the whole level (an Open World map has ~135
      engine scaffolding actors — always counted, listed on request).
    op=reconcile: MACRO ≈ nothing in UE — diff the ueb terrain/spline/foliage registries
      against the editor's own tally (clean / dirty with self|external attribution /
      orphaned / untracked) and GC orphans, so a level change can't leave a phantom (G16).
    """
    p = {"op": op}
    if include_all: p["include_all"] = True
    return render(call_ue("outliner", p))


@mcp.tool()
def level(op: Literal["streaming", "save", "new", "open", "clear"] = "streaming",
          path: str = None, template: str = None, save: bool = False,
          save_path: str = None, force: bool = False) -> str:
    """Level / World Settings / World Partition — lifecycle included (SPEC-04).

    op=streaming: the WorldPartition residency picture — is the world partitioned, its
      data layers + effective runtime state, per-actor is_spatially_loaded/runtime_grid.
      Says so plainly when the map isn't partitioned. (WorldPartitionBlueprintLibrary)
    op=save: save the level + external actors + authored content. An unsaved Untitled
      needs path='/Game/Maps/<Name>' (save-as).
    op=new (path=): fresh level saved at path, cloned from the World-Partition Open World
      template (template= to override), with the G36 cure baked in: the template's copied
      env actors (broken at PIE time) are replaced by a fresh sun / sky_light /
      sky_atmosphere / clouds / height_fog / player_start set.
    op=open (path=): load a level by asset path.
    op=clear: wipe the ueb arrangement, keep the map — every ueb-tagged actor and foliage
      population dies (counts reported by kind), engine scaffolding survives, the
      template ground returns (G37), op log + intents reset.

    Guards: new/open REFUSE if the current level has unsaved changes — save=true saves
    first (save_path= if it's Untitled), force=true discards explicitly. new/open/clear
    all run outliner-reconcile as part of the transition, so the registries can never
    describe a level that is no longer loaded.
    """
    p = {"op": op}
    if path is not None: p["path"] = path
    if template is not None: p["template"] = template
    if save: p["save"] = True
    if save_path is not None: p["save_path"] = save_path
    if force: p["force"] = True
    return render(call_ue("level", p, timeout=120))


@mcp.tool()
def play(op: Literal["census", "start", "stop", "where"] = "census") -> str:
    """Play In Editor. Editor verbs refuse during Play (B8) — this verb owns PIE.

    op=census (G36): GAME truth — editor and PIE views of a map can disagree completely
      (always-loaded template actors that never load at runtime = black screen on Play
      while every editor read says fine). Two-step: first call snapshots the always-loaded
      set and starts Play; call AGAIN ~2 s later to census the game world, END Play, and
      get the missing-at-runtime diff. Run it before handing a level to a human.
    op=start | stop: plain PIE control. (LevelEditorSubsystem.editor_request_begin/end_play)
    op=where (SPEC-06 deixis): mid-Play — where the PIE pawn stands and what the player
      camera looks at ("I'm here and I see X"), read from the game world without ending
      Play. The user's "right here, where I'm standing" made resolvable.
    """
    return render(call_ue("play", {"op": op}))


@mcp.tool()
def feel(op: Literal["describe", "distance_between", "gap_between", "is_aligned",
                     "render_state", "framing", "visible", "looking_at"],
         target: str = None, a: str = None, b: str = None,
         axis: str = "ANY", side: str = "CENTER_Z", fov: float = 90.0) -> str:
    """SENSE (agent-only) — relational perception: measure, don't guess. Numbers, never a
    picture: this is the whole perception surface (there is NO screenshot/render verb —
    see the vision policy in the instructions).

    op=describe (target):        dims, bounds, on_floor, and relations (rests_on /
                                 directly_under / flush_left_of / flush_right_of /
                                 flush_in_front_of / flush_behind) to other ueb actors.
    op=distance_between (a,b,axis): centre-to-centre distance; axis=X|Y|Z|ANY.
    op=gap_between (a,b):        per-axis empty space (negative = overlap) + touching axes.
    op=is_aligned (a,b,side):    side ∈ TOP|BOTTOM|FRONT|BACK|LEFT|RIGHT|CENTER_X|
                                 CENTER_Y|CENTER_Z (front/back = ±X, left/right = ±Y).
    op=render_state (target):    walk the render gating chain for one actor or foliage
                                 stand: per-link verdict + the fix, and a DRAWS /
                                 WILL-NOT-DRAW verdict — the deep-dive behind the status
                                 block's one-line `render:` summary (SPEC-03).
    op=framing (target, fov):    project the target's world AABB through the editor
                                 viewport camera → frac_w/frac_h, est_px (the sub-pixel
                                 tell), clipped edges, in_front, and a FRAMED / SUB-PIXEL /
                                 CLIPPED / OFF-FRAME verdict — as NUMBERS, never a frame.
    op=visible (target, fov):    SEEN or hidden behind other geometry: raycasts from the
                                 camera (occluded_fraction + verdict), not a screenshot.
                                 With framing this tells sub-pixel vs off-frustum vs
                                 occluded vs absent apart.
    op=looking_at:               SPEC-06 deixis — trace the USER's viewport forward ray:
                                 "you're looking at X, N m away", with a foliage hit
                                 resolved to (stand, instance_index). The answer to
                                 "that thing over there" after the user aims at it.
    """
    p = {"op": op, "target": target, "a": a, "b": b, "axis": axis, "side": side, "fov": fov}
    return render(call_ue("feel", p))


@mcp.tool()
def asset(op: Literal["packs", "inventory", "describe", "find", "whats_new"] = "packs",
          pack: str = None, name: str = None, query: str = None, kind: str = "mesh",
          family: str = None, measure: bool = False, budget: int = 60,
          seconds: float = 20.0, commit: bool = True) -> str:
    """The Content Browser / Asset Registry — "what can I build with, and how big is it?"

    All dimensions are centimetres, at native scale (a 400 cm wall is 400 cm because its
    doorframe is human-sized). Pivot is reported per asset — base (trees, walls) vs center
    — because grounding math depends on it.

    op=packs:                  top-level /Game roots, per-class counts, one-line character.
                               Cheap (registry only).
    op=inventory (pack):       COMPACT by default — one dict per inferred FAMILY
                               (Pine_Tree_01..05 → family Pine_Tree) with variant names,
                               tris, Nanite, and where measured: height, footprint and
                               aspect_h_over_w — the SILHOUETTE tells (aspect ≈1 reads as
                               a bush/blob; a trunk-and-canopy tree runs ~1.5–3; past ~3
                               you're usually looking at a bare spire/snag — flagged
                               sparse_spire, G38). Don't pick forest species on height
                               alone. Dims are measured lazily (loading a mesh is the one
                               expensive step):
                                 measure=True [budget=N, seconds=S]: warm the dims cache
                                   in bounded batches (≤N meshes AND ≤S s, defaults
                                   60/20 s) — repeat until complete; never blocks the bridge.
                                 family="Pine_Tree": full per-variant detail for one
                                   family, measuring just those. Measured dims persist.
    op=describe (name):        one asset in full — dims, pivot, material slots, collision,
                               dependency/referencer counts. On a MATERIAL: the vet (G32) —
                               master + parent chain, exposed parameters, and a MOTION
                               verdict (G39): masked_wind (base anchored, safe) vs wpo /
                               wpo_suspect (the mesh MOVES). Run it BEFORE dressing
                               anything in an unknown material.
    op=find (query, kind):     name-substring search; kind=mesh|blueprint|skeletal|
                               material|any (material finds surfaces for terrain
                               material= / spline op=surface).
    op=whats_new (commit):     diff the registry against a persisted snapshot — how a
                               freshly-downloaded pack becomes visible. commit=False peeks
                               without updating the snapshot.
    """
    p = {"op": op, "pack": pack, "asset": name, "query": query, "kind": kind,
         "family": family, "measure": measure, "budget": budget,
         "commit": commit, "seconds": seconds}
    # measure / family-drill load meshes — give them room; default inventory is cheap.
    timeout = 180 if (measure or family) else 60
    return render(call_ue("asset", p, timeout=timeout))


@mcp.tool()
def material(op: Literal["instance"] = "instance", parent: str = None, name: str = None,
             textures: dict = None, scalars: dict = None, folder: str = None) -> str:
    """The Material Instance editor — author materials without raw editor Python.

    op=instance (parent, name, textures, scalars, folder): a MaterialInstanceConstant of
      a master — textures={param: texture name}, scalars={param: value}. Param names are
      validated against the master BEFORE creation; every set is verified by read-back
      (5.8's setters return False even on success). folder default /Game/UEB_Materials.
      (MaterialEditingLibrary + AssetTools.create_asset)
    """
    p = {"op": op}
    for k, v in (("parent", parent), ("name", name), ("textures", textures),
                 ("scalars", scalars), ("folder", folder)):
        if v is not None:
            p[k] = v
    return render(call_ue("material", p))


@mcp.tool()
def foliage(op: Literal["paint", "describe", "reseed", "remove"] = "paint",
            label: str = "foliage", meshes: list = None, region: dict = None,
            density_per_100m2: float = None, seed: int = 1337, rules: dict = None,
            terrain: str = "terrain", pack: str = None, force: bool = False) -> str:
    """The Foliage editor mode — populations, not actors: declare rules, get a
    reproducible, spline-respecting stand. One labelled stand holds the whole population
    (instanced foliage components in the level's InstancedFoliageActor), never thousands
    of rows. Ground z + slope come from world traces. Spatial verb (not history-undoable);
    teardown is op=remove. (Cousin: PCG — its 5.8 Python surface is too thin; R2.)

    op=paint — InstancedFoliageActor.add_instances + minted FoliageType assets:
      meshes:  inventory FAMILY names, optional weight — ["Pine_Tree", "Black_Alder:0.3"]
               (variants randomised per instance). A family that resolves across MULTIPLE
               packs errors with pack-attributed candidates (G31) — scope with pack= or
               pass explicit variant names.
      region:  {"kind":"circle","at":[x,y],"radius":cm} | {"kind":"rect","at":[x,y],
               "size":[w,h]} | {"kind":"polygon","points":[[x,y],...]} | {"kind":"terrain"}
               (the whole terrain). MAP coords.
      density_per_100m2:  instances per 100 m² (or set rules.min_spacing_cm).
      seed:    determinism — same seed + rules ⇒ same stand.
      rules:   {min_spacing_cm, max_slope_deg, align_to_slope (rocks yes / trees no),
               scale_jitter:[lo,hi], yaw_random, clear_margin, clear_of:[spline/actor
               labels, regions], collision: "auto"|"block"|"none" (G46 — auto gives
               tree-scale variants BlockAll bodies so the PIE pawn stops at trunks;
               understory stays collision-free. Visibility traces still pass through
               foliage by engine design — "which tree" is feel op=looking_at's math
               pass, not a trace)}.
               DEFAULT: every paint auto-clears existing splines
               (width/2+margin) and buildings (footprint+margin) — the trail stays open
               THROUGH the trees. Spacing below the measured canopy width warns (G28);
               derive min_spacing_cm from the widest family's footprint, never intuition.
               Meshes whose materials MOVE them are announced at author time (G39/G40).
      force:   painting IS instancing — a palette whose WPO is pivot-anchored (R1/G40)
               is REFUSED before planting, with alternatives (standalone placement, or
               motion-safe meshes from inventory). force=true plants anyway; the
               level-wide census keeps flagging the stand, and reseed inherits the force.
    op=describe: counts per family, region, seed, rules — enough to reason/rebuild.
    op=reseed (seed): same rules, new dice — the "reroll that stand" button (ours; UE has
      no reroll concept).
    op=remove: delete the whole stand as a unit (by component tag).
    """
    p = {"op": op, "label": label, "seed": seed, "terrain": terrain}
    for k, v in (("meshes", meshes), ("region", region), ("pack", pack),
                 ("density_per_100m2", density_per_100m2), ("rules", rules)):
        if v is not None:
            p[k] = v
    if force: p["force"] = True
    return render(call_ue("foliage", p, timeout=240))


@mcp.tool()
def spline(op: Literal["create", "surface", "describe", "remove"] = "create",
           label: str = "spline", points: list = None, route: dict = None,
           width: float = None, at_fraction: float = None, terrain: str = "terrain",
           material: str = None, lift: float = None, tile: float = None) -> str:
    """SplineComponent as intent — a winding route draped over the terrain. (5.8 blocks
    adding a SplineComponent from Python, G13, so the curve is a Catmull-Rom spline over
    waypoints; the CONCEPT is UE's.) Carving the terrain along a spline is `terrain
    op=carve along=<label>` — the op lives on the thing it mutates.

    All positions are MAP points: polar {"from":<anchor>,"bearing":deg,"distance":cm}
    (anchor = "center" | actor label | terrain | ["spline_label", fraction]) or absolute
    [x,y] with a READ provenance. Compass: north=+X, bearing clockwise = UE yaw. z is
    draped onto the terrain by tracing. Spatial verb (not history-undoable).

    op=create (points | route, width):
        points=[map position, ...] — waypoints; a smooth curve runs through them.
        route={"start":<pos>, "start_bearing":deg, "steps":[...]} — a WALK; each step is
          {"bearing":deg,"distance":cm} (absolute) or {"turn":±deg,"distance":cm}
          (relative — the natural encoding of "winding"). Returns every resolved waypoint.
    op=surface (material, width, lift, tile): MACRO ≈ Landscape splines' road mesh — make
        the route VISIBLE: a thin material ribbon draped onto the ground (a carve alone is
        nearly invisible without material contrast, G25). material = name or /Game path
        (asset op=find kind=material); lift = cm above ground (default 5); tile = cm per
        texture repeat (default 400). Idempotent: re-running replaces the strip.
        Typical order: create → terrain op=carve → surface.
    op=describe (at_fraction): length, waypoints, a GRADE profile (per-segment slope %
        from live ground traces, avg/max + where — walkability as a number, >20% warns),
        and (at_fraction) the world point + tangent + bearing there — the skeleton for
        `along=`/`facing=` placement.
    op=remove: forget the spline (and delete its surface strip).

    Placement (on add/foliage): place={"along":{"spline":label,"fraction":f,"side":
    "left|right","offset":cm}} puts a thing beside the route; add(facing=label) turns it
    to face the route — perpendicular from beside it, down the TANGENT when the actor
    stands ON the route itself (placed along= it, within its width).
    """
    p = {"op": op, "label": label, "terrain": terrain}
    for k, v in (("points", points), ("route", route), ("width", width),
                 ("at_fraction", at_fraction), ("material", material),
                 ("lift", lift), ("tile", tile)):
        if v is not None:
            p[k] = v
    return render(call_ue("spline", p, timeout=180))


@mcp.tool()
def terrain(op: Literal["create", "shape", "flatten", "carve", "describe",
                        "remove"] = "create",
            label: str = "terrain", size: list = None, origin: list = None,
            base_height: float = None, features: list = None, region: dict = None,
            height: float = None, blend_margin: float = None, at: list = None,
            along: str = None, replace: bool = False, resolution: list = None,
            material: str = None, uv_tile_cm: float = None) -> str:
    """MACRO ≈ UE Landscape (Python cannot author Landscape in 5.8) — StaticMesh terrain
    synthesised from a declarative heightfield; no layers, no grass types. You describe
    landforms, the runtime builds the mesh (Geometry Script DynamicMesh, collidable — so
    ground-snap / foliage / spline-drape trace it directly). All coords are MAP cm.
    NOT undoable via history (see the `undoable` field). While a ueb terrain exists, the
    engine template's z=0 Landscape is neither traced NOR rendered (G37); removing the
    last ueb terrain restores it.

    op=create (size, origin, base_height, material): new flat terrain. size=[x_cm,y_cm]
        (a hamlet ~[20000,20000] = 200 m); origin = map centre (default [0,0]).
    op=shape (features, replace, material): landform features, composed in order —
        {"kind":"valley","axis":"x|y","floor_width":cm,"wall_height":cm,"roughness":0..1}
        {"kind":"hill"|"ridge","at":[x,y],"radius":cm,"height":cm,"length":cm,"axis":"x|y"}
        {"kind":"noise","amplitude":cm,"scale":cm,"octaves":n,"seed":n}
        {"kind":"plateau","at":[x,y],"radius":cm,"height":cm,"blend_margin":cm}
      replace=True resets the feature list first (idempotent rebuild); default appends.
    op=flatten (region, height, blend_margin): carve a pad/bed — blend the terrain to a
        level inside region={kind:"circle"|"rect"|"polygon", ...}, feathered over
        blend_margin. height is WORLD z; defaults to the current grade (pad at grade).
    op=carve (along, blend_margin): flatten to grade along a spline's route, feathered to
        its width — cuts the geometric bed in ONE mesh rebuild, and re-drapes the
        spline's surface strip automatically. along=<spline label>.
    op=describe (at): bounds, height range, and z + slope sampled at map points
        at=[[x,y],...] — agrees with world traces (same height function built the mesh).
    op=remove: tear the terrain down (actor + meta) so create can rebuild from scratch.

    material: a material name or /Game path for the surface (asset op=find kind=material);
        persists across reshapes. Accepted on create/shape.
    uv_tile_cm: ground-texture repeat in cm (default 400) — so a tiling material renders
        at its authored scale instead of smearing (G33). Accepted on create/shape.
    """
    p = {"op": op, "label": label, "replace": replace}
    for k, v in (("size", size), ("origin", origin), ("base_height", base_height),
                 ("features", features), ("region", region), ("height", height),
                 ("blend_margin", blend_margin), ("at", at), ("along", along),
                 ("resolution", resolution), ("material", material),
                 ("uv_tile_cm", uv_tile_cm)):
        if v is not None:
            p[k] = v
    return render(call_ue("terrain", p, timeout=180))


@mcp.tool()
def history(op: Literal["list", "undo", "undo_to"] = "list", id: str = None,
            n: int = 1) -> str:
    """Edit▸Undo History — inspect or rewind the mutation log.

    op=list:          the ordered op log (id, verb, summary).
    op=undo (n=1):    "undo that" — N raw editor undos on the SHARED transaction stack,
                      newest first, agent op OR human edit (the blunt, human-facing button).
    op=undo_to (id):  undo every op after `id`, via the editor's transaction stack. The
                      stack is shared with manual editor edits — an interleaved manual
                      edit can desync this (gaps.md G1).
    """
    return render(call_ue("history", {"op": op, "id": id, "n": n}))


@mcp.tool()
def validate(op: Literal["run", "expect", "forget", "intended"] = "run",
             targets: str = None, a: str = None, b: str = None, reason: str = None,
             check: str = "penetration", max_depth: float = None,
             verbose: bool = False) -> str:
    """SENSE (agent-only) — the always-on correctness floor (SPEC-02). A spatial-lint
    floor runs AUTOMATICALLY on the touched delta after every add/transform and reports by
    exception on the status block; this verb is its on-demand + declaration surface.
    Three checks: ground (float/bury vs a trace), penetration (AABB depth), and z_fight
    (coplanar overlapping faces). Every finding carries its fix.

    op=run (targets, verbose):  sweep the whole scene, or a comma-separated `targets`
        list. verbose lists every finding uncapped. Run at milestones / before handoff.
    op=expect (a, b, reason, check, max_depth):  declare a contact INTENDED — the only
        way to quiet a laden finding (there is no "ignore"). reason is required — a
        falsifiable design claim. check=penetration (a↔b) | ground (a↔"ground"). max_depth
        (cm) bounds a blessed penetration so a deeper one still surfaces. a/b may name an
        actor TAG to bless a whole class at once. z_fight is intent-free (rejected).
    op=forget (a, b, check):  retire a declaration (re-arms the finding).
    op=intended:  list the live declared-intent registry.
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
