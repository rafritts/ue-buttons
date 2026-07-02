# ue-buttons

The blender-buttons philosophy projected onto Unreal Engine 5: a small MCP verb
surface over the Remote Control HTTP bridge, so an agent drives the UE editor through
legible perception, exact dimensions, and relational placement instead of coordinates.

Start with `README.md` (topology: Claude in WSL → mirrored localhost:30010 → UE 5.8 on
Windows) and `docs/SPEC-00-Initial.md` (the foundation spec). `scripts/probe.sh` is the
fastest way to verify the bridge is alive and run one-shot editor Python.

## Sister project: blender-buttons

`~/workspace/blender-buttons` (github.com/rafritts/blender-buttons) is the origin and
reference implementation — same author, same partnership model (human owns
taste/playtesting, agent owns precision/mechanical verification), same core concepts.
Most of what this repo needs already exists there in mature form:

- Verb surface design: `server/verbs/` (SPEC-05 verb collapse — ~15 verbs, not 137 tools)
- Relational/AABB math to port: `server/relational.py`
- Auto-status block, placement DSL vocabulary: its `README.md`
- Agent field manual worth emulating: `GUIDANCE_FOR_LLMS.md`
- Process: `gaps.md` discipline (friction → numbered gap → fix → live-verify → clear)

When porting, translate conventions — Blender is meters, front = −Y; UE is centimeters,
front = +X, yaw/pitch/roll — and check the sister repo before inventing anything that
smells like it was already solved there.

## UE project (not in this repo)

The editor project lives on NTFS: `C:\Users\anvil\Documents\Unreal Projects\UEButtons`
(`/mnt/c/Users/anvil/Documents/Unreal Projects/UEButtons` from WSL). This repo is the
source of truth; runtime code is synced into the project's `Content/Python/`.
