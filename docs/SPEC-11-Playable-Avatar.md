# SPEC-11 — `playtest`: drop the user into the level to inspect it

Status: **DESIGN** (2026-07-05). Audience: the agent implementing the verb. Every engine
claim below is spike-proven over the RC bridge (traces at bottom) unless marked
**SPIKE-CHECK** — those you verify live before relying on them.

## The ask (user, 2026-07-05)

A **debug / inspection** tool, not a shipped gameplay feature. The LLM calls it **once** and
the user is standing inside the level they just generated, walking around to inspect it.
Stock UE5 mannequin, **first- OR third-person** at the user's choice; the third-person view
is an over-the-shoulder follow camera **zoomed out enough to see the feet touching the
ground**. Fewest possible MCP calls — ideally the one call also drops them straight into
Play.

Success = **one** `playtest op=enter` call and the user is walking the scene; **one**
`playtest op=exit` and Play stops and the throwaway avatar is gone, level untouched.

## The one decisive engine fact that shapes everything

**UE 5.8 Python cannot read or edit a Blueprint's internals** — `parent_class` and
`simple_construction_script` are not exposed on the `Blueprint` object (proven: both raise
"Failed to find property"). So the camera boom that lives *inside* the character Blueprint
is **not tunable through the asset.** The GameMode-spawns-a-pawn path gives us a character
we cannot frame.

But a **spawned instance** of that Blueprint has every SCS component instanced and mutable.
On an instance we can read/set the SpringArm's `target_arm_length`, activate the
first- vs third-person camera, and set `auto_possess_player` (all proven).

→ **The avatar is a placed, auto-possessed character *instance*, spawned for the session
and destroyed on exit.** This is the whole design, and it matches "plop down a throwaway
avatar and drop me in."

## Decisions already made (do not relitigate)

- **Verb = `playtest`** (user's call, 2026-07-05). It names the intent — a developer walking
  their own build to inspect it, not a gameplay feature. Its own verb (not `add what=…` or a
  `play` op): `play` owns *runtime PIE control* (census/start/stop/where) over an
  already-playable level; `playtest` is the *editor-time setup + drop-in* that makes an
  arbitrary generated scene walkable in one shot. They're adjacent — the docstrings
  cross-reference — but distinct.
- **The avatar is transient debug scaffolding, not a saved level fixture.** `enter` spawns
  it; `exit` destroys it. It is ueb-tagged so `outliner op=reconcile` / `level op=clear`
  sweep a leftover, and `describe`/the status block warn if a playtest avatar is still
  present (so it never gets saved into the user's level by accident).
- **One call drops the user in.** `enter` spawns + tunes + auto-possesses **and** begins
  Play in a single dispatch (spawn-then-`begin_play` in one dispatch is proven). `exit` ends
  Play and removes the avatar — and, like `play op=stop`, is allowed *during* Play because
  it owns ending its own session ([[always-allowed-to-stop-pie]]).
- **First- and third-person are both first-class** via `view=`. The stock character carries
  BOTH a `Camera_FP` (CineCamera) and a `SpringArm`+`Camera_TP` (proven). `view=third`
  (default) tunes the boom for the feet-on-ground framing; `view=first` activates the head
  camera (no boom, no feet — that's the eyes view).
- **Mechanism = placed auto-possessed instance** (forced by the BP-not-editable fact). No
  GameMode override in the primary path (SPIKE-CHECK 1 gates a fallback).
- **"Stock UE5 character" = the mannequin the project actually has.** There is no
  `/Game/ThirdPerson/...` template here and `/Engine` ships no third-person character
  (proven). The project's kit rode in on a marketplace pack:
  `/Game/GV_FreeShrubsPack/Demo/ThirdPersonCharacter` (full Manny + anim BP + control rigs,
  FP and TP cameras). We adopt it and **discover it by shape, not by hard path** (see
  Character source), so a pack rename doesn't silently break the verb.
- **Perception stays numbers-only.** The agent never looks at the framing. Whether the feet
  read as "touching the ground" is the **user's** visual call ([[no-llm-vision-view-removed]])
  — the verb exposes the camera knobs (`arm`, framing offset) and reports them; the human
  tunes to taste while inside the playtest.

## Verb contract

### MCP tool (`server/main.py`)

Thin projection over `call_ue`, `pcg` tool as the template:

```python
@mcp.tool()
def playtest(op: Literal["enter", "exit", "describe"] = "enter",
             view: Literal["third", "first"] = "third",
             place: dict = None, yaw: float = None, facing: str = None,
             arm: float = None, force: bool = False) -> str:
    """DEBUG drop-in — stand the user inside the level they just built to inspect it. NOT a
    shipped gameplay feature: a throwaway stock mannequin, possessed, dropped into Play in
    ONE call, and removed on exit.

    op=enter (default): plop an auto-possessed stock character at the drop-in point (the
      level's PlayerStart if it has one, else a ground-traced origin), select the camera per
      view=, and BEGIN Play. The user is now walking the scene. Idempotent per session.
    op=exit: end Play and destroy the debug avatar (allowed during Play — it owns ending its
      own session). Leaves the level exactly as it was.
    op=describe: read-only — is a playtest live, which view, where the drop-in point is, and
      whether a stray avatar is still placed.

    view=third (default): over-the-shoulder SpringArm zoomed out (arm=, default 500cm) so the
      feet-on-ground contact is in frame. view=first: eyes-level first-person camera (no boom).
    place/yaw/facing: the add-verb placement vocabulary for the drop-in point + facing.
    arm: SpringArm length in cm — the third-person zoom-out lever ("see the feet").
    force: spawn/enter anyway past a soft guard (e.g. a playtest already live).
    """
    p = {"op": op, "view": view, "place": place or {}}
    if yaw is not None: p["yaw"] = yaw
    if facing is not None: p["facing"] = facing
    if arm is not None: p["arm"] = arm
    if force: p["force"] = True
    return render(call_ue("playtest", p, timeout=120))
```

Also update: `server/_instructions.py` (verb count 15 → 16; add `playtest` to the list, note
it owns the drop-in-to-inspect affordance while `play` owns runtime PIE) and the README verb
table.

### Ops

| op | params | effect |
|---|---|---|
| `enter` | `view=`, `place=?`, `yaw=?`, `facing=?`, `arm=?` | spawn grounded auto-possessed stock character at the drop-in point, activate the FP or TP camera (tune the TP boom), begin Play, return the drop-in census |
| `exit` | — | end Play, destroy the avatar, unregister; level untouched |
| `describe` | — | read-only: playtest live? which view? drop-in xyz? stray avatar present? |

Build order: `enter` + `exit` first; `describe` in the same PR (cheap, and it's the "did I
leave an avatar behind" safety read).

### Errors (each carries the next legal move — the vision law)

- **No stock character found** in the project → error naming what was searched (a
  `Character`-derived BP with a SpringArm+Camera) and the two fixes: add the Engine "Third
  Person" feature content, or point `playtest` at a known BP. The most likely fresh-project
  failure.
- **A playtest is already live / an avatar is already placed** → soft guard: report it and
  offer `playtest op=exit` (clean up) or `force=True` (re-enter). Never silently stack two.
- bad `place=`/`facing=` reference → the same reference-lookup errors `add` already raises
  (reuse the shared placement tail).

## Runtime implementation (`runtime/ue_buttons/playtest.py`, new module)

Mirror `pcg.py`'s shape: `handle(p)` dispatching on `p["op"]`, returning a plain dict. Wire
into `verbs.py`:

- `from . import playtest as playtestmod`; add `"playtest": _v_playtest` to `_VERBS`.
- `playtest` is **not** a persistent SPATIAL fixture, but its avatar must be sweepable.
  Simplest: keep a light session record in `_state` (below), ueb-tag the avatar so
  `outliner op=reconcile` and `level op=clear` already catch a leftover, and let `enter`/
  `exit`/`describe` bypass the normal mutating-verb status block (editor reads are refused
  during Play anyway, B8). Do **not** add `playtest` to `SPATIAL` — its lifecycle is the
  session, not the level.
- `exit` must be callable during Play (whitelist it alongside `play` in the B8 refusal
  gate — it's the counterpart to `play op=stop`).

### `op=enter` algorithm

1. **Guard.** If `_state.playtest` shows a live session or a placed avatar and not `force`,
   return the soft-guard error with the `exit`/`force` affordances.
2. **Resolve the drop-in point.** `place=` if given (add placement vocabulary), else the
   level's existing `PlayerStart` location if one exists, else a downward ground trace at
   origin. Do **not** create or relocate a PlayerStart — the debug avatar is auto-possessed
   and needs none; keep the level's footprint unchanged.
3. **Resolve the character class.** `source = _find_third_person_bp()` (see Character
   source) → a `BlueprintGeneratedClass` (`load_object(None, path + "_C")`, proven). Error
   with the HATEOAS message if none.
4. **Spawn the instance grounded at the drop-in point.**
   `EditorActorSubsystem.spawn_actor_from_class(cls, loc, rot)`; seat the **capsule** on the
   traced ground the way `_add_player_start` does (Manny's capsule half-height ≈ 88 cm — read
   it off the spawned `CapsuleComponent`, don't hardcode). Label it (`"playtest_avatar"`),
   ueb-tag via `_apply_tags` / `_ue.UEB_TAG`.
5. **Select the camera** (SPIKE-CHECK 3 — confirm the activate mechanism):
   - `view="third"`: ensure `Camera_TP`/`SpringArm` is the active camera; set the SpringArm
     `target_arm_length = p.get("arm", 500.0)` (the zoom-out lever; stock default 300 is too
     tight for "see the feet") and a `socket_offset` Z framing lift (~+60 cm; exact value =
     SPIKE-CHECK 2, the user's visual call). Don't rely on spawn-time boom **pitch**:
     `use_pawn_control_rotation=True` (proven) means the controller drives pitch at runtime,
     so pitch is transient — arm length + socket Z are the durable levers.
   - `view="first"`: activate `Camera_FP`; no boom, no arm/feet framing.
   - Mechanism to force one: on the instance, `chosen_cam.set_active(True)` and deactivate the
     other `CameraComponent`; if the BP exposes a FP/TP bool it may reassert on possess, so
     verify the possessed pawn opens on the requested camera (part of SPIKE-CHECK 1's PIE
     read) and, if the BP wins, set that bool via `set_editor_property` on the instance.
6. **Auto-possess + begin Play in the same dispatch.**
   `actor.set_editor_property("auto_possess_player", unreal.AutoReceiveInput.PLAYER0)`
   (proven), then `LevelEditorSubsystem.editor_request_begin_play()` (proven to work in the
   same dispatch as the spawn). The user is now in the level.
7. **Record + return** the drop-in census (built from the pre-play reads):

```python
{"playtest": "live", "view": "third", "avatar": "playtest_avatar",
 "source": "GV_FreeShrubsPack/.../ThirdPersonCharacter",
 "drop_in": [x, y, z], "arm": 500.0, "auto_possess": "Player0",
 "next": ["playtest op=exit  (stop + remove the avatar)",
          "playtest op=enter view=third arm=<cm>  (re-drop, re-tune the zoom)"]}
```

### `op=exit`

`editor_request_end_play()`, then `destroy_actor` the recorded avatar (and belt-and-braces:
sweep any ueb-tagged `Character` labelled `playtest_avatar`), clear `_state.playtest`. Return
`{"playtest": "ended", "removed": True}`. If no session was live, say so — don't error.

**No GameMode override in the primary path.** A placed pawn with `AutoPossessPlayer=Player0`
possesses itself on Play; the default GameMode's `RestartPlayer` skips spawning a pawn when
the controller already has one — so no stray pawn. **SPIKE-CHECK 1** gates this: on Play,
verify `GetPlayerController(0).GetControlledPawn()` **is our instance**, pawn count is 1,
input is live, and the active camera matches `view=`. If a stray pawn appears or input is
dead, the fallback is `WorldSettings.default_game_mode = <discovered ThirdPersonGameMode>`
(proven settable) — but that reintroduces the untunable camera, so it's a last resort; log a
gap. Reading the possessed pawn is **TWO-CALL**: `get_game_world()` returns `None` in the
dispatch that starts Play (the PIE world needs an editor tick — the same async gap
[[spec10-pcg-status]]'s `play op=census` is built around). Reuse `play`'s two-call PIE-world
introspection.

### Character source (`_find_third_person_bp`)

Discover, don't hard-code the marketplace path. Search the Asset Registry for a `Blueprint`
whose generated class derives from `unreal.Character` **and** whose instance carries a
`SpringArmComponent` + `CameraComponent`. Preference order:
1. a canonical template path if present (`/Game/ThirdPerson/Blueprints/BP_ThirdPersonCharacter`);
2. the known pack character `/Game/GV_FreeShrubsPack/Demo/ThirdPersonCharacter` (current only
   source — proven present);
3. any other match (name containing "ThirdPerson"/"Character").
Cache the resolved path so repeat `enter` calls skip the scan. None → the HATEOAS error.
(Adopting the pack character couples us to that pack; a full de-fragilize would copy the whole
Mannequin tree into `/Game/UEB_Play/`, heavy and out of scope for v1 — discovery + a clear
error is the pragmatic floor. Log the coupling as an open item.)

### Session state (`_state.py`)

```python
playtest = None   # or {"avatar": label, "view", "drop_in", "arm", "source", "playing": bool}
```

`_state` is never hot-reloaded — guard every access with `hasattr`/`getattr(_state,
"playtest", None)`, same pattern as `_state.follow`. `outliner op=reconcile` and `level
op=clear` already sweep the ueb-tagged avatar; also clear `_state.playtest` when the avatar
is gone so `describe` never claims a phantom session.

## Invariants

1. **Tune the instance, never the Blueprint** — BP internals aren't Python-writable (proven);
   the camera lives on the spawned actor's components.
2. **Auto-possess the placed pawn** — it's what makes Play use our tuned camera and what
   suppresses the GameMode's stray pawn (SPIKE-CHECK 1).
3. **Seat the capsule on the ground**, not the AABB — the sprite/arrow/mesh bounds float the
   capsule otherwise (the exact bug `_add_player_start` fixes, G55). Reuse that reseat.
4. **Arm length is the third-person zoom lever; socket Z is the framing bias** — not
   spawn-pitch (transient under `use_pawn_control_rotation`). First-person ignores both.
5. **The avatar is transient** — `exit` removes it; a saved level must never carry a
   `playtest_avatar` (describe/status warn if one lingers).
6. **`exit` works during Play** — it's the counterpart to `play op=stop`.

## Verification plan (live, over the MCP tools, before commit)

1. `playtest op=enter view=third` on a fresh generated scene (e.g. a `pcg` forest): returns
   `playtest: live`, drop-in point sane, avatar ueb-tagged.
2. **SPIKE-CHECK 1** (two-call PIE read): exactly one pawn, possessed by Player0, it is our
   instance, it opens on the TP camera, WASD moves it (the human confirms movement).
3. **The user's visual acceptance** (no-vision policy hands this to the human): in the live
   playtest, confirm the over-the-shoulder camera shows the mannequin's feet on the ground.
   Re-`enter` with `arm=<cm>` until right; record the chosen arm + socket Z as the defaults
   in this spec (**SPIKE-CHECK 2**).
4. `playtest op=enter view=first`: first-person head camera active, no boom (SPIKE-CHECK 3 —
   the camera-select mechanism holds through possess).
5. `playtest op=exit`: Play ends, avatar gone, `_state.playtest` cleared; the level has no
   leftover character. Re-enter works.
6. `describe`: reports live/idle correctly; warns if an avatar lingers (simulate by killing
   Play out-of-band and confirming reconcile + describe agree).
7. `outliner op=reconcile` / `level op=clear` sweep a leftover avatar and clear the session.
8. Failures found on the way become numbered gaps in `gaps.md` (fix → live-verify → prune).

## Open items

- **Full character-source de-fragilize** (copy the Mannequin tree into `/Game/UEB_Play/`) —
  deferred; discovery + clear error is the v1 floor.
- **"Stock UE5 character" reality**: this project's only third-person character is the
  mannequin bundled in `GV_FreeShrubsPack/Demo/`; no Epic Third Person template is installed.
  The verb adopts and discovers it. Adding the Engine "Third Person" feature content makes
  `playtest` prefer the canonical mannequin automatically.

## Ground truth — spike traces (2026-07-05, all over the RC bridge)

Level at probe time: `UEB_PCGMeadow` then `UEB_PCGForest` (a parallel session switched it);
`WorldSettings.default_game_mode` = `None`; one `player_start` already present.

1. **Character hunt.** No `/Game/ThirdPerson/...` and no `/Engine` third-person character
   (`does_asset_exist` false; engine search empty). Found a full kit under
   `/Game/GV_FreeShrubsPack/Demo/`: `ThirdPersonCharacter` (Blueprint), `ThirdPersonGameMode`
   (Blueprint), `SKM_Manny`, `ABP_Manny`, `SK_Mannequin`, `CR_Mannequin_*` control rigs.
2. **GameMode override is live** (fallback path only). `WorldSettings.default_game_mode` reads
   (`None`) and is settable; `ThirdPersonGameMode_C` loads, its `default_pawn_class` **is**
   `ThirdPersonCharacter_C`.
3. **BP internals are opaque to Python.** `Blueprint.get_editor_property("parent_class")` and
   `("simple_construction_script")` both raise "Failed to find property" — the camera boom
   can't be edited through the asset. (Decisive: forces the instance path.)
4. **Instance components (spawned `ThirdPersonCharacter_C`):** `CollisionCylinder` (Capsule),
   `Arrow`, `CharacterMesh0` (SkeletalMesh), **`Camera_FP` (CineCamera)**, `SpringArm`
   (SpringArmComponent), **`Camera_TP` (CameraComponent)**, plus a SpotLight and camera
   proxy/frustum helpers. So BOTH first- and third-person cameras exist on one character.
   SpringArm defaults: `target_arm_length=300`, `socket_offset=(0,0,0)`,
   `relative_rotation=(0,0,0)`, `use_pawn_control_rotation=True`.
5. **Instance is tunable.** `target_arm_length` 300 → 650 (read back 650); `relative_rotation`
   set; `auto_possess_player = AutoReceiveInput.PLAYER0` set + read back.
   `spawn_actor_from_class` / `destroy_actor` / `editor_request_begin_play` /
   `editor_request_end_play` all work; spawn-then-begin_play in one dispatch works.
6. **PIE-world async gap** (confirms SPIKE-CHECK 1 is two-call): `get_game_world()` returns
   `None` in the same dispatch that starts Play — the PIE world needs an editor tick, same
   reason `play op=census` is two-call. All spike actors were destroyed and Play ended; no
   test state saved to the user's level.
