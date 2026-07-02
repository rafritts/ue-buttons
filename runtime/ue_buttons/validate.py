"""SPEC-02 — the always-on correctness floor (`validate`), UE edition.

The second of the two forced senses (SPEC-02, ported from blender-buttons SPEC-16 +
`validation.py`). The reasoning ports verbatim; the *detectors* are rebuilt on UE's
native primitives — world-AABB overlap and downward world traces (cm) — instead of
Blender's bmesh/BVH. Read `validation.py` alongside this: the intent registry,
report-by-exception rendering, bidirectional tripwire, class-declaration hint, and
drift re-ground are the same machine, translated.

The floor runs automatically on the TOUCHED DELTA after every geometry/placement op and
reports BY EXCEPTION: one reassuring line when clean, findings (each carrying its FIX)
when not. Three checks:

  • ground       — intent-laden. Trace under an actor's base vs the actor's own base:
                   floating / buried, with the corrected z. Declarable (a↔"ground").
  • penetration  — intent-laden. AABB interpenetration depth + the nudge that separates.
                   Declarable (a↔b), optionally depth-bounded (max_depth).
  • z_fight      — INTENT-FREE (never suppressible). Coplanar same-orientation faces with
                   an overlapping footprint — the flicker of two surfaces in one plane;
                   full coincidence is called out as a duplicate transform.

Suppression is a positive, justified declaration (`validate op=expect … reason=…`),
never an ignore — keyed on the (check, {a,b}) RELATIONSHIP, collapsed to a count, and
enforced bidirectionally (a declared contact that VANISHES is itself a finding).

State (the intent registry + the drift accumulator) lives in `_state`, the one module
hot-reload never touches — so a runtime edit can't wipe declarations mid-build.
"""
import math

from . import _ue
from . import _state
from . import relational

# ── epsilons (cm — UE native; do NOT copy Blender's metre values) ──────────────
CONTACT = 0.1        # resting/flush face contact — below this is "touching", not a defect
GROUND_EPS = 2.0     # |base − ground| under this reads as resting; over it, float/bury
PEN_FLOOR = 1.0      # interpenetration below this is contact noise, not a finding
COPLANAR = 0.2       # ~2 mm — two parallel faces this close share a plane (z-fight)

# Intent-free checks — NO suppression path exists for these.
_INTENT_FREE = ("z_fight",)
# Intent-laden checks — quiet only via a declared intent (expect).
_LADEN = ("ground", "penetration")
_ALL_CHECKS = _INTENT_FREE + _LADEN

GROUND = "ground"    # the reserved counterpart token for a ground declaration

# The registry + drift accumulator live in _state (never hot-reloaded). But _state edits
# don't land until an editor restart, so a live session's _state may predate them — ensure
# the containers exist. hasattr-guarded so a validate.py reload never WIPES a live registry.
if not hasattr(_state, "intents"):
    _state.intents = []
if not hasattr(_state, "drift"):
    _state.drift = [0.0]


# ── declared-intent registry (lives in never-reloaded _state.intents) ──────────
# Each entry: {"check", "a", "b", "reason", "status": holding|vanished, "source",
#              "max_depth"?, "depth_at_decl"?}. Keyed on (check, {a,b}) — declaring
# cabin↔terrain intended does NOT also blind a later cabin↔rock penetration.

def _pair_key(check, a, b):
    return (check, frozenset((a, b)))


def _find_intent(check, a, b):
    key = _pair_key(check, a, b)
    for e in _state.intents:
        if _pair_key(e["check"], e["a"], e["b"]) == key:
            return e
    return None


def _actor_tags(label):
    a = _ue.find_by_label(label)
    return {str(t) for t in a.tags} if a is not None else set()


def _token_matches(token, actor_label):
    """A declaration token matches an actor by exact label OR — so one `expect
    trees↔ground` covers a whole scatter — by TAG membership when the token names a tag
    the actor carries (the UE analogue of blender-buttons' collection tokens). The
    reserved token "ground" only ever matches itself (handled by the caller)."""
    if token == actor_label:
        return True
    return token in _actor_tags(actor_label)


def _intent_for(check, x, y):
    """Fuzzy-match a live finding pair (x,y) against the registry, honouring tag tokens.
    For ground, y is the literal "ground"."""
    for e in _state.intents:
        if e["check"] != check:
            continue
        ea, eb = e["a"], e["b"]
        if check == GROUND:
            if _token_matches(ea, x) and eb == GROUND:
                return e
            continue
        if (_token_matches(ea, x) and _token_matches(eb, y)) or \
           (_token_matches(ea, y) and _token_matches(eb, x)):
            return e
    return None


def _prune_dead_intents():
    """Auto-GC declarations whose subject actor no longer exists, so a deleted actor
    never leaves a permanent un-clearable VANISHED tripwire. "ground" and tag tokens are
    never pruned (a tag with no members today may gain one tomorrow)."""
    changed = False
    for e in list(_state.intents):
        for tok in (e["a"], e["b"]):
            if tok == GROUND:
                continue
            if _ue.find_by_label(tok) is None and not _tag_exists(tok):
                _state.intents.remove(e)
                changed = True
                break
    return changed


def _tag_exists(tok):
    return any(tok in _actor_tags(a.get_actor_label()) for a in _ue.ueb_actors())


def add_intent(a, b, reason, check="penetration", source="agent", max_depth=None):
    """Declare a contact INTENDED — a positive, falsifiable assertion carrying its reason
    verbatim. Re-declaring a pair updates its reason. z_fight is intent-free and rejected.
    A ground declaration is a↔"ground" (b defaults to "ground")."""
    if check not in _LADEN:
        return {"error": f"'{check}' is intent-free — it can never be declared intended. "
                         f"Fix it, or it isn't a defect. Declarable: {list(_LADEN)}"}
    if check == GROUND and not b:
        b = GROUND
    if not a or not b:
        return {"error": "expect needs both parties (a, b) of the intended relationship"}
    if not (reason or "").strip():
        return {"error": "expect needs a reason — 'I intend X to touch Y because …'. An "
                         "assertion you can't justify is a bug you're hiding."}
    e = _find_intent(check, a, b)
    if e is None:
        e = {"check": check, "a": a, "b": b, "reason": reason.strip(),
             "status": "holding", "source": source}
        _state.intents.append(e)
    else:
        e["reason"] = reason.strip()
        e["source"] = source
    if check == "penetration":
        # A depth envelope blesses the overlap only up to max_depth (cm); anything deeper
        # is still a finding, so a broad 'gravel↔terrain intended' can't hide an 11 cm
        # poke-through. Record depth at declaration for a later 'now Nx deeper' tripwire.
        e["max_depth"] = max_depth
        e["depth_at_decl"] = _pen_depth(a, b)
    return {"success": True, "intent": dict(e)}


def revoke_intent(a, b, check="penetration"):
    e = _find_intent(check, a, b)
    if e is None:
        return {"error": f"no declared {check} intent for {a}↔{b}"}
    _state.intents.remove(e)
    return {"success": True, "revoked": {"check": check, "a": a, "b": b}}


def list_intents():
    return [dict(e) for e in _state.intents]


# ── geometry helpers over world AABBs ──────────────────────────────────────────

def _substrates():
    """Labels the actor-floor never validates as actors: terrains, scatter stands, path
    labels. A terrain IS the ground (the ground check consults it via a trace, not an
    AABB overlap); a scatter stand's AABB spans its whole region (overlap is meaningless);
    a path is not an actor. Everything placed ON these is validated normally."""
    return set(_state.landscapes) | set(_state.scatters) | set(_state.paths)


def _spatial_actors(labels):
    """Resolve labels → (label, bounds) for real, non-substrate ueb actors with extent."""
    subs = _substrates()
    out = []
    for lbl in labels:
        if lbl in subs:
            continue
        a = _ue.find_by_label(lbl)
        if a is None:
            continue
        b = _ue.bounds(a)
        if b["size"] == [0, 0, 0]:
            continue
        out.append((lbl, b))
    return out


def _neighbors():
    """All real (non-substrate) ueb actors as (label, bounds) — the pool a touched actor
    is checked against for penetration / z-fight."""
    subs = _substrates()
    out = []
    for a in _ue.ueb_actors():
        lbl = a.get_actor_label()
        if lbl in subs:
            continue
        b = _ue.bounds(a)
        if b["size"] == [0, 0, 0]:
            continue
        out.append((lbl, b))
    return out


def _overlaps(a, b):
    """Per-axis AABB overlap (cm). Positive = interpenetrating on that axis; ≤0 =
    separated/touching. Returns [ox, oy, oz]."""
    return [min(a["max"][i], b["max"][i]) - max(a["min"][i], b["min"][i]) for i in range(3)]


def _pen_depth(a_label, b_label):
    """True AABB interpenetration depth (cm, 0 if not overlapping) between two live
    actors — recomputed every report so a declared pair's depth can be re-checked."""
    a = _ue.find_by_label(a_label)
    b = _ue.find_by_label(b_label)
    if a is None or b is None:
        return 0.0
    ov = _overlaps(_ue.bounds(a), _ue.bounds(b))
    return round(min(ov), 2) if all(o > 0 for o in ov) else 0.0


# ── the three detectors ────────────────────────────────────────────────────────

def _ground_ignore():
    """Every placed (non-substrate) ueb actor — the trace excludes them all so the ground
    check reads the SUBSTRATE beneath, never a neighbour's roof or the actor's own top
    (gaps.md G18). Substrates (terrain/scatter/path) stay hittable; the engine's own
    landscape proxies aren't ueb actors, so they answer too."""
    subs = _substrates()
    return [a for a in _ue.ueb_actors() if a.get_actor_label() not in subs]


def _ground_findings(scope):
    """Trace under each touched actor's base-centre, against the SUBSTRATE only (every
    placed actor ignored — G18), and compare to its own min-z. A miss (nothing beneath, or
    collision not yet cooked — see bugs.md B3) is reported as an HONEST can't-verify, never
    silently passed."""
    out = []
    ignore = _ground_ignore()
    for lbl, b in scope:
        cx, cy = b["center"][0], b["center"][1]
        base_z = b["min"][2]
        gz = _ue.trace_ground(cx, cy, ignore=ignore)
        if gz is None:
            out.append({"check": GROUND, "a": lbl, "b": GROUND, "kind": "unverifiable",
                        "message": f"{lbl}: nothing traced beneath the base — no ground, or "
                                   f"collision not cooked yet (can't verify support)"})
            continue
        gap = base_z - gz
        if gap > GROUND_EPS:
            out.append({"check": GROUND, "a": lbl, "b": GROUND, "depth": round(gap, 1),
                        "message": f"{lbl} floats {round(gap, 1)}cm above ground "
                                   f"(base z={round(base_z, 1)}, ground z={round(gz, 1)}) "
                                   f"→ drop base to z={round(gz, 1)}"})
        elif gap < -GROUND_EPS:
            out.append({"check": GROUND, "a": lbl, "b": GROUND, "depth": round(-gap, 1),
                        "message": f"{lbl} buried {round(-gap, 1)}cm "
                                   f"(base z={round(base_z, 1)}, ground z={round(gz, 1)}) "
                                   f"→ raise base to z={round(gz, 1)}"})
    return out


def _penetration_findings(scope, neighbors):
    """AABB interpenetration between a touched actor and any other real actor. Depth =
    smallest positive axis overlap; the fix is the nudge along that axis that separates
    them. Contact within PEN_FLOOR is not a finding."""
    out = []
    scope_names = {lbl for lbl, _ in scope}
    seen = set()
    for la, ba in scope:
        for lb, bb in neighbors:
            if lb == la:
                continue
            key = frozenset((la, lb))
            if key in seen:
                continue
            # a touched↔touched pair is only reported once; touched↔untouched always.
            if lb in scope_names:
                seen.add(key)
            ov = _overlaps(ba, bb)
            if not all(o > 0 for o in ov):
                continue
            axis = min(range(3), key=lambda i: ov[i])
            depth = round(ov[axis], 1)
            if depth < PEN_FLOOR:
                continue
            sign = 1.0 if ba["center"][axis] >= bb["center"][axis] else -1.0
            nudge = [0.0, 0.0, 0.0]
            nudge[axis] = round(sign * depth, 1)
            axname = "XYZ"[axis]
            out.append({"check": "penetration", "a": la, "b": lb, "depth": depth,
                        "message": f"{la} penetrates {lb} by {depth}cm along {axname} "
                                   f"→ nudge {nudge}"})
    return out


def _zfight_findings(scope, neighbors):
    """Coplanar same-orientation faces with an overlapping footprint — two surfaces in one
    plane (the classic z-fight flicker). Full coincidence (both faces of a box coplanar
    with another's) is called out as an accidental duplicate transform. Intent-free."""
    out = []
    scope_names = {lbl for lbl, _ in scope}
    seen = set()
    for la, ba in scope:
        for lb, bb in neighbors:
            if lb == la:
                continue
            key = frozenset((la, lb))
            if key in seen:
                continue
            if lb in scope_names:
                seen.add(key)
            planes = []
            coincident_axes = 0
            for i in range(3):
                other = [j for j in range(3) if j != i]
                # need overlapping footprint on the perpendicular axes AND shared volume
                if not all(_strict_ov(ba, bb, j) for j in other):
                    continue
                if _overlaps(ba, bb)[i] <= 0:
                    continue
                minc = abs(ba["min"][i] - bb["min"][i]) < COPLANAR
                maxc = abs(ba["max"][i] - bb["max"][i]) < COPLANAR
                if minc or maxc:
                    planes.append("XYZ"[i])
                if minc and maxc:
                    coincident_axes += 1
            if not planes:
                continue
            if coincident_axes == 3:
                out.append({"check": "z_fight", "a": la, "b": lb,
                            "message": f"{la} is a DUPLICATE transform of {lb} "
                                       f"(fully coincident) → delete one"})
            else:
                out.append({"check": "z_fight", "a": la, "b": lb,
                            "message": f"{la}↔{lb} coplanar on {'/'.join(planes)} "
                                       f"(overlapping faces in one plane — z-fight)"})
    return out


def _strict_ov(a, b, i):
    return a["min"][i] < b["max"][i] and a["max"][i] > b["min"][i]


# ── the aggregator ─────────────────────────────────────────────────────────────

def run_validate(touched_labels=None, scene_wide=False, verbose=False):
    """Run the floor over the touched delta (or the whole scene, op=run). Returns a
    structured dict plus a pre-rendered one-line `line` for the status block. Adds no
    detection logic beyond the three detectors above; composes + classifies them against
    the declared-intent registry. verbose (op=run) lists every finding, uncapped."""
    _prune_dead_intents()

    # Scene vs delta is an EXPLICIT choice, never inferred from a falsy label list (B4):
    # a typo'd delta target must not silently flip into a whole-scene sweep.
    if scene_wide:
        scope = _neighbors()
        if not scope:
            return {"passed": True, "intent_free": [], "ground": _empty(GROUND),
                    "penetration": _empty("penetration"),
                    "line": "validate: clean — no placed actors in scope"}
    else:
        labels = touched_labels or []
        scope = _spatial_actors(labels)
        if not scope:
            # Empty delta scope is its OWN verdict, attributed — never a clean pass (B4).
            # silence-because-nothing must never read as silence-because-clean.
            return {"passed": None, "intent_free": [], "ground": _empty(GROUND),
                    "penetration": _empty("penetration"),
                    "line": f"validate: nothing to check — {_unresolved_reason(labels)}"}
    neighbors = _neighbors()

    zfight = _zfight_findings(scope, neighbors)
    ground = _classify(GROUND, _ground_findings(scope), scope)
    pen = _classify("penetration", _penetration_findings(scope, neighbors), scope)

    passed = (not zfight and not ground["new"] and not ground["vanished"]
              and not pen["new"] and not pen["vanished"] and not pen.get("deeper"))
    line = _render_line(zfight, ground, pen, verbose)
    return {"passed": passed, "intent_free": zfight, "ground": ground,
            "penetration": pen, "line": line}


def _unresolved_reason(labels):
    """Attribute WHY a delta scope came up empty (B4) — a misspelled name must read as
    'no such actor', never as a clean scene."""
    if not labels:
        return "no resolvable focus for this edit"
    subs = _substrates()
    bits = []
    for lbl in labels:
        if lbl in subs:
            bits.append(f"{lbl} is a substrate (checked by trace, not as an actor)")
        elif _ue.find_by_label(lbl) is None:
            bits.append(f"{lbl}: no such actor (missing or renamed)")
        else:
            bits.append(f"{lbl}: zero-extent (non-spatial)")
    return "; ".join(bits)


def _empty(check):
    return {"declared": _declared_count(check), "new": [], "vanished": [], "deeper": [],
            "intended": 0, "hint": None}


def _declared_count(check):
    return len([e for e in _state.intents if e["check"] == check])


def _classify(check, findings, scope):
    """Split raw laden findings into new / intended-collapsed-to-a-count, apply the
    depth-envelope + change tripwire, compute the VANISHED bidirectional invariant over
    declared pairs this op touched, and offer the class-declaration hint (≥6 sharing one
    counterpart)."""
    scope_names = {lbl for lbl, _ in scope}
    intended, new, deeper = 0, [], []
    live_pairs = set()
    for f in findings:
        a, b = f["a"], f["b"]
        live_pairs.add(frozenset((a, b)))
        e = _intent_for(check, a, b)
        if e is None:
            new.append(f)
            continue
        # depth envelope (penetration): deeper than blessed is STILL a finding.
        md = e.get("max_depth")
        d = f.get("depth")
        if check == "penetration" and md is not None and d is not None and d > md + PEN_FLOOR:
            f = dict(f)
            f["message"] = (f"{a}↔{b} {d}cm EXCEEDS declared max {md}cm (deeper than "
                            f"intended — fix or raise max_depth)")
            new.append(f)
            continue
        e["status"] = "holding"
        intended += 1
        # DEEPER tripwire (B5): the declare-first flow ("gravel WILL seat into terrain" →
        # then place it) records depth_at_decl = 0 — falsy, so a fixed `d0 and …` guard is
        # dead for exactly those intents. Treat 0 as "not yet observed": latch the first
        # nonzero depth as the baseline, then arm the 2× escalation against it.
        d0 = e.get("depth_at_decl")
        if check == "penetration" and d:
            if not d0:
                e["depth_at_decl"] = d0 = d
            elif d > 2 * d0 + PEN_FLOOR:
                deeper.append({"a": a, "b": b, "now": d, "then": d0})

    # bidirectional invariant — a declared pair this op TOUCHED that no longer shows the
    # finding is VANISHED (blessings can't rot silently). Only object pairs actually in
    # scope; tag-scoped declarations are too broad to vanish.
    vanished = []
    for e in _state.intents:
        if e["check"] != check:
            continue
        a, b = e["a"], e["b"]
        parties = [a] if b == GROUND else [a, b]
        is_obj = all(_ue.find_by_label(p) is not None for p in parties)
        touched = any(p in scope_names for p in parties)
        if is_obj and touched and frozenset((a, b)) not in live_pairs:
            e["status"] = "vanished"
            vanished.append({"a": a, "b": b, "reason": e["reason"]})

    hint = _class_hint(check, new)
    return {"declared": _declared_count(check), "new": new, "vanished": vanished,
            "deeper": deeper, "intended": intended, "hint": hint}


def _class_hint(check, new):
    """When ≥6 new findings all involve one counterpart it's almost always a settled
    group (a scatter on one substrate). Offer the ONE class declaration that collapses
    them instead of leaving the agent to bless instances one by one (blender-buttons
    G125). For ground the counterpart is "ground"; suggest tagging + a tag token."""
    if len(new) < 6:
        return None
    counts = {}
    for f in new:
        for tok in (f["a"], f["b"]):
            counts[tok] = counts.get(tok, 0) + 1
    common, c = max(counts.items(), key=lambda kv: kv[1])
    if c < 6:
        return None
    if check == GROUND:
        return (f"{c} actors float above ground — if it's an intended set, tag them and "
                f"declare validate op=expect check=ground a=<tag> once")
    return (f"{c} of these involve '{common}' — if it's a settled group, tag the instances "
            f"and validate op=expect a=<tag> b={common} to declare the whole class at once")


# ── report-by-exception rendering ──────────────────────────────────────────────

def _render_line(zfight, ground, pen, verbose=False, excluded=0):
    """Compact, report-by-exception status line. Clean ⇒ a short reassurance so
    silence-because-clean is explicit. Intended contacts collapse to a count; only the
    NEW delta is listed, capped (~4) with the remainder as a count. `excluded` is the
    non-renderable count the floor skipped (SPEC-03's predicate — 0 until it lands)."""
    cap = 999 if verbose else 4
    segs = []
    if zfight:
        shown = "; ".join(f["message"] for f in zfight[:cap])
        more = "" if verbose or len(zfight) <= cap else f" …(+{len(zfight) - cap})"
        segs.append(f"z_fight {len(zfight)}: {shown}{more}")
    for name, grp in (("ground", ground), ("penetration", pen)):
        parts = []
        if grp["declared"]:
            parts.append(f"{grp['declared']} intended")
        if grp["new"]:
            shown = "; ".join(f["message"] for f in grp["new"][:cap])
            more = ("" if verbose or len(grp["new"]) <= cap
                    else f" …(+{len(grp['new']) - cap}; validate op=run verbose to list)")
            parts.append(f"{len(grp['new'])} new: {shown}{more}")
        for v in grp["vanished"][:cap]:
            parts.append(f"VANISHED {v['a']}↔{v['b']} (declared intended — confirm or clear)")
        for d in grp.get("deeper", [])[:cap]:
            parts.append(f"DEEPER {d['a']}↔{d['b']} {d['now']}cm now vs {d['then']}cm at "
                         f"declaration (re-confirm)")
        if parts:
            segs.append(f"{name} " + " · ".join(parts))
        if grp.get("hint"):
            segs.append("↳ " + grp["hint"])
    excl = f"  [{excluded} excluded]" if excluded else ""
    if not segs:
        return f"validate: clean{excl}"
    return "validate: " + " | ".join(segs) + excl


# ── Sense 1: the ambient feel delta ────────────────────────────────────────────

def feel_delta(label):
    """A cheap perceptual note on the actor the op just touched — world dims + its live
    contacts, as PERCEPTION (no verdict). The floor of seeing: the agent can't opt out of
    looking at its own work. Delta-scoped to the one touched actor."""
    a = _ue.find_by_label(label) if label else None
    if a is None:
        return None
    b = _ue.bounds(a)
    if b["size"] == [0, 0, 0]:
        return None
    dims = "×".join(str(round(v, 1)) for v in b["size"])
    rels = []
    # Ground support first — the single most common relationship in an environment build
    # (thing sits on terrain), which AABB-face math can NEVER see because a terrain's AABB
    # top is its highest ridge, not the surface under the actor (gaps.md G19). Same trace
    # the floor runs, folded in as PERCEPTION (no verdict — the validate line judges).
    gz = _ue.trace_ground(b["center"][0], b["center"][1], ignore=_ground_ignore())
    if gz is not None:
        gap = round(b["min"][2] - gz, 1)
        if abs(gap) <= GROUND_EPS:
            rels.append(f"rests_on ground (traced, gap {abs(gap)}cm)")
        elif gap > 0:
            rels.append(f"{gap}cm above traced ground")
        else:
            rels.append(f"{-gap}cm into traced ground")
    subs = _substrates()
    for other in _ue.ueb_actors():
        if other == a:
            continue
        # Substrates out of the relation pool: their AABB faces produce spurious flush_*
        # relations near the terrain's outer boundary and never a real contact (G19).
        if other.get_actor_label() in subs:
            continue
        ob = _ue.bounds(other)
        if ob["size"] == [0, 0, 0]:
            continue
        rs = relational._relations(b, ob)
        if rs:
            rels.append(f"{'/'.join(rs)} {other.get_actor_label()}")
    tail = " · " + ", ".join(rels[:4]) if rels else " · (no contacts)"
    return f"feel: {label} — {dims}cm{tail}"


# ── drift → periodic re-ground (SPEC-02 §4; blender-buttons G117) ──────────────
# Per-op feedback is the spine; this re-anchors a stale mental model on a long build.
# Weight by how much an op can invalidate what the agent believes: a landscape reshape or
# a scatter rearranges everything; a nudge barely anything.
_DRIFT_THRESHOLD = 100.0
_DRIFT_HIGH = {"landscape", "scatter", "path"}   # spatial ops move the world under you


def accrue_drift(verb):
    w = 25.0 if verb in _DRIFT_HIGH else 4.0
    _state.drift[0] += w
    if _state.drift[0] < _DRIFT_THRESHOLD:
        return None
    _state.drift[0] = 0.0
    return _reground_recap()


def _reground_recap():
    actors = [a.get_actor_label() for a in _ue.ueb_actors()]
    subs = _substrates()
    placed = [x for x in actors if x not in subs]
    listed = ", ".join(placed[:24]) + (f", … (+{len(placed) - 24})" if len(placed) > 24 else "")
    holding = [f"{e['a']}↔{e['b']}" for e in _state.intents if e.get("status") == "holding"]
    vanished = [f"{e['a']}↔{e['b']}" for e in _state.intents if e.get("status") == "vanished"]
    return {"actor_count": len(placed), "actors": listed,
            "declared_holding": holding, "declared_vanished": vanished}


# ── the agent verb (routed from verbs._v_validate) ─────────────────────────────

def handle(p):
    op = p.get("op", "run")
    if op == "run":
        targets = p.get("targets")
        if isinstance(targets, str):
            targets = [s.strip() for s in targets.split(",") if s.strip()] or None
        return {"validate": run_validate(targets, scene_wide=not targets,
                                         verbose=bool(p.get("verbose")))}
    if op == "expect":
        check = (p.get("check") or "penetration").strip()
        md = p.get("max_depth")
        return add_intent(p.get("a", ""), p.get("b", ""), p.get("reason", ""),
                          check=check, max_depth=(float(md) if md not in (None, "", 0) else None))
    if op == "forget":
        return revoke_intent(p.get("a", ""), p.get("b", ""),
                             check=(p.get("check") or "penetration").strip())
    if op == "intended":
        _prune_dead_intents()   # never list a declaration whose subject is already gone
        return {"intents": list_intents()}
    return {"error": f"unknown validate op '{op}'. known: run | expect | forget | intended"}
