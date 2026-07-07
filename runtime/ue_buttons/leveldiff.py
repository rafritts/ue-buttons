"""SPEC-16 — the whole-outliner blast-radius diff. Maximally truthful, verb-blind.

Snapshot the ENTIRE outliner (every actor + every component, engine scaffolding included),
run an op, snapshot again, diff. Report everything that changed anywhere — added / removed /
changed — with a field-level sub-diff, knowing NOTHING about landscapes, PCG, foliage or
terrain. The same code that catches a sculpt catches a deleted sun, because it special-cases
none of them. This is observe-and-report, never undo (that is `history`'s job).

Capture mechanism (SPIKE resolved live 2026-07-06, UE 5.8):
  * Identity = actor GUID (`actor_guid`.to_string()) — stable across reads, so `removed`
    means gone, not renamed. Fallback = get_path_name().
  * State = a reflection property-walk. UE's Python wrapper exposes UPROPERTYs as
    `getset_descriptor`s on the class (methods are `methodwithclosure_descriptor`); we read
    each via get_editor_property and canonicalise. T3D/actor-export APIs do NOT exist in
    5.8 (spiked: export_* absent), so the property-walk IS the mechanism, not a fallback.
  * Cost: full walk incl. component recursion = ~0.5 s / 138 actors, ~65k fields. Two per
    op. Proven cheap; a `spatial` fast-path (transform+bounds only) is the honest lever for
    a pathologically actor-heavy level — the payload always names which mode ran.

The honesty spine — no-op ⇒ empty diff is a HARD invariant, defended NOT by curating
"important" fields (the smart-and-fragile trap that eventually hides a real change) but by
the empirically-derived `_TRANSIENT_DENYLIST`: a field is filtered IFF it flickers under a
literal no-op. Spiked 2026-07-06: an actor+component double-snapshot over 138 actors
flickered ZERO fields, so the denylist ships EMPTY. A wild flicker found later is promoted
in under the same discipline (reproduce under a no-op, record the justification) — never
waved off ad hoc.
"""
import unreal

from . import _state

# ── modes ─────────────────────────────────────────────────────────────────────
SPATIAL = "spatial"   # transform + bounds-Z only (PROVEN, cheapest)
FULL = "full"         # complete property walk incl. components (default; catches material
                      # swaps, light dims — anything the spatial fingerprint misses)
DEFAULT_MODE = FULL

# ── transient denylist (SPIKE-derived; EMPTY by construction) ──────────────────
# Keys are "field" (actor prop) or "comp/field" (component prop). Empty today: the
# double-snapshot no-op gate flickered nothing. Each future entry MUST carry a one-line
# "flickered under a literal no-op" justification — nothing is denylisted for being
# 'unimportant' (a stable-under-no-op field is ALWAYS reported).
_TRANSIENT_DENYLIST = frozenset()

# Guids that are identity/bookkeeping, not authored state — stable per actor so they never
# create a false diff, but capturing them as state is pure weight. Skipped from the walk.
_SKIP_FIELDS = frozenset({"actor_guid", "actor_instance_guid"})

# Per-actor field cap on the reported sub-diff (a mass edit could change thousands); the
# payload discloses the truncation rather than hiding it (never a silent cap).
_MAX_FIELDS_REPORTED = 25

_EMPTY_GUID = "00000000000000000000000000000000"


# ── identity ───────────────────────────────────────────────────────────────────
def _key(actor):
    """Stable identity: actor GUID string, or the path name if the guid is empty/unreadable."""
    try:
        g = actor.get_editor_property("actor_guid")
        s = g.to_string()
        if s and s != _EMPTY_GUID:
            return s
    except Exception:
        pass
    return actor.get_path_name()


# ── canonicalisation ────────────────────────────────────────────────────────────
def _canon(v, depth=0):
    """A value rendered so equal states compare equal and unequal ones differ. Assets are
    captured by PATH (a material swap changes it); sub-objects/components by name (their
    own state is captured by the component walk); structs/arrays recurse (bounded)."""
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        return round(v, 3)
    if isinstance(v, unreal.Name):
        return str(v)
    if isinstance(v, unreal.Vector):
        return [round(v.x, 2), round(v.y, 2), round(v.z, 2)]
    if isinstance(v, unreal.Rotator):
        return [round(v.roll, 2), round(v.pitch, 2), round(v.yaw, 2)]
    if isinstance(v, unreal.LinearColor):
        return [round(v.r, 3), round(v.g, 3), round(v.b, 3), round(v.a, 3)]
    if isinstance(v, unreal.Color):
        return [v.r, v.g, v.b, v.a]
    if isinstance(v, unreal.Object):
        p = v.get_path_name()
        # An asset reference (/Game/…, /Engine/… with no sub-object ':' tail) is captured by
        # path — the durable identity a swap changes. An owned sub-object/component is
        # captured by name; its own fields ride the component walk.
        if p.startswith(("/Game", "/Engine", "/Script")) and ":" not in p.rsplit(".", 1)[-1]:
            return "asset:" + p
        return "obj:" + v.get_name()
    if isinstance(v, (unreal.Array, unreal.Set)):
        if depth >= 2:
            return "<%s:%d>" % (type(v).__name__, len(v))
        return [_canon(x, depth + 1) for x in list(v)[:64]]
    if isinstance(v, unreal.Map):
        try:
            return sorted((str(k), _canon(val, depth + 1)) for k, val in v.items())
        except Exception:
            return "<map:%d>" % len(v)
    if isinstance(v, unreal.StructBase):
        try:
            return _canon(list(v.to_tuple()), depth + 1)
        except Exception:
            try:
                return v.to_string()
            except Exception:
                return "<struct:%s>" % type(v).__name__
    return "<%s>" % type(v).__name__


def _prop_names(obj):
    """Editor-exposed UPROPERTY names on obj's class — the getset_descriptors (methods are
    methodwithclosure_descriptors, so callables are excluded)."""
    pc = type(obj)
    out = []
    for n in dir(pc):
        if n.startswith("_") or n in _SKIP_FIELDS:
            continue
        try:
            if type(getattr(pc, n)).__name__ == "getset_descriptor":
                out.append(n)
        except Exception:
            pass
    return out


def _walk(obj, prefix, into, denylist):
    """Read every readable property of obj into `into`, keyed prefix+name. Unreadable
    properties (dynamic-multicast delegates the bridge can't marshal) are skipped — they
    aren't state — which keeps them consistent across snapshots (no phantom diff)."""
    for n in _prop_names(obj):
        key = prefix + n
        if key in denylist:
            continue
        try:
            into[key] = _canon(obj.get_editor_property(n))
        except Exception:
            continue


def _actor_state(actor, mode):
    """The fingerprint state dict for one actor: {field -> canon value}, canonically ordered
    at compare time (plain dict compare is order-insensitive)."""
    state = {}
    # World AABB in BOTH modes. It is the PROVEN narrow fingerprint (spatial) AND the only
    # thing that catches a pure geometry edit in full mode: a heightmap sculpt rewrites a
    # DynamicMesh's vertices — which are NOT a diffable UPROPERTY — but its world bounds-Z
    # shifts. Without this, full mode (property-walk only) would MISS the very crater the
    # spatial fingerprint catches. Bounds is flicker-free under a no-op (spiked).
    loc = actor.get_actor_location()
    state["location"] = [round(loc.x, 2), round(loc.y, 2), round(loc.z, 2)]
    try:
        o, e = actor.get_actor_bounds(False)
        state["bounds"] = [round(o.x, 1), round(o.y, 1), round(o.z, 1),
                           round(e.x, 1), round(e.y, 1), round(e.z, 1)]
    except Exception:
        pass
    if mode == SPATIAL:
        return state
    # FULL: + every actor prop + every component's props.
    _walk(actor, "", state, _TRANSIENT_DENYLIST)
    try:
        comps = actor.get_components_by_class(unreal.ActorComponent)
    except Exception:
        comps = []
    for c in comps:
        try:
            _walk(c, "comp:" + c.get_name() + "/", state, _TRANSIENT_DENYLIST)
        except Exception:
            continue
    return state


# ── snapshot / diff ─────────────────────────────────────────────────────────────
def snapshot(mode=DEFAULT_MODE):
    """{key -> {label, cls, state}} over ALL loaded actors (engine scaffolding included —
    the sun IS scaffolding). Never raises for one bad actor: it is skipped and the rest
    stand."""
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    out = {}
    for a in eas.get_all_level_actors():
        try:
            out[_key(a)] = {"label": a.get_actor_label(),
                            "cls": a.get_class().get_name(),
                            "state": _actor_state(a, mode)}
        except Exception:
            continue
    return out


def _field_diff(before, after, verbose=False):
    """[{path, before, after}] for the fields that differ between two state dicts. Capped at
    _MAX_FIELDS_REPORTED with an honest overflow marker unless verbose (outliner op=diff
    verbose=true — the uncapped dump)."""
    fields = []
    for path in sorted(set(before) | set(after)):
        b, a = before.get(path), after.get(path)
        if b != a:
            fields.append({"path": path, "before": b, "after": a})
    if not verbose and len(fields) > _MAX_FIELDS_REPORTED:
        extra = len(fields) - _MAX_FIELDS_REPORTED
        fields = fields[:_MAX_FIELDS_REPORTED]
        fields.append({"path": "…", "before": None,
                       "after": "+%d more field(s) changed (capped — outliner op=diff "
                                "verbose=true for the full dump)" % extra})
    return fields


# ── B16 self-heal attribution (author ruling 1) ──────────────────────────────────
# The first `terrain create` in a level sinks + hides ~128 template Landscape proxies 2 km
# (the B15/B16 collision cure). That is the tool's OWN documented side-effect, not the
# user's op — so it is ATTRIBUTED (a labeled housekeeping line, kept out of the flag), NOT
# silenced (the proxies stay in `changed`) and NOT filtered (filtering would hide a real
# Landscape sculpt — sink and sculpt are indistinguishable by class alone). A changed actor
# joins the pure-sink subset only under a STRICT 4-part signature; ONE deviating field and
# the exemption is off and the flag trips normally. A real sculpt never matches (varied ΔZ,
# no hide, not the exact constant).
_B16_SINK_CM = 200000.0   # must match terrain._TEMPLATE_SINK_CM (B15) — the exact ±2 km offset
_B16_CLASSES = frozenset({"Landscape", "LandscapeStreamingProxy", "LandscapeProxy",
                          "WorldPartitionHLOD"})


def _z_shift(before, after):
    """If two captured values differ ONLY by a uniform shift of their Z component, return
    that shift (cm); else None. Handles location/relative_* ([x,y,z]) and bounds
    ([ox,oy,oz,ex,ey,ez] — origin-Z shifts, extents fixed)."""
    if not (isinstance(before, list) and isinstance(after, list)) or len(before) != len(after):
        return None
    if len(before) == 3:
        keep = (0, 1)
    elif len(before) == 6:
        keep = (0, 1, 3, 4, 5)
    else:
        return None
    if any(before[i] != after[i] for i in keep):
        return None
    try:
        return float(after[2]) - float(before[2])
    except (TypeError, ValueError):
        return None


def _is_b16_sink(entry):
    """True iff `entry` is a pure template-proxy 2 km sink/raise + hide-flag flip and NOTHING
    else — the strict signature under which the B16 self-heal is attributed, not flagged."""
    if entry["cls"] not in _B16_CLASSES:
        return False
    saw_z = hidden_ok = False
    shift = None
    for f in entry["fields"]:
        p, b, a = f["path"], f["before"], f["after"]
        if p == "hidden":
            if (b, a) not in ((False, True), (True, False)):
                return False
            hidden_ok = True
            continue
        z = _z_shift(b, a)
        if z is None or abs(abs(z) - _B16_SINK_CM) > 1.0:
            return False                       # a non-sink field deviates → exemption off
        if shift is None:
            shift = z
        elif abs(z - shift) > 1.0:
            return False                       # inconsistent direction/magnitude
        saw_z = True
    return saw_z and hidden_ok and shift is not None


def _partitioned():
    """Is the current editor world World-Partitioned? Then get_all_level_actors enumerates
    only LOADED actors, so `removed` is ambiguous — truly deleted vs merely streamed out."""
    try:
        w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        return unreal.WorldPartitionBlueprintLibrary.get_data_layer_manager(w) is not None
    except Exception:
        return False


def diff(before, after, verbose=False):
    """The LevelDelta: added / removed / changed (field-level) + summary + OPPENHEIMER flag.
    B16 template-proxy self-heal changes are attributed (marked `housekeeping`) but stay in
    `changed` — the listing is always complete; only the flag ignores them."""
    added = [{"key": k, "label": after[k]["label"], "cls": after[k]["cls"]}
             for k in after if k not in before]
    removed = [{"key": k, "label": before[k]["label"], "cls": before[k]["cls"]}
               for k in before if k not in after]
    changed = []
    for k in before:
        if k not in after:
            continue
        fd = _field_diff(before[k]["state"], after[k]["state"], verbose=verbose)
        if fd:
            entry = {"key": k, "label": after[k]["label"], "cls": after[k]["cls"], "fields": fd}
            if _is_b16_sink(entry):
                entry["housekeeping"] = "b16_sink"
            changed.append(entry)
    housekeeping = [c for c in changed if c.get("housekeeping")]
    delta = {"added": added, "removed": removed, "changed": changed}
    hk = len(housekeeping)
    delta["summary"] = "+%d −%d ~%d" % (len(added), len(removed), len(changed))
    if hk:
        delta["housekeeping"] = hk
        delta["housekeeping_note"] = ("~%d template proxies sunk 2 km — B16 self-heal, engine "
                                      "housekeeping, not your op" % hk)
    # The flag ignores attributed housekeeping (ruling 1): a routine terrain-create must not
    # cry OPPENHEIMER, but ONE proxy deviating by one field falls out of the subset above and
    # is counted here like anything else.
    delta["flag"] = _flag(delta, [c for c in changed if not c.get("housekeeping")])
    # WorldPartition honesty (SPIKE-CHECK not yet built as a real removed/unloaded split):
    # on a partitioned map a `removed` key MAY be a stream-out, not a deletion. We cannot
    # yet reach the WP actor-descriptor list from Python to tell them apart, so we DISCLOSE
    # the ambiguity plainly rather than assert a deletion that might be streaming.
    if removed and _partitioned():
        delta["removed_note"] = ("world-partitioned map: a `removed` actor MAY have streamed "
                                 "out rather than been deleted (only loaded actors enumerate; "
                                 "the WP descriptor split is not yet built). Confirm a true "
                                 "deletion via outliner op=census, or re-diff with its cell "
                                 "resident.")
    return delta


# ── the OPPENHEIMER flag — a QUESTION, never an assertion ────────────────────────
# The differ is verb-blind, so it cannot know what the op INTENDED. The flag asks "— did you
# mean to?" when the blast radius carries a side-effect signature: something vanished, a
# quarter-map-scale vertical swing (the crater), or a broad radius. Tunable; deliberately a
# prompt, not a verdict.
_FLAG_DELETE = True          # any removal is worth a look (the deleted-sun North Star)
_FLAG_MAX_DZ_CM = 10000.0    # 100 m bounds-Z swing on any changed actor (the crater)
_FLAG_CHANGED_COUNT = 20     # a broad blast radius across many actors


def _max_dz(changed):
    """Largest |Δ| on any bounds/location Z field across the changed set (cm), or 0."""
    best = 0.0
    for c in changed:
        for f in c["fields"]:
            b, a = f["before"], f["after"]
            if isinstance(b, list) and isinstance(a, list) and len(b) == len(a):
                # location [x,y,z] (z=idx2) or bounds [ox,oy,oz,ex,ey,ez] (oz=idx2)
                if f["path"] in ("location", "bounds") or f["path"].endswith("/relative_location"):
                    try:
                        best = max(best, abs(float(a[2]) - float(b[2])))
                    except (TypeError, ValueError):
                        pass
    return best


def _flag(delta, flaggable_changed):
    """`flaggable_changed` is `changed` minus the attributed B16 housekeeping (ruling 1)."""
    reasons = []
    if _FLAG_DELETE and delta["removed"]:
        labels = ", ".join(r["label"] for r in delta["removed"][:5])
        reasons.append("%d actor(s) REMOVED (%s)" % (len(delta["removed"]), labels))
    dz = _max_dz(flaggable_changed)
    if dz >= _FLAG_MAX_DZ_CM:
        reasons.append("max ΔZ %.1f m" % (dz / 100.0))
    n = len(flaggable_changed) + len(delta["removed"])
    if n >= _FLAG_CHANGED_COUNT:
        reasons.append("%d actors changed/removed" % n)
    if not reasons:
        return None
    return "OPPENHEIMER: " + "; ".join(reasons) + " — intended?"


# ── status-block rendering ───────────────────────────────────────────────────────
def render_lines(delta, mode, verbose=False):
    """The level_delta block. One line when clean; expands with the flag + a bounded per-
    bucket listing when anything moved. The mode is always named (honesty about fidelity).
    B16 housekeeping proxies are summarized by one attributed line, not listed individually
    (they stay in the structured `changed` for programmatic/verbose access). verbose lifts
    the per-bucket display cap."""
    a, r, c = len(delta["added"]), len(delta["removed"]), len(delta["changed"])
    head = "  level Δ:    %s  (%s)" % (delta["summary"], mode)
    if not (a or r or c):
        return [head]
    cap = 10 ** 9 if verbose else 8
    lines = ["── level delta (SPEC-16 · %s) ─────────────────" % mode, "  " + delta["summary"]]
    if delta["flag"]:
        lines.append("  ⚠ " + delta["flag"])
    if delta.get("housekeeping_note"):
        lines.append("  ⚙ " + delta["housekeeping_note"])
    if delta.get("removed_note"):
        lines.append("  ⓘ " + delta["removed_note"])
    shown = [c_ for c_ in delta["changed"] if not c_.get("housekeeping")]
    for r_ in delta["removed"][:cap]:
        lines.append("  − %s [%s]" % (r_["label"], r_["cls"]))
    for a_ in delta["added"][:cap]:
        lines.append("  + %s [%s]" % (a_["label"], a_["cls"]))
    fcap = (10 ** 9 if verbose else 4)
    for c_ in shown[:cap]:
        paths = ", ".join(f["path"] for f in c_["fields"][:fcap])
        more = "" if len(c_["fields"]) <= fcap else " +%d" % (len(c_["fields"]) - fcap)
        lines.append("  ~ %s [%s]: %s%s" % (c_["label"], c_["cls"], paths, more))
    dropped = max(0, r - cap) + max(0, a - cap) + max(0, len(shown) - cap)
    if dropped:
        lines.append("  … +%d more (outliner op=diff verbose=true for the full list)" % dropped)
    lines.append("────────────────────────────────────────────")
    return lines
