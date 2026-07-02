# bugs.md — ue-buttons

Outright defects (wrong output, crash, corrupted state) found while building or driving
ue-buttons. Same discipline as `gaps.md`: a bug is **reproduced, fixed, and the fix
live-verified over the RC bridge before it is cleared** (checked box). Keep the repro
and the root cause, not just "fixed".

Distinction from `gaps.md`: gaps are friction, missing capability, or design limits.
bugs are things that are *supposed to work and don't*.

Format: `### B<n> — <title>` · status · repro · root cause · fix · verification.

---

### B1 — `unreal.Rotator` positional args are (roll, pitch, yaw), not (pitch, yaw, roll)
Status: FIXED 2026-07-02 (live-verified)

Repro: `view` positioned the orbit camera but it came out tumbled — looking off into the
sky, never at the target. `transform action=rotate` was wrong the same way.

Root cause: `unreal.Rotator(10, 20, 30)` maps positionally to **roll=10, pitch=20,
yaw=30** (verified live). Both call sites assumed `(pitch, yaw, roll)`:
`view` passed `Rotator(pitch, yaw, 0.0)` → the computed pitch landed in `roll` and yaw in
`pitch`; `transform` passed `Rotator(r[1], r[0], r[2])` for `[yaw,pitch,roll]` → also
scrambled.

Fix: use keyword args everywhere — `unreal.Rotator(pitch=..., yaw=..., roll=...)` — so
the order can never be misread. (`unreal.Vector(x,y,z)` positional IS correct, so this
trap is specific to Rotator.)

Verification: after the fix, setting the orbit camera and reading it back in one call
gives forward·to_target **dot = 1.00000 (0.00° off)** — the camera points exactly at the
target. (Splitting set/readback across two separate RC calls can read a different
perspective viewport's state — a measurement artifact only; `view` sets location +
rotation atomically in one dispatch, so real use is exact.)

### B2 — `add(asset=)` silently resolved an ambiguous exact name to the first match
Status: FIXED 2026-07-02 (live-verified)

Repro: `add(asset="Wall_4m", …)` spawned the StaticMesh `…/Modular/Wall_4m` with no
warning — but the pack also ships a Blueprint named exactly `Wall_4m`
(`…/Modular/Blueprints/Wall_4m`). The caller had no way to know which they got, and which
"won" depended on asset-registry iteration order.

Root cause: `asset._resolve_asset_path` returned on the FIRST exact name match inside its
loop, so a same-name StaticMesh/Blueprint collision was resolved non-deterministically
instead of surfaced.

Fix: collect ALL exact-name matches; one → resolve, more than one → return them as
`candidates` (the same ambiguity path fuzzy matches already used). Exact still beats fuzzy.

Verification: `add(asset="Wall_4m")` now errors "ambiguous" listing both the SM and BP
paths; unique names (`Outhouse`, `Branch_Norway_Maple_Live_03`) still resolve directly.

### B3 — path drape traces the terrain before collision is ready → silent z=0.0, then `carve` bakes it into the mesh
Status: OPEN (found 2026-07-02 driving Level 1 dogfood; root cause characterized, not fixed)

Repro (Level 1, "Valley of trees"): `landscape create` → `landscape shape` (valley +
ridges + noise) → `path create` (route form) → `path carve` → `scatter`. The path's
returned waypoints came back with **`z=0.0` on 4 of 9 points** while the rest draped to real
terrain height (e.g. `[-3264,1311,418.9]`). The scatter that ran later reported
`no_ground: 0` — every one of ~11k candidates traced fine. So the *same* `trace_ground`
missed for the path and hit for the scatter, minutes apart, on the same terrain.

Root cause (two-stage): `path._drape` (path.py:129-130) does
`z = _ue.trace_ground(x,y); draped.append([x, y, z if z is not None else 0.0])`. Right
after `shape`, the DynamicMesh's **complex collision hasn't finished cooking**, so
`SceneTools._trace_world` returns `None` for the first waypoints — silently defaulted to
`0.0` instead of surfaced as a failure. Then `path carve` computes its flatten grade from
those stored waypoints, so it **flattened the southern bed to z=0** — baking the bad drape
into real geometry (a raised causeway ~800 cm above the natural −825 floor). Re-tracing the
floor afterward now *hits* z=0.0 there (a real flat surface), so the corruption is
self-consistent and invisible to a re-trace. Evidence: floor trace at x≤−6000 returns a flat
`0.0`; `landscape describe` (height function) still says −825..−269 there (see G15).

Two defects to fix: (1) `trace_ground` / `_drape` must distinguish "nothing beneath the
ray" from "collision not ready" — settle-and-retry after `shape`/`create` (poll the trace
until it stabilizes, or force a collision-cook wait), and `_drape` should *warn* on a miss,
never silently write 0.0. (2) `carve` should refuse (or warn) when a target waypoint z looks
like a miss sentinel rather than grading to it. Blender-buttons' drape has no cook race
(CPU mesh, immediate) — this is UE-specific (async physics cook).

### B4 — empty validate scope reads as a clean pass (typo'd target ⇒ `passed: true`; unresolvable focus ⇒ the validate line silently disappears)
Status: OPEN (found by code review of the SPEC-02 implementation, 2026-07-02 — not yet reproduced live)

`validate.run_validate` returns `{"passed": True, …, "line": ""}` whenever its scope
resolves to nothing (`validate.py` `if not scope:` early return). Three ways in, all bad:

- **`validate op=run targets=cabin_9` with a typo'd / deleted / substrate label** → the
  sweep reports `passed: true` with no line. A misspelled name reads as a clean scene —
  the exact "silence-because-nothing reads as silence-because-clean" failure SPEC-02
  exists to kill, produced by the floor itself.
- **Per-op: a mutating verb whose focus can't resolve to a spatial actor** (zero-extent
  at check time, renamed, etc.) → `line` is empty, and `verbs._status_block` only appends
  the line `if v.get("line")` — so Sense 2 vanishes from the block with no `validate:
  OFF` announcement. Silence must always be attributed (clean | OFF | can't-check).
- **Per-op: focus is `None` on a MUTATING verb** → `run_validate(None)` quietly becomes a
  *whole-scene* sweep presented as the op's delta (scope semantics flip on a falsy arg).

Fix direction: empty scope is its own honest verdict — `passed` omitted/None (not True)
and `line: "validate: nothing to check (unresolved targets: cabin_9 — missing or
substrate)"`; per-op, an unresolved focus prints that line rather than nothing; and
`run_validate`'s delta-vs-scene mode should be an explicit flag, never inferred from a
falsy label list.

### B5 — the "DEEPER than at declaration" tripwire never arms when the intent was declared before contact existed
Status: OPEN (found by code review of the SPEC-02 implementation, 2026-07-02 — not yet reproduced live)

`add_intent` records `depth_at_decl = _pen_depth(a, b)` at declaration time. The natural
declare-then-build flow ("path gravel will seat 3 cm into terrain by design" → *then*
place the gravel) records `depth_at_decl = 0.0`, and `_classify`'s tripwire is guarded by
`d0 and d > 2 * d0 + PEN_FLOOR` — `0.0` is falsy, so the escalation check is dead for
exactly the declarations made in the recommended order (tag tokens too: `_pen_depth` on a
tag returns 0.0). Only `max_depth` still protects those pairs, and it's optional.

Fix direction: treat `depth_at_decl == 0` as "not yet observed" and set it on the first
*nonzero* observed depth (lazily, in `_classify`), so the 2× escalation tripwire arms for
declare-first intents instead of never.
