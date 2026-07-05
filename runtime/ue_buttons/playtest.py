"""`playtest` — drop the user into the level they just built, to INSPECT it (SPEC-11).

DEBUG tool FOR THE USER, not a shipped gameplay feature. The LLM calls it and the user is
standing inside the generated scene, walking around to inspect it. `op=enter` spawns a
throwaway auto-possessed stock mannequin at a grounded drop-in point and BEGINS Play; the
user is walking immediately. `op=exit` ends Play and destroys the avatar, leaving the level
exactly as it was. Perception here is the HUMAN's — whether the feet read as "touching the
ground" is the user's visual call; the agent has no screenshot verb and never judges it.

THE DECISIVE FACTS (spike-proven over RC, SPEC-11 + build-time verification 2026-07-05):
  1. UE 5.8 Python cannot edit a Blueprint's internals, so the camera boom inside the BP is
     untunable through the asset — the avatar must be a spawned INSTANCE.
  2. BUT tuning the editor instance's SpringArm does NOT survive PIE: begin_play re-runs the
     BP construction and the arm reverts to the BP default (300). The tuning that STICKS is
     on the LIVE PIE pawn, which exists only AFTER PIE ticks. So enter is TWO-CALL, exactly
     like `play op=census`: call 1 spawns + possesses + begins Play (user is walking on the
     BP-default framing); call 2 (in PIE) applies the zoom, selects the camera, and clears
     the GameMode's stray pawn. Retuning the zoom later is another call-2 (live, no restart).
  3. The default GameMode spawns its OWN pawn at Play — our auto-possessed avatar wins the
     controller, orphaning the GameMode's, so PIE carries a stray unpossessed doppelganger.
     Call 2 destroys it in the game world.
  4. Ending Play cannot reliably destroy the editor-world avatar in the same dispatch, so
     exit queries editor_world() explicitly (valid during PIE) to sweep the real avatar.

NOT a SPATIAL fixture: its lifecycle is the SESSION, not the level. It is ueb-tagged so
`outliner op=reconcile` / `level op=clear` sweep a leftover, and `describe` warns if one
lingers so it never gets saved into the user's level by accident.
"""
import unreal

from . import _state
from . import _ue
from . import relational

_AVATAR_LABEL = "playtest_avatar"
_DEFAULT_ARM = 500.0        # TP zoom-out to see the feet (stock default 300 is too tight)
_GROUND_SEAT = 0.5          # G21: seat the capsule this hair above the trace (validate.GROUND_SEAT)

# Character-source discovery (SPEC-11): prefer a canonical Epic template, then the known
# pack character, then any Character-derived BP. Resolved path is cached in _state.
_CANON = "/Game/ThirdPerson/Blueprints/BP_ThirdPersonCharacter"
_KNOWN = "/Game/GV_FreeShrubsPack/Demo/ThirdPersonCharacter"


# ── session record (never-reloaded _state — guard every access, same as _state.follow) ──
def _rec():
    return getattr(_state, "playtest", None)


def _set_rec(v):
    _state.playtest = v


def _les():
    return unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)


# ── dispatch ────────────────────────────────────────────────────────────────────────
def handle(p):
    fn = {"enter": _enter, "exit": _exit, "describe": _describe}.get(p.get("op", "enter"))
    if fn is None:
        return {"error": f"unknown playtest op '{p.get('op')}'. known: enter|exit|describe"}
    return fn(p)


# ── character source ──────────────────────────────────────────────────────────────────
def _no_character_error():
    """HATEOAS: no stock character found — name what was searched + the two fixes. The most
    likely fresh-project failure (a project with no Third Person feature content)."""
    return {"error": "no stock character found to play — playtest needs a Character-derived "
                     "Blueprint carrying a SpringArm + Camera (the UE Third Person mannequin).",
            "searched": [f"{_CANON} (Epic template)", f"{_KNOWN} (pack character)",
                         "any Character-derived Blueprint under /Game"],
            "next": ["add the Engine 'Third Person' feature content (Content Browser > Add "
                     "Feature), then playtest op=enter",
                     "or install a marketplace character pack that ships a third-person BP"]}


def _find_third_person_bp():
    """Resolve a stock third-person character BP path by SHAPE, not a hard path (SPEC-11):
    canonical template -> known pack character -> any Character-derived /Game Blueprint
    (name-hinted first). Caches the resolved path so repeat enters skip the scan. Returns
    (path, None) or (None, error-dict)."""
    cached = getattr(_state, "playtest_source", None)
    if cached and unreal.EditorAssetLibrary.does_asset_exist(cached):
        return cached, None
    for path in (_CANON, _KNOWN):
        if unreal.EditorAssetLibrary.does_asset_exist(path):
            _state.playtest_source = path
            return path, None
    ar = unreal.AssetRegistryHelpers.get_asset_registry()
    assets = ar.get_assets_by_class(
        unreal.TopLevelAssetPath("/Script/Engine", "Blueprint"), True)
    matches = []
    for a in assets:
        if "Character" not in str(a.get_tag_value("ParentClass") or ""):
            continue
        pkg = str(a.package_name)
        if pkg.startswith("/Engine/"):
            continue     # engine tutorial/sample characters — not a game-ready mannequin
        hinted = "ThirdPerson" in str(a.asset_name) or "Character" in str(a.asset_name)
        matches.append((not hinted, pkg))     # name-hinted sorts first
    matches.sort()
    if matches:
        _state.playtest_source = matches[0][1]
        return matches[0][1], None
    return None, _no_character_error()


# ── camera + placement helpers ────────────────────────────────────────────────────────
def _classify_cams(pawn):
    """FP = a camera NOT parented to a SpringArm (the head camera); TP = the camera on the
    SpringArm boom. By shape, so a discovered non-pack character still classifies. Returns
    (fp, tp, springarm)."""
    cams = list(pawn.get_components_by_class(unreal.CameraComponent))
    arms = list(pawn.get_components_by_class(unreal.SpringArmComponent))
    arm_names = {a.get_name() for a in arms}
    fp = tp = None
    for c in cams:
        parent = c.get_attach_parent()
        if parent is not None and parent.get_name() in arm_names:
            tp = tp or c
        else:
            fp = fp or c
    return fp, tp, (arms[0] if arms else None)


def _level_player_start():
    w = _ue.editor_world()
    starts = list(unreal.GameplayStatics.get_all_actors_of_class(w, unreal.PlayerStart))
    return starts[0] if starts else None


def _drop_in(p, actor, cap):
    """Resolve the XY drop-in point (place= vocabulary -> level PlayerStart -> origin) and
    seat the capsule bottom on the traced ground. Feet on the ground is always the goal, so
    the trace owns Z — never the AABB (which the camera/arrow components inflate, G55). The
    Character's root IS the capsule, so actor.z = ground + capsule_half + seat. Returns the
    [x, y, z] capsule centre."""
    yaw = p.get("yaw")
    facing = p.get("facing")
    place = p.get("place") or {}
    if facing is not None:
        try:
            from . import verbs      # deferred: verbs imports this module (avoid a cycle)
            yaw = verbs._facing_yaw(place, facing)
        except Exception:
            pass
    if yaw is not None:
        actor.set_actor_rotation(unreal.Rotator(yaw=float(yaw), pitch=0.0, roll=0.0), False)

    tx = ty = None
    if place:
        try:
            tgt = relational.resolve_placement(actor, place)
            tx, ty = tgt[0], tgt[1]
        except Exception:
            tx = ty = None
    if tx is None:
        ps = _level_player_start()
        if ps is not None:
            loc = ps.get_actor_location()
            tx, ty = loc.x, loc.y
    if tx is None:
        tx, ty = 0.0, 0.0

    gz = _ue.trace_ground(tx, ty, ignore=actor)
    half = cap.get_scaled_capsule_half_height()
    z = (gz + half + _GROUND_SEAT) if gz is not None else 200.0
    actor.set_actor_location(unreal.Vector(tx, ty, z), False, False)
    return [tx, ty, z]


# ── ops ───────────────────────────────────────────────────────────────────────────────
def _enter(p):
    """TWO-CALL (finding 2). In PIE with a session -> phase 2: tune the live pawn + clear the
    stray. In the editor -> phase 1: spawn, ground, auto-possess, begin Play."""
    rec = _rec()
    in_pie = _les().is_in_play_in_editor()

    if in_pie:
        if rec is None:
            return {"error": "the editor is already in Play but not a playtest — play op=stop "
                             "first, then playtest op=enter."}
        # phase 2 / retune — pull any new view/arm from this call, then apply to the live pawn
        if p.get("view") in ("third", "first"):
            rec["view"] = p["view"]
        if p.get("arm") is not None:
            rec["arm"] = float(p["arm"])
        return _frame_live(rec)

    # ── phase 1 (editor world) ──
    force = bool(p.get("force"))
    live = _ue.find_by_label(_AVATAR_LABEL)
    if (rec or live is not None) and not force:
        return {"error": "a playtest avatar is already placed — never stack two.",
                "avatar": _AVATAR_LABEL, "session": bool(rec),
                "next": ["playtest op=exit   (stop Play + remove the avatar)",
                         "playtest op=enter force=True   (re-drop + re-tune)"]}
    if force and live is not None:
        _ue.actor_subsystem().destroy_actor(live)   # a stray from a killed session
        _set_rec(None)

    view = p.get("view", "third")
    if view not in ("third", "first"):
        return {"error": f"unknown view '{view}'. known: third|first"}

    src, err = _find_third_person_bp()
    if err:
        return err
    cls = unreal.EditorAssetLibrary.load_blueprint_class(src)
    if cls is None:
        return {"error": f"the character BP '{src}' would not load a spawnable class",
                "next": ["point playtest at a valid Character-derived BP"]}

    eas = _ue.actor_subsystem()
    actor = eas.spawn_actor_from_class(cls, unreal.Vector(0.0, 0.0, 100000.0))
    if actor is None:
        return {"error": f"could not spawn a character from '{src}'"}
    actor.set_actor_label(_AVATAR_LABEL)
    actor.tags = [unreal.Name(_ue.UEB_TAG)]     # sweepable by reconcile / level clear (G7)

    cap = actor.get_component_by_class(unreal.CapsuleComponent)
    if cap is None or not actor.get_components_by_class(unreal.CameraComponent):
        eas.destroy_actor(actor)
        return {"error": f"'{src}' is not a usable playtest character (needs a Capsule + a "
                         "Camera).", "next": ["point playtest at the stock mannequin BP"]}

    drop = _drop_in(p, actor, cap)
    arm = float(p.get("arm", _DEFAULT_ARM))

    # auto-possess the placed pawn + begin Play IN THIS DISPATCH (both proven). A pawn with
    # AutoPossessPlayer=Player0 possesses itself; the GameMode's own pawn is orphaned and
    # gets swept in phase 2. NO camera/arm tuning here — it wouldn't survive the construction
    # re-run (finding 2); it's applied to the live pawn in phase 2.
    actor.set_editor_property("auto_possess_player", unreal.AutoReceiveInput.PLAYER0)
    _set_rec({"avatar": _AVATAR_LABEL, "view": view, "drop_in": drop, "source": src,
              "arm": arm, "pending": True, "playing": True})
    _les().editor_request_begin_play()

    return {"playtest": "entering", "view": view, "avatar": _AVATAR_LABEL, "source": src,
            "drop_in": [round(v, 1) for v in drop], "arm": arm, "auto_possess": "Player0",
            "note": ("You're being dropped in — PIE spins up asynchronously (a single call "
                     "can't force the tick). Call playtest op=enter AGAIN in ~2 s to finish: "
                     "it applies the zoom, selects the camera, and clears the GameMode's "
                     "stray pawn. The user is already walking on the default framing."),
            "next": [f"playtest op=enter   (again, ~2 s — finishes framing at arm={arm:g})",
                     "playtest op=exit   (stop Play + remove the avatar)"]}


def _frame_live(rec):
    """Phase 2 (in PIE): tune the possessed pawn (finding 2) and destroy the GameMode's stray
    pawn (finding 3). Re-runnable to retune the zoom live without a Play restart. If PIE isn't
    fully live yet (world/pawn not resolvable), return the 'call again' stub."""
    gw = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
    if gw is None:
        return _framing_stub(rec, "PIE isn't live yet")
    pc = unreal.GameplayStatics.get_player_controller(gw, 0)
    pawn = pc.get_controlled_pawn() if pc else None
    if pawn is None:
        return _framing_stub(rec, "the pawn isn't possessed yet")

    view, arm = rec["view"], rec["arm"]
    fp, tp, sa = _classify_cams(pawn)
    chosen = tp if view == "third" else fp
    for c in (fp, tp):
        if c is not None:
            try:
                c.set_active(c is chosen)
            except Exception:
                pass
    if view == "third" and sa is not None:
        sa.set_editor_property("target_arm_length", arm)

    # sweep the GameMode's orphaned pawn(s) — anything possessing nobody but our avatar
    strays = 0
    for pw in unreal.GameplayStatics.get_all_actors_of_class(gw, unreal.Pawn):
        if pw is not pawn:
            try:
                pw.destroy_actor()
                strays += 1
            except Exception:
                pass

    rec["pending"] = False
    remaining = len(list(unreal.GameplayStatics.get_all_actors_of_class(gw, unreal.Pawn)))
    out = {"playtest": "live", "view": view, "avatar": _AVATAR_LABEL,
           "source": rec.get("source"), "drop_in": rec.get("drop_in"),
           "possessed": pawn.get_actor_label(), "pawn_count": remaining,
           "strays_removed": strays, "camera": chosen.get_name() if chosen else None,
           "next": ["playtest op=exit   (stop Play + remove the avatar)",
                    "playtest op=enter arm=<cm>   (retune the zoom, live — no restart)",
                    "playtest op=enter view=first   (switch to first-person, live)"]}
    if view == "third":
        out["arm"] = arm
        out["framing_note"] = ("over-the-shoulder at arm=%g cm — YOUR call whether the feet "
                               "read as on the ground; ask for more/less and I re-enter with "
                               "a new arm= (live, no restart). Pitch the view down with the "
                               "mouse to bring the feet into frame." % arm)
    else:
        out["framing_note"] = "first-person head camera — no boom, no feet (the eyes view)."
    return out


def _framing_stub(rec, why):
    return {"playtest": "entering", "view": rec["view"], "avatar": _AVATAR_LABEL,
            "note": f"{why} (PIE advances on the editor's tick, which a blocking call can't "
                    "force) — call playtest op=enter again in ~2 s to finish framing.",
            "next": ["playtest op=enter   (again, ~2 s)", "playtest op=exit"]}


def _sweep_editor_avatar():
    """Destroy the ueb-tagged playtest avatar(s) in the editor. ONLY reliable once Play has
    fully ended (finding 4): during PIE the editor avatar is unreachable by every method
    tried — active-world enumeration returns PIE actors, get_editor_world() enumeration
    returns [] for it, and a direct stored reference no-ops. So exit removes it in a second
    dispatch, back in the editor. Returns the count removed."""
    removed = 0
    for a in list(_ue.all_actors()):
        try:
            if a.get_actor_label() == _AVATAR_LABEL \
                    and _ue.UEB_TAG in [str(t) for t in a.tags]:
                _ue.actor_subsystem().destroy_actor(a)
                removed += 1
        except Exception:
            pass
    return removed


def _exit(p):
    """End Play + remove the debug avatar. TWO-CALL when Play is running (finding 4): the
    editor avatar is unreachable until Play has fully ended, and end_play is async — so call 1
    (in PIE) ends Play and call 2 (back in the editor) sweeps the avatar. The counterpart to
    play op=stop; the user is OUT of Play after call 1. If nothing was live, say so."""
    rec = _rec()
    if _les().is_in_play_in_editor():
        _les().editor_request_end_play()
        if rec is not None:
            rec["playing"] = False
        return {"playtest": "stopping", "removed": False, "stopped_play": True,
                "note": ("Play is ending — the editor world restores on the next tick, so the "
                         "avatar can't be removed in this same call (PIE is async). Call "
                         "playtest op=exit AGAIN in ~1 s to remove the debug avatar."),
                "next": ["playtest op=exit   (again, ~1 s — removes the avatar)"]}
    removed = _sweep_editor_avatar()
    had = rec is not None
    _set_rec(None)
    if not (removed or had):
        return {"playtest": "idle", "removed": False,
                "note": "no playtest was live — nothing to end."}
    return {"playtest": "ended", "removed": removed > 0, "stopped_play": False,
            "note": "Debug avatar removed; the level is untouched."}


def _describe(p):
    """Read-only: is a playtest live, which view, where the drop-in is, and — the safety
    read — whether a stray avatar is still placed (so it never gets saved into the level)."""
    rec = _rec()
    live = _ue.find_by_label(_AVATAR_LABEL)
    playing = _les().is_in_play_in_editor()
    out = {"playtest": "live" if rec else "idle", "avatar_present": live is not None,
           "in_play": playing}
    if rec:
        out.update({"view": rec.get("view"), "drop_in": rec.get("drop_in"),
                    "arm": rec.get("arm"), "source": rec.get("source"),
                    "pending_framing": bool(rec.get("pending"))})
    if live is not None and rec is None:
        out["warning"] = (f"a '{_AVATAR_LABEL}' actor is placed but no playtest session is "
                          "recorded (Play was likely killed out-of-band) — it must NOT be "
                          "saved into the level.")
        out["next"] = ["playtest op=exit   (remove the stray avatar)"]
    elif live is not None:
        out["next"] = ["playtest op=exit   (stop + remove the avatar)"]
    else:
        out["next"] = ["playtest op=enter view=third   (drop in to inspect the level)"]
    return out
