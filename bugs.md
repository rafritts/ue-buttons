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
