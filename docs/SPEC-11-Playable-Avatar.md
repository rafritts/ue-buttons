# SPEC-11 — `avatar`: drop a playable third-person character into a scene

Status: **DESIGN** (2026-07-05). Audience: the agent implementing the verb. Every engine
claim below is spike-proven over the RC bridge (traces at bottom) unless marked
**SPIKE-CHECK** — those you verify live before relying on them.

## The ask (user, 2026-07-05)

"A playable avatar the user can drop into a scene to explore anything the MCP server
generated. Third-person over-the-shoulder camera, **zoomed out enough to see the feet
touching the ground**. Two things: place a **player-start**, and plop down the **stock UE5
character**. Ideally **as few MCP calls as possible.**"

Success = **one** ue-buttons call makes any level walkable, then the human presses Play (or
`play op=start`) and explores with a follow camera that shows the character head-to-toe on
the ground.

## The one decisive engine fact that shapes everything

**UE 5.8 Python cannot read or edit a Blueprint's internals** — `parent_class` and
`simple_construction_script` are not exposed on the `Blueprint` object (proven: both raise
"Failed to find property"). So the camera boom that lives *inside* the character Blueprint
is **not tunable through the asset.** The GameMode-spawns-a-pawn path therefore gives us a
character we cannot frame.

But a **spawned instance** of that Blueprint has every SCS component instanced and
mutable. On an instance we can read and set the SpringArm's `target_arm_length`, its
`socket_offset`/`relative_rotation`, and the actor's `auto_possess_player` (all proven).

→ **The avatar is a placed, auto-possessed character *instance*, not a GameMode pawn.**
This is the whole design. It also happens to match the user's words exactly: "plop down
the avatar" = spawn a visible character actor in the level, tuned, that Play possesses.

## Decisions already made (do not relitigate)

- **Verb = `avatar`** (recommended; the user owns this taste call — see "For the user"
  below). Its own verb, not `add what=avatar`: `add` spawns exactly one actor and returns
  it; `avatar op=place` is a *composite* level fixture (PlayerStart + character + camera
  tune + possession + registry entry) with its own reversible lifecycle — the same profile
  (SPATIAL, ueb-tagged, reconcile/clear/cleanup) that earned `pcg` a verb rather than a
  `foliage` op. Overloading `add`'s single-actor contract with a multi-actor composite is
  the reason to split.
- **Mechanism = placed auto-possessed instance** (forced by the BP-not-editable fact
  above). No GameMode override in the primary path (SPIKE-CHECK 1 gates a fallback).
- **One call does both halves.** `avatar op=place` ensures the PlayerStart *and* plops the
  character at the same spot — the user asked for two things and for fewest calls; the verb
  reconciles them into one dispatch.
- **"Stock UE5 character" = the mannequin the project actually has.** There is no
  `/Game/ThirdPerson/...` template here and `/Engine` ships no third-person character
  (proven). The project's third-person kit rode in on a marketplace pack:
  `/Game/GV_FreeShrubsPack/Demo/ThirdPersonCharacter` (full Manny + anim BP + control rigs,
  with a first-person AND a third-person camera). We adopt it as the avatar source and
  **discover it by shape, not by hard path** (see Character source), so a pack rename
  doesn't silently break the verb.
- **Perception stays numbers-only.** The agent never looks at the framing. Whether the feet
  read as "touching the ground" is the **user's** visual call (the no-vision policy) — the
  verb exposes the camera knobs (`arm`, and a framing offset) and reports them; the human
  tunes to taste.

## Verb contract

### MCP tool (`server/main.py`)

Follow the `pcg` tool as the template (thin projection, `call_ue`, long-ish timeout — a
spawn + ground trace is quick, but PIE-adjacent work wants headroom):

```python
@mcp.tool()
def avatar(op: Literal["place", "remove", "describe"] = "place",
           label: str = "avatar", place: dict = None, yaw: float = None,
           facing: str = None, arm: float = None, force: bool = False) -> str:
    """Drop a playable third-person character into the level so a human can walk the
    scene — the "let me explore this" button. ONE call places the PlayerStart AND plops a
    tuned, auto-possessed stock mannequin at that spot; then press Play (or play op=start).

    op=place (default): ensure the level's PlayerStart at the target (relocate-or-create,
      G35) and spawn an auto-possessed ThirdPersonCharacter instance grounded there, its
      over-the-shoulder SpringArm zoomed out (arm=, default 500cm) so the feet-on-ground
      contact is in frame. Re-running with the same label re-seats/re-tunes (idempotent).
    op=remove: destroy the character instance + unregister (the PlayerStart stays — it's a
      level marker). Full reversal of the plop.
    op=describe: is this level playable? PlayerStart location, avatar label, arm length,
      auto-possess state — read-only.

    place/yaw/facing: the add-verb placement vocabulary (where the player drops in, which
      way they face). arm: SpringArm length in cm — the zoom-out lever ("see the feet").
    """
    p = {"op": op, "label": label, "place": place or {}}
    if yaw is not None: p["yaw"] = yaw
    if facing is not None: p["facing"] = facing
    if arm is not None: p["arm"] = arm
    if force: p["force"] = True
    return render(call_ue("avatar", p, timeout=120))
```

Also update: `server/_instructions.py` (verb count 15 → 16; add `avatar` to the verb list
and the conventions blurb) and the README verb table.

### Ops

| op | params | effect |
|---|---|---|
| `place` | `place=?`, `yaw=?`, `facing=?`, `arm=?`, `label=` | ensure PlayerStart at target (reuse `_add_player_start`), spawn grounded auto-possessed ThirdPersonCharacter instance, tune its TP SpringArm, ueb-tag + register, return playable state |
| `remove` | `label=` | destroy the character actor + unregister; PlayerStart survives |
| `describe` | `label=?` (omit → the level's avatar) | read-only playability census: PlayerStart xyz, avatar xyz, arm, auto-possess, source BP |

Build order: `place` + `remove` first; `describe` in the same PR if cheap.

### Errors (each carries the next legal move — the vision law)

- **No third-person character found** in the project → error naming what was searched (a
  `Character`-derived BP with a SpringArm+Camera) and the two fixes: add the Engine "Third
  Person" feature content, or point `avatar` at a known BP. This is the one failure the
  user is most likely to hit on a fresh project.
- unknown `facing=` spline / bad `place=` reference → same reference-lookup errors `add`
  already raises (reuse the shared placement tail).
- duplicate `label=` that isn't our own avatar → error (labels unique across ueb actors);
  re-running against *our* avatar label is a legal re-tune, not a collision (mirror
  `_add_player_start`'s relocate-or-create guard).

## Runtime implementation (`runtime/ue_buttons/avatar.py`, new module)

Mirror `pcg.py`'s shape: a `handle(p)` dispatching on `p["op"]`, returning a plain dict.
Wire into `verbs.py`:

- `from . import avatar as avatarmod`; add `"avatar": _v_avatar` to `_VERBS`.
- Add `"avatar"` to the **`SPATIAL`** set (`verbs.py:42`, currently
  `{"terrain","spline","foliage","pcg"}`) — same lifecycle class: status block yes,
  history/transaction handled like the others, `undoable` per the SPATIAL default, teardown
  is its own `remove` + the `level op=clear` ueb-tag sweep. `_focus_label` already routes
  SPATIAL via `result["label"]`, so every mutating result must carry `label`.

### `op=place` algorithm

1. **Ensure the PlayerStart.** Call the existing `_add_player_start(p, label="player_start",
   place, snap, yaw, facing, under_cover, tags)` path (relocate-or-create, capsule seated on
   the traced ground, ueb-tagged — all already built for `add what=player_start`, G35).
   Reuse it verbatim; do not re-implement grounding. The avatar and the PlayerStart share
   the resolved spawn point.
2. **Resolve the character class.** `source = _find_third_person_bp()` (see Character
   source) → a `BlueprintGeneratedClass` (`load_object(None, path + "_C")`, proven). Error
   with the HATEOAS message if none.
3. **Spawn the instance grounded at the PlayerStart point.**
   `EditorActorSubsystem.spawn_actor_from_class(cls, loc, rot)`; seat the **capsule** on the
   traced ground exactly as `_add_player_start` does (Manny's capsule half-height ≈ 88 cm —
   read it off the spawned `CapsuleComponent`, don't hardcode). Label it (`label`, default
   `"avatar"`), ueb-tag via `_apply_tags` / the `_ue.UEB_TAG` append so
   outliner/feel/reconcile see it.
4. **Tune the third-person SpringArm** on the instance (proven settable):
   - `arm = spring.get_editor_property("target_arm_length")`; set to `p.get("arm", 500.0)`
     — the "zoom out to see feet" lever (stock default is 300 cm, too tight for the ask).
   - `socket_offset` Z lift (framing bias so the character sits high enough that feet + a
     patch of ground are in frame) — **SPIKE-CHECK 2** for the exact value; start ~+60 cm.
   - Do **not** rely on a fixed `relative_rotation` pitch: the boom has
     `use_pawn_control_rotation=True` (proven), so the controller's pitch drives it at
     runtime and any spawn-time pitch is transient. Arm length + socket Z are the durable
     levers; the human tilts down with the mouse for more.
   - Pick the **third-person** boom/camera specifically: this character has both `Camera_FP`
     and `SpringArm`+`Camera_TP`. Select the `SpringArmComponent` (there is one) and,
     if the character exposes a FP/TP toggle, leave it in whatever state Play starts in and
     just tune the TP boom (SPIKE-CHECK 3 — confirm Play opens on the TP camera; if it opens
     first-person, the census must say so and `describe` reports the active view).
5. **Auto-possess.** `actor.set_editor_property("auto_possess_player",
   unreal.AutoReceiveInput.PLAYER0)` (proven settable) — pressing Play possesses *this*
   tuned instance, so the camera we set is the camera the human gets.
6. **Register + return** (shape below). Record the resolved PlayerStart point, the arm, the
   source BP path.

**No GameMode override in the primary path.** A placed pawn with `AutoPossessPlayer=Player0`
possesses itself on Play; the default GameMode's `RestartPlayer` skips spawning a pawn when
the controller already has one — so there should be no stray pawn. **SPIKE-CHECK 1** gates
this: verify on Play that `GetPlayerController(0).GetControlledPawn()` **is our instance**,
pawn count is 1, and movement input is live. If a stray default pawn appears OR input is
dead, the fallback is to set `WorldSettings.default_game_mode` (proven settable) to the
discovered `ThirdPersonGameMode` and drop the placed instance — but that reintroduces the
untunable-camera problem, so treat it as a last resort and log a gap. Verifying SPIKE-CHECK 1
is TWO-CALL: `get_game_world()` returns `None` inside the dispatch that starts Play (the PIE
world isn't live until the editor ticks — the same async gap `play op=census` is built
around). Reuse `play`'s two-call PIE-world introspection to read the possessed pawn.

### Character source (`_find_third_person_bp`)

Discover, don't hard-code a marketplace path. Search the Asset Registry for a `Blueprint`
whose generated class derives from `unreal.Character` **and** whose instance carries a
`SpringArmComponent` + `CameraComponent`. Order of preference:
1. a canonical template path if present (`/Game/ThirdPerson/Blueprints/BP_ThirdPersonCharacter`);
2. the known pack character `/Game/GV_FreeShrubsPack/Demo/ThirdPersonCharacter` (current
   only source — proven present);
3. any other match, first by name containing "ThirdPerson"/"Character".
Cache the resolved path in the registry so repeat `place` calls skip the scan. If nothing
matches → the HATEOAS "no character found" error. (Adopting the pack character couples us to
that pack; a full de-fragilize would copy the whole Mannequin tree into `/Game/UEB_Play/`,
which is heavy and out of scope for v1 — discovery + a clear error is the pragmatic floor.
Log the coupling as an open item.)

### State registry (`_state.py`)

```python
avatars = {}   # {label: {source_bp, arm, player_start, actor_name, spawn_xyz}}
```

`_state` is never hot-reloaded — guard every access with
`hasattr(_state, "avatars")`-init, same pattern as `pcg_volumes`. Extend
`outliner op=reconcile` to prune `avatars` entries whose actor is gone, and confirm
`level op=clear` destroys the avatar via the ueb-tag sweep (a plain Character actor dies on
`destroy_actor` — no special pre-pass, unlike PCG's ISM volume).

### Result dicts

`place` (the SPATIAL status block renders around this; `notes` → ⚠ lines):

```python
{"label": "avatar", "source": "GV_FreeShrubsPack/.../ThirdPersonCharacter",
 "player_start": [x, y, z], "spawn": [x, y, z], "arm": 500.0,
 "auto_possess": "Player0", "camera": "third_person",
 "next": ["play op=start", "avatar op=place label=avatar arm=<cm>  (re-tune the zoom)",
          "avatar op=remove label=avatar"]}
```

`remove`: `{"label": ..., "removed": True}` (PlayerStart untouched).
`describe`: the same playability census, read live.

## Invariants

1. **Tune the instance, never the Blueprint** — BP internals are not Python-writable
   (proven); the camera lives on the spawned actor's components.
2. **Auto-possess the placed pawn** — it's what makes Play use our tuned camera and what
   suppresses the GameMode's stray pawn (SPIKE-CHECK 1).
3. **Seat the capsule on the ground**, not the AABB — the character's sprite/arrow/mesh
   bounds float the capsule if you seat the full AABB (the exact bug `_add_player_start`
   already fixes for the PlayerStart, G55). Reuse that reseat.
4. **Arm length is the zoom lever; socket Z is the framing bias.** Not spawn-pitch (transient
   under `use_pawn_control_rotation`).
5. **Every mutating result carries `label`** (SPATIAL status block depends on it).
6. **`remove` leaves the PlayerStart** — it's a level marker with its own lifecycle.

## Verification plan (live, over the MCP tools, before commit)

1. `avatar op=place` on a fresh generated scene (e.g. a `pcg` forest): returns playable,
   PlayerStart + avatar co-located, avatar ueb-tagged and visible to `outliner`/`feel`,
   arm reported.
2. `play op=start` → **SPIKE-CHECK 1**: exactly one pawn, it is possessed by Player0, it is
   our instance, WASD moves it (the human confirms movement; the census confirms the single
   possessed pawn). `play op=stop`.
3. **The user's visual acceptance** (the no-vision policy hands this to the human): press
   Play, confirm the over-the-shoulder camera shows the mannequin's feet on the ground.
   `avatar op=place arm=<cm>` re-tunes until the framing is right; record the chosen arm +
   socket Z as the new default in this spec (**SPIKE-CHECK 2**).
4. `avatar op=describe`: playability census matches the live actors.
5. `avatar op=remove`: character gone, registry pruned, PlayerStart still present; re-place
   with the same label works.
6. `outliner op=reconcile` after a human-deletes-the-avatar simulation prunes the entry;
   `level op=clear` removes the avatar with the rest of the ueb arrangement.
7. Failures found on the way become numbered gaps in `gaps.md` (fix → live-verify → prune),
   per house discipline.

## For the user (one taste call + one open risk)

- **Verb name.** This spec recommends a dedicated `avatar` verb (own lifecycle, matches
  "plop down the avatar"). The alternative is `add what=avatar` (parallels the existing
  `add what=player_start`, but strains `add`'s one-actor contract). Verb-surface is a taste
  call the user owns (as `pcg`'s naming was) — say the word to switch.
- **"Stock UE5 character" reality.** This project's only third-person character is the
  mannequin bundled inside the `GV_FreeShrubsPack` demo folder; there is no Epic Third
  Person template installed. The verb adopts and discovers it. If you'd rather have the
  canonical Epic mannequin, add the Engine "Third Person" feature content and `avatar` will
  prefer it automatically.

## Ground truth — spike traces (2026-07-05, all over the RC bridge)

Level at probe time: `UEB_PCGMeadow` then `UEB_PCGForest` (a parallel session switched it);
`WorldSettings.default_game_mode` = `None`; one `player_start` already present.

1. **Character hunt.** No `/Game/ThirdPerson/...` and no `/Engine` third-person character
   (`does_asset_exist` false; engine search empty). Found a full kit under
   `/Game/GV_FreeShrubsPack/Demo/`: `ThirdPersonCharacter` (Blueprint),
   `ThirdPersonGameMode` (Blueprint), `SKM_Manny`, `ABP_Manny`, `SK_Mannequin`,
   `CR_Mannequin_*` control rigs, Manny materials/poses/textures.
2. **GameMode override is live.** `WorldSettings.default_game_mode` reads (`None`) and is a
   settable editor property; `ThirdPersonGameMode_C` loads and its `default_pawn_class` **is**
   `ThirdPersonCharacter_C`.
3. **BP internals are opaque to Python.** `Blueprint.get_editor_property("parent_class")`
   and `("simple_construction_script")` both raise "Failed to find property" — the camera
   boom cannot be edited through the asset. (Decisive: forces the instance path.)
4. **Instance components (spawned `ThirdPersonCharacter_C`):** `CollisionCylinder`
   (Capsule), `Arrow`, `CharacterMesh0` (SkeletalMesh), `Camera_FP` (CineCamera),
   `SpringArm` (SpringArmComponent), `Camera_TP` (CameraComponent), plus a SpotLight and
   camera proxy/frustum helpers. SpringArm defaults: `target_arm_length=300`,
   `socket_offset=(0,0,0)`, `relative_rotation=(0,0,0)`, `use_pawn_control_rotation=True`.
5. **Instance is tunable.** Set `target_arm_length` 300 → 650 (read back 650);
   `relative_rotation` set; `auto_possess_player = AutoReceiveInput.PLAYER0` set and read
   back (`AutoReceiveInput.PLAYER0`). `spawn_actor_from_class` / `destroy_actor` /
   `editor_request_begin_play` / `editor_request_end_play` all work.
6. **PIE-world async gap** (confirms SPIKE-CHECK 1 is two-call): `get_game_world()` returns
   `None` in the same dispatch that starts Play — the PIE world needs an editor tick, the
   same reason `play op=census` is two-call. All spike actors were destroyed and Play ended;
   no test state saved to the user's level.
