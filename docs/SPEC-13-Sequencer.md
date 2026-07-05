# SPEC-13 — `sequencer`: cinematics from level ground truth

Status: **DESIGN — spike-proven 2026-07-05.** Audience: the agent implementing the verb.
Every engine claim below was probed live over the RC bridge on UE 5.8 (traces at bottom)
unless marked **SPIKE-CHECK**.

## Problem

The agent can build a world but cannot present it: no flyby to show the user a level,
no camera move, no keyed animation. Sequencer is UE's timeline; the entire Python
surface works (spike: full pass, zero blockers). The verb is `sequencer` (SPEC-05
reserved it; flagged there as an obesity risk — a whole application wearing a verb —
so this spec ships a deliberately SMALL slice).

## Decisions already made (do not relitigate)

- **v1 scope is the flyby + keyed-transform slice**, nothing else. No audio tracks, no
  material tracks, no subsequences, no Movie Render Queue (plugin not enabled — probed;
  enabling it is a future spec when the user wants rendered video files). Sequencer
  earns more ops the way every verb does: a dogfooded need at a time.
- **Keys are DERIVED, never divined.** The agent does not hand-author coordinate
  keyframes. Camera paths come from level ground truth: a spline's sampled centerline
  (`spline op=describe` machinery), an orbit derived from a target actor's measured
  AABB, a dolly between two labeled actors' positions. This is the ue-buttons
  differentiator: **relational cinematography** — `along=`, `look_at=`, `orbit=` — the
  placement DSL pointed at a camera over time.
- **Playback preview is for the USER, not the agent.** `play` here scrubs the editor
  viewport through the sequence — the agent cannot watch it (vision policy) and never
  claims to. The agent's perception is the sequence's numbers: bindings, tracks, key
  times/values, camera-cut ranges.
- Sequence assets live under `/Game/UEB_SEQ/<name>`, ordinary visible assets, one per
  cinematic, user-openable in the Sequencer UI at any time.
- Frame rate 30 fps display rate by default; ranges in SECONDS at the verb surface
  (`duration=5.0`), frames internal.

## Verb contract

### MCP tool (`server/main.py`)

```python
@mcp.tool()
def sequencer(op: Literal["create", "shot", "play", "describe", "remove"] = "describe",
              label: str = None, duration: float = None, shot: dict = None,
              at: float = None) -> str:
    ...
    return render(call_ue("sequencer", p, timeout=120))
```

### Ops

| op | params | effect |
|---|---|---|
| `create` | `label=` (required), `duration=` (s, default 10) | create `/Game/UEB_SEQ/<label>` LevelSequence, 30 fps, playback range [0, duration]; register |
| `shot` | `label=`, `shot=` (dict, below) | add one camera move to the sequence: spawns/reuses a ueb-tagged CineCameraActor, binds it, writes derived transform keys + a camera-cut section |
| `play` | `label=`, `at=?` (s, scrub instead of play) | open in Sequencer UI + play (or scrub to `at`) — the user-viewing surface |
| `describe` | `label=` (omitted → all) | bindings, tracks, key count + first/last key values, cut ranges, duration — the numeric readback |
| `remove` | `label=` | close if open, destroy the sequence's ueb camera actors, delete the asset, unregister |

### The `shot=` dict (the intent surface)

One of three derivation modes, all seeded from ground truth:

```python
{"kind": "flythrough", "along": "<spline label>", "height": 400, "look": "ahead" | "<actor label>",
 "start": 0.0, "end": 8.0}          # keys sampled from the spline's live centerline
{"kind": "orbit", "around": "<actor label>", "radius": None,  # None → 2.5× target AABB radius, derived
 "height": None, "revolutions": 1.0, "start": 0.0, "end": 8.0}
{"kind": "dolly", "from": "<actor label | {at:[x,y,z]}>", "to": "<actor label>",
 "look_at": "<actor label>", "start": 0.0, "end": 5.0}
```

Key density: one key per sampled waypoint for `flythrough` (the spline sampling already
exists — G45 machinery); 16 keys/revolution for `orbit`; 2 keys + easing for `dolly`.
Rotation keys aim the camera per `look`/`look_at` at each sampled position (derived
look-at math on measured positions — legitimate arithmetic on ground truth).

Multiple `shot` calls append: each new shot's camera-cut section starts where the last
ended (read the existing cut track's end — never overlap cuts).

### Errors (HATEOAS)

- unknown `label=` → live sequence list + `sequencer op=create` next line.
- `shot.along=` names a spline that doesn't exist → the spline-labels error `spline`
  already uses.
- `shot` beyond the sequence's duration → error stating the range and offering
  `op=create duration=<needed>` (extending is a mutation the agent should re-declare).
- `remove` while the sequence is open in the UI → close first (`close_level_sequence`),
  then delete; if the asset still refuses deletion, report it as in-use and STOP (G47:
  never force-delete).

## Runtime implementation (`runtime/ue_buttons/sequencer.py`, new module)

Registry (`_state.py`, hasattr-guarded): `sequences = {}` —
`{label: {asset_path, duration, shots: [...], camera_labels: [...]}}`. Wire into
`verbs.py` `_VERBS` + SPATIAL (its mutations spawn camera actors); reconcile prunes
entries whose asset is gone; rehydrate-on-open from `/Game/UEB_SEQ/` contents
(asset-registry scan) like G61 groves. `level op=clear` must also delete the level's
sequence cameras (they're ueb-tagged, so the sweep catches them) — the sequence ASSET
survives clear (it's content, not level state); its bindings go stale and `describe`
must say so (**SPIKE-CHECK**: what a possessable binding reports after its actor died —
expect `get_bound_objects` empty; render that as a `stale_bindings` warning with the
re-`shot` next line).

Build sequence for a `shot` (all APIs proven):

1. `unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, "/Game/UEB_SEQ",
   unreal.LevelSequence, unreal.LevelSequenceFactoryNew())` (create op);
   `set_display_rate(FrameRate(30,1))`, `set_playback_start/end`.
2. Spawn CineCameraActor via `add`'s helper (label `<seq>_cam<n>`, ueb-tagged).
3. `binding = seq.add_possessable(cam)`; `track = binding.add_track(
   MovieScene3DTransformTrack)`; `section = track.add_section()`; `section.set_range()`.
4. `section.get_all_channels()` → 9 channels named `Location.X_0` … `Scale.Z_0`;
   `channel.add_key(FrameNumber(f), value)` per derived sample.
5. Camera cut: `cut = seq.add_track(MovieSceneCameraCutTrack)`; `cs = cut.add_section()`;
   `cs.set_range()`; `cs.set_camera_binding_id(seq.get_binding_id(binding))`.
6. `EditorAssetLibrary.save_loaded_asset(seq)`.
7. describe: walk `seq.get_bindings()` / tracks / sections / channels + `get_keys()`
   (times + values proven readable).

Playback (op=play): `LevelSequenceEditorBlueprintLibrary.open_level_sequence(seq)` +
`play()` / `set_current_time(frame)`; `is_playing()` for the status line. NOTE:
`set_current_time`/`get_current_time` are deprecated in 5.8 (work fine; warnings in
log) — prefer the playback-params overloads if the deprecation graduates to removal.

New-module reload gotcha applies (editor restart before hot-reload picks it up).

## Invariants

1. **Every key value traces to a measured source** (spline sample, actor AABB, labeled
   position). A hand-typed coordinate keyframe is a spec violation.
2. **Camera-cut sections never overlap** — append shots by reading the cut track's end.
3. The agent never claims to have SEEN a sequence — `describe` is numbers; `play` is
   the user's.
4. Sequence cameras are ueb-tagged and owned by the sequence (removed with it).
5. Never force-delete an in-use asset (G47).

## Verification plan (live, over the MCP tools, before commit)

1. `op=create label=flyby duration=8` → asset exists at `/Game/UEB_SEQ/flyby`, range
   [0,240] frames, registered.
2. `op=shot` flythrough along an existing dogfood spline → describe shows 9-channel
   transform track, key count = waypoint count, first/last key values match the
   spline's sampled endpoints (read both, compare numerically).
3. `op=shot` orbit around a labeled actor → radius in keys ≈ derived radius; camera-cut
   track has two non-overlapping sections.
4. `op=play` → `is_playing()` true (user confirms visually — their half).
5. `op=remove` → asset gone, cameras gone, registry pruned, reconcile clean.
6. Save/reopen level → sequence rehydrates; kill a bound camera by hand → describe
   reports stale binding with next line.
7. Dogfood: an establishing flyby of the current dogfood level; findings → gaps/bugs.

## Ground truth — spike traces (2026-07-05, RC bridge, UE 5.8)

1. Classes all present: LevelSequence(+FactoryNew), MovieSceneSequenceExtensions,
   LevelSequenceEditorBlueprintLibrary, SequencerTools, MovieScene3DTransformTrack,
   MovieSceneCameraCutTrack, Binding/Track/SectionExtensions, CineCameraActor,
   MovieSceneScriptingFloatChannel.
2. Created `/Game/UEB_SPIKE/SPIKE_Seq` via AssetTools + LevelSequenceFactoryNew;
   `set_display_rate(30)`, playback range 0–150 — all read back exactly.
3. `add_possessable(cine_cam)` bound; transform track + section added;
   `get_all_channels()` → 9 channels (`Location.X_0`…`Scale.Z_0`); `add_key` at frames
   0/150 with values 0.0/5000.0 → `get_keys()` read back `[(0, 0.0), (150, 5000.0)]`.
4. Camera cut track added at sequence level; `set_camera_binding_id(seq.get_binding_id(
   binding))` succeeded.
5. Playback: `open_level_sequence` → True; `set_current_time(75)` → `get_current_time()`
   = 75 (deprecation warnings, functional); `play()` → `is_playing()` True; `pause()` +
   `close_level_sequence()` clean.
6. Spawnables exist (`add_spawnable_from_class/_from_instance`) — unused in v1.
7. Movie Render Queue absent: `MoviePipelineQueueSubsystem`/`MoviePipelineQueue`/
   `MovieGraphConfig` all missing (plugin not enabled).
8. Cleanup: cam destroyed, `delete_asset("/Game/UEB_SPIKE/SPIKE_Seq")` → True (no
   in-use refusal once closed).
