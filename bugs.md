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
