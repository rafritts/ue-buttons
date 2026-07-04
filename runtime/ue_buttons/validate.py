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
import time

import unreal

from . import _ue
from . import _state
from . import relational
from . import render

# ── epsilons (cm — UE native; do NOT copy Blender's metre values) ──────────────
CONTACT = 0.1        # resting/flush face contact — below this is "touching", not a defect
GROUND_EPS = 2.0     # |base − ground| under this reads as resting; over it, float/bury
PEN_FLOOR = 1.0      # interpenetration below this is contact noise, not a finding
COPLANAR = 0.2       # ~2 mm — two parallel faces this close share a plane (z-fight)
GROUND_SEAT = 0.5    # G21: ground-snap seats base THIS far above the trace — inside the
                     # resting band, above the coplanar band, so the placer and the
                     # ground-z-fight detector can never fight over the same actor

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
    trees↔ground` covers a whole stand — by TAG membership when the token names a tag
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
    """Labels the actor-floor never validates as actors: terrains, foliage stands, spline
    labels, spline surface strips. A terrain IS the ground (the ground check consults it via
    a trace, not an AABB overlap); a foliage stand's AABB spans its whole region (overlap
    is meaningless); a spline is not an actor and its surface strip is the spline made visible.
    Everything placed ON these is validated normally. One shared definition (_ue)."""
    return _ue.substrate_labels()


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
    (gaps.md G18). Substrates (terrain/foliage/spline) stay hittable; the engine's own
    landscape proxies aren't ueb actors, so they answer too."""
    subs = _substrates()
    return [a for a in _ue.ueb_actors() if a.get_actor_label() not in subs]


def _ground_findings(scope):
    """Trace under each touched actor's base-centre, against the SUBSTRATE only (every
    placed actor ignored — G18), and compare to its own min-z. A miss (nothing beneath, or
    collision not yet cooked — see bugs.md B3) is reported as an HONEST can't-verify, never
    silently passed. Returns (laden ground findings, intent-free ground-coplanar z-fights):
    G21 — a base within COPLANAR of the terrain surface is the spec's own 'floor at exactly
    terrain height' case; exact equality is a bug, not a coincidence. Safe to arm now that
    ground-snap seats at +GROUND_SEAT (the placer can't produce it by accident)."""
    out, coplanar = [], []
    ignore = _ground_ignore()
    for lbl, b in scope:
        a = _ue.find_by_label(lbl)
        cx, cy, base_z = (_ue.support_point(a, b) if a is not None
                          else [b["center"][0], b["center"][1], b["min"][2]])
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
        elif abs(gap) <= COPLANAR and a is not None and render.is_renderable(a):
            coplanar.append({"check": "z_fight", "a": lbl, "b": GROUND,
                             "message": f"{lbl} base is COPLANAR with the ground surface "
                                        f"(gap {round(gap, 2)}cm ≤ {COPLANAR}cm — exact "
                                        f"equality z-fights) → sink 1–2cm or raise "
                                        f"~{GROUND_SEAT}cm (ground-snap seats there)"})
    return out, coplanar


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

    ground_raw, ground_coplanar = _ground_findings(scope)
    zfight = _zfight_findings(scope, neighbors) + ground_coplanar
    ground = _classify(GROUND, ground_raw, scope)
    pen = _classify("penetration", _penetration_findings(scope, neighbors), scope)

    # SPEC-03 handshake: the floor names the non-renderable actors it SKIPPED (its own
    # blind spot), rather than pretending it validated them. Count over the checked pool.
    excluded = _excluded_count(scope, neighbors)

    passed = (not zfight and not ground["new"] and not ground["vanished"]
              and not pen["new"] and not pen["vanished"] and not pen.get("deeper"))
    line = _render_line(zfight, ground, pen, verbose, excluded=excluded)
    return {"passed": passed, "intent_free": zfight, "ground": ground,
            "penetration": pen, "line": line}


def _excluded_count(scope, neighbors):
    """How many distinct actors in the checked pool are NON-renderable (SPEC-03's
    predicate) — the floor's blind spot, surfaced as `[N excluded]` so a skipped actor is
    never mistaken for a validated one."""
    labels = {lbl for lbl, _ in scope} | {lbl for lbl, _ in neighbors}
    n = 0
    for lbl in labels:
        a = _ue.find_by_label(lbl)
        if a is not None and not render.is_renderable(a):
            n += 1
    return n


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
    group (a stand on one substrate). Offer the ONE class declaration that collapses
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
    sx, sy, base_z = _ue.support_point(a, b)
    gz = _ue.trace_ground(sx, sy, ignore=_ground_ignore())
    if gz is not None:
        gap = round(base_z - gz, 1)
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
# Weight by how much an op can invalidate what the agent believes: a terrain reshape or
# a paint rearranges everything; a move barely anything.
_DRIFT_THRESHOLD = 100.0
_DRIFT_HIGH = {"terrain", "foliage", "spline"}   # spatial ops move the world under you


def accrue_drift(verb):
    w = 25.0 if verb in _DRIFT_HIGH else 4.0
    _state.drift[0] += w
    if _state.drift[0] < _DRIFT_THRESHOLD:
        return None
    _state.drift[0] = 0.0
    return _reground_recap()


def spatial_roster():
    """G43: one line of population-shaped content from the ueb registries — terrains,
    splines (length), stands (instance count). The actor-shaped summaries (status block,
    census, re-ground) all undercount the world without it; five numbers fix all three."""
    parts = []
    if _state.terrains:
        parts.append("terrains: " + ", ".join(sorted(_state.terrains)))
    if _state.splines:
        parts.append("splines: " + ", ".join(
            f"{k} {round(v.get('length_cm', 0) / 100.0)}m"
            for k, v in sorted(_state.splines.items())))
    if _state.foliage_stands:
        parts.append("stands: " + ", ".join(
            f"{k} {v.get('count', '?')}"
            for k, v in sorted(_state.foliage_stands.items())))
    return " · ".join(parts)


def _reground_recap():
    actors = [a.get_actor_label() for a in _ue.ueb_actors()]
    subs = _substrates()
    placed = [x for x in actors if x not in subs]
    listed = ", ".join(placed[:24]) + (f", … (+{len(placed) - 24})" if len(placed) > 24 else "")
    holding = [f"{e['a']}↔{e['b']}" for e in _state.intents if e.get("status") == "holding"]
    vanished = [f"{e['a']}↔{e['b']}" for e in _state.intents if e.get("status") == "vanished"]
    return {"actor_count": len(placed), "actors": listed,
            "spatial": spatial_roster(),
            "declared_holding": holding, "declared_vanished": vanished}


# ── state reconciliation (SPEC-03 §"clean/dirty/orphaned"; closes G16) ─────────
# blender-buttons keeps NO parallel server store — the datablocks ARE the registry
# (handles.py). ueb can't: WP shards foliage into per-cell components and _state survives a
# hot-reload (by design), so the registry can outlive the level it describes — the phantom
# hamlet stands (G16). reconcile diffs each registry against the editor's OWN tally and
# classifies clean / dirty (drifted but resolves, with self|external attribution) / orphaned
# (backing gone → GC'd, so a level change can't leave a permanent phantom) / untracked
# (backing in the level with no registry entry — the reverse phantom).

def _foliage_tally(label):
    """(instances, components) the editor actually holds for a foliage-stand label, by tag."""
    from . import foliage as foliagemod
    tag = foliagemod._FOLIAGE_TAG + label
    comps = [c for c in foliagemod._ifa_fismcs()
             if tag in [str(t) for t in c.get_editor_property("component_tags")]]
    return sum(c.get_instance_count() for c in comps), len(comps)


def _editor_stand_labels():
    """Every foliage-stand label the editor's tags claim (may exceed the registry)."""
    from . import foliage as foliagemod
    pref = foliagemod._FOLIAGE_TAG
    out = set()
    for c in foliagemod._ifa_fismcs():
        for t in c.get_editor_property("component_tags"):
            s = str(t)
            if s.startswith(pref):
                out.add(s[len(pref):])
    return out


def _drift_attribution(label):
    """self = a logged ueb op references this label (the drift is ours); external = nothing
    explains it (the loud alarm — a human or another session moved it)."""
    for h in _state.history:
        if label and (label in (h.get("label") or "") or label in (h.get("summary") or "")):
            return "self (a ueb op references this label)"
    return "external (no ueb op explains the drift — investigate before building on it)"


def reconcile(gc=True):
    """Diff the ueb registries (_state.foliage_stands/terrains/splines) against the editor's own
    tally; classify + optionally GC orphans. The mechanical cure for G16 — a self-reported
    count in a vacuum is exactly what let the phantom hamlet persist."""
    report = {"clean": [], "dirty": [], "orphaned": [], "untracked": []}

    for label, meta in list(_state.foliage_stands.items()):
        inst, comps = _foliage_tally(label)
        recorded = meta.get("count", 0)
        if comps == 0:
            report["orphaned"].append({"kind": "foliage", "label": label,
                "reason": f"registry claims {recorded} instances but the level has no foliage "
                          f"for it (level changed or cleared)"})
            if gc:
                _state.foliage_stands.pop(label, None)
        elif inst == recorded:
            report["clean"].append({"kind": "foliage", "label": label, "instances": inst})
        else:
            report["dirty"].append({"kind": "foliage", "label": label, "recorded": recorded,
                "editor": inst, "attribution": _drift_attribution(label),
                "reason": f"registry {recorded} vs editor {inst} instances"})

    for label in list(_state.terrains):
        if _ue.find_by_label(label) is None:
            report["orphaned"].append({"kind": "terrain", "label": label,
                "reason": "no actor carries this label (level changed or the terrain was deleted)"})
            if gc:
                _state.terrains.pop(label, None)
        else:
            report["clean"].append({"kind": "terrain", "label": label})

    for label, pdata in list(_state.splines.items()):
        terr = pdata.get("terrain", "terrain")
        if terr not in _state.terrains and _ue.find_by_label(terr) is None:
            report["orphaned"].append({"kind": "spline", "label": label,
                "reason": f"the terrain '{terr}' it was carved into is gone"})
            if gc:
                _state.splines.pop(label, None)
                strip = pdata.get("surface_actor")     # the ribbon dies with its spline
                sa = _ue.find_by_label(strip) if strip else None
                if sa is not None:
                    _ue.actor_subsystem().destroy_actor(sa)
        else:
            report["clean"].append({"kind": "spline", "label": label})

    for label in _editor_stand_labels():
        if label not in _state.foliage_stands:
            inst, _ = _foliage_tally(label)
            report["untracked"].append({"kind": "foliage", "label": label, "instances": inst,
                "reason": "foliage tagged in the level with no registry entry (registry wiped, "
                          "or placed in another session) — `foliage op=remove` clears it by tag"})

    report["summary"] = (f"{len(report['clean'])} clean, {len(report['dirty'])} dirty, "
                         f"{len(report['orphaned'])} orphaned{' (GC’d from registry)' if gc else ''}, "
                         f"{len(report['untracked'])} untracked")
    return report


# ── SPEC-08: the lint sweep (validate op=run scope=…) ──────────────────────────
# Three layers, cheapest first, one severity-ranked findings list out:
#   1. the spatial floor, widened (run_validate — nothing new to build)
#   2. the SPEC-07 rule table at firing point 3 (rules.sweep — one walk, N rules)
#   3. the engine's own validators, wrapped (a floor, not a roof — and NEVER console
#      MAP CHECK over RC: it crashes the editor (G41) and found nothing anyway)
# No persisted lint.md — findings are perishable ground truth; re-running is cheap.

def _floor_findings(fl):
    """Convert a run_validate result into lint findings. The floor's messages already
    carry their fix (SPEC-02); laden ones additionally offer the declare path."""
    out = []
    for f in fl["intent_free"]:
        out.append({"severity": "degrades", "source": "floor:z_fight", "subject": f["a"],
                    "message": f["message"],
                    "next": "z_fight is intent-free — apply the fix in the message; "
                            "there is no declare path"})
    for check in ("ground", "penetration"):
        grp = fl[check]
        for f in grp["new"]:
            msg = f["message"]
            nxt = {"declare": f"validate op=expect a={f['a']} b={f['b']} check={check} "
                              f"reason=<why this contact is intended>"}
            if "→" in msg:
                nxt["fix"] = msg.split("→", 1)[1].strip()
            out.append({"severity": "degrades", "source": f"floor:{check}",
                        "subject": f["a"], "message": msg, "next": nxt})
        for v in grp["vanished"]:
            out.append({"severity": "degrades", "source": f"floor:{check}",
                        "subject": v["a"],
                        "message": f"declared {check} {v['a']}↔{v['b']} VANISHED "
                                   f"(was: {v['reason']})",
                        "next": f"confirm the change is intended, or validate op=forget "
                                f"a={v['a']} b={v['b']} check={check}"})
        for d in grp.get("deeper", []):
            out.append({"severity": "degrades", "source": f"floor:{check}",
                        "subject": d["a"],
                        "message": f"{d['a']}↔{d['b']} {d['now']}cm now vs {d['then']}cm "
                                   f"at declaration (2× deeper than blessed)",
                        "next": f"re-confirm: validate op=expect a={d['a']} b={d['b']} "
                                f"check={check} reason=<updated reason> — or fix the sink"})
    return out


def _engine_findings(asset_paths, deadline):
    """Layer 3: EditorValidatorSubsystem over the scope's asset set, in chunks so the
    seconds budget is checked between assets. Returns (findings, notes, checked, total).
    Per-asset details are extracted defensively — when a failure's details are
    unreadable, the finding says so and points at the editor's Message Log instead of
    pretending the asset passed."""
    findings, notes = [], []
    evs = unreal.get_editor_subsystem(unreal.EditorValidatorSubsystem)
    ar = unreal.AssetRegistryHelpers.get_asset_registry()
    datas = []
    for pth in asset_paths:
        try:
            ad = ar.get_asset_by_object_path(pth)
        except Exception:
            ad = None
        if ad is not None and ad.is_valid():
            datas.append(ad)
    settings = unreal.ValidateAssetsSettings()
    settings.set_editor_property("collect_per_asset_details", True)
    settings.set_editor_property("show_if_no_failures", False)
    checked, chunk = 0, 25
    for i in range(0, len(datas), chunk):
        if time.monotonic() > deadline:
            notes.append(f"engine validators stopped at {checked}/{len(datas)} assets "
                         f"(seconds budget) — re-run to continue")
            break
        batch = datas[i:i + chunk]
        n_bad, res = evs.validate_assets_with_settings(batch, settings)
        checked += int(res.get_editor_property("num_checked"))
        if not n_bad:
            continue
        extracted = 0
        try:
            details = res.get_editor_property("assets_details")
            items = details.items() if hasattr(details, "items") else []
        except Exception:
            items = []
        for key, d in items:
            msgs, verdict = [], None
            for prop in ("validation_errors", "validation_warnings"):
                try:
                    msgs += [str(t) for t in d.get_editor_property(prop)]
                except Exception:
                    pass
            try:
                verdict = str(d.get_editor_property("result"))
            except Exception:
                pass
            if msgs or (verdict and "INVALID" in verdict.upper()):
                extracted += 1
                findings.append({
                    "severity": "engine", "source": "engine-validator",
                    "subject": str(key),
                    "message": f"{key}: {verdict or 'flagged'} — "
                               f"{'; '.join(msgs) or 'no message text exposed'}",
                    "next": "open the editor's Message Log › Asset Check for the "
                            "clickable detail"})
        if extracted < n_bad:
            findings.append({
                "severity": "engine", "source": "engine-validator", "subject": "(batch)",
                "message": f"{n_bad - extracted} asset(s) in this batch failed engine "
                           f"validation but exposed no readable details",
                "next": "open the editor's Message Log › Asset Check"})
    return findings, notes, checked, len(datas)


def lint(p):
    """The SPEC-08 sweep. scope: "all" (whole level) | "selection" (SPEC-06 deixis —
    what the user has selected) | a label (foliage stand or actor). Findings are
    numbered, severity-ranked (breaks > degrades > engine notes), each with provenance
    and a ready-to-fire next. seconds= (default 20) is the wall-clock budget."""
    from . import rules as rulesmod
    t0 = time.monotonic()
    deadline = t0 + float(p.get("seconds") or 20.0)
    scope = p.get("scope")
    stand_labels = actor_labels = None    # None = level-wide
    floor_targets = None                  # None = scene-wide floor
    notes = []
    if scope == "selection":
        from . import deixis
        sel = deixis.selection()
        if not sel.get("selected"):
            return {"error": "scope=selection but nothing is selected in the editor",
                    "next": "ask the user to click the thing ('select it for me'), "
                            "then re-issue validate op=run scope=selection"}
        stand_labels, actor_labels = set(), set()
        for e in sel.get("entries", []):
            if e.get("class") == "InstancedFoliageActor":
                stand_labels.update(e.get("stands") or [])
            else:
                actor_labels.add(e["label"])
        floor_targets = sorted(actor_labels)
        notes.append(f"scope resolved from selection: "
                     f"{len(stand_labels)} stand(s), {len(actor_labels)} actor(s)")
    elif scope != "all":
        label = scope
        if label in _state.foliage_stands or label in _editor_stand_labels():
            stand_labels, actor_labels = {label}, set()
            floor_targets = []
        elif _ue.find_by_label(label) is not None:
            stand_labels, actor_labels = set(), {label}
            floor_targets = [label]
        else:
            return {"error": f"scope '{label}' is neither a foliage stand nor an actor "
                             f"label in this level",
                    "known_stands": sorted(set(_state.foliage_stands)
                                           | _editor_stand_labels()),
                    "next": "validate op=run scope=all — or outliner op=list to find "
                            "the label"}

    # layer 1 — the spatial floor (actors only; a stand is a substrate, not an actor)
    if floor_targets is None:
        fl = run_validate(scene_wide=True, verbose=True)
    elif floor_targets:
        fl = run_validate(floor_targets, verbose=True)
    else:
        fl = None
        notes.append("spatial floor: n/a — scope is a foliage stand (substrate; "
                     "ground/penetration/z-fight don't apply)")
    floor = _floor_findings(fl) if fl else []
    if fl:
        notes.append(fl["line"])

    # layer 2 — the SPEC-07 rule table at firing point 3
    rule_f, rule_notes, asset_paths, (swept, total_subj) = rulesmod.sweep(
        stand_labels, actor_labels, deadline)
    notes += rule_notes

    # layer 3 — the engine's own validators (G41: never console MAP CHECK)
    eng_f, eng_notes, checked, total_assets = _engine_findings(asset_paths, deadline)
    notes += eng_notes

    findings = ([f for f in rule_f if f["severity"] == "breaks"]
                + [f for f in rule_f if f["severity"] == "degrades"]
                + floor + eng_f)
    for i, f in enumerate(findings, 1):
        f["n"] = f"F{i}"
    n_breaks = sum(1 for f in findings if f["severity"] == "breaks")
    n_eng = sum(1 for f in findings if f["severity"] == "engine")
    n_degr = len(findings) - n_breaks - n_eng
    summary = ("clean" if not findings else
               f"{len(findings)} finding(s) — {n_breaks} breaks, {n_degr} degrades, "
               f"{n_eng} engine")
    return {"lint": {
        "scope": scope, "summary": summary, "findings": findings, "notes": notes,
        "coverage": {"subjects": f"{swept}/{total_subj}",
                     "engine_assets": f"{checked}/{total_assets}",
                     "seconds": round(time.monotonic() - t0, 1)}}}


# ── the agent verb (routed from verbs._v_validate) ─────────────────────────────

def handle(p):
    op = p.get("op", "run")
    if op == "run":
        if p.get("scope"):
            return lint(p)       # SPEC-08: the three-layer sweep
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
