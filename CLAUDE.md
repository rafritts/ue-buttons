# ue-buttons

The blender-buttons philosophy projected onto Unreal Engine 5: a small MCP verb
surface over the Remote Control HTTP bridge, so an agent drives the UE editor through
legible perception, exact dimensions, and relational placement instead of coordinates.

Start with `README.md` (topology: Claude in WSL → mirrored localhost:30010 → UE 5.8 on
Windows) and `docs/SPEC-00-Initial.md` (the foundation spec). `scripts/probe.sh` is the
fastest way to verify the bridge is alive and run one-shot editor Python.

## The prime directive — read this first; it governs everything

**We optimize for exactly ONE thing: the MCP server being as pragmatic, correct, useful,
and trustworthy as it can possibly be. Nothing else.**

We do **not** optimize for any particular level or scene. This is deliberate, and it is
not indifference — it is the whole strategy, inverted:

> A user's scene is only ever as good as the tooling that builds it. Make the MCP server
> effortlessly useful and honest, and the scene takes care of itself. Chase a scene
> directly and sooner or later you cut a corner in the tool to get there — and that corner
> betrays the next user who trusts the tool.

From this, non-negotiably:

- **No shortcuts. No hidden workarounds.** A technique is legitimate only when it is
  correct *and* the user knows exactly what they got. The disqualifier is never
  "non-standard" — it is **deception**. The instant a tool makes the editor report one
  thing while the truth is another (the 2 km landscape sink: fine in the editor, broken in
  Play), it is dead code no matter how well it demos.
- **A limitation has exactly two honest exits: solve it correctly, or state it plainly as
  a limitation.** There is no third exit. "State it" means the tool tells the user the
  truth about what it did and did not do — surfaced, not buried. A *named* compromise
  (mesh terrain, with its losses spelled out) is honest engineering. A *silent* one is a
  lie.
- **Betraying a user's trust or expectations is the death of the project** — not a bug, a
  fatal one. We would rather ship less, and say so, than ship a lie that happens to pass
  the demo.

Cathedrals that still stand centuries later were not built by cutting corners. Neither is
this.

### Workaround verbs must announce themselves — and always offer the sidekick

A verb that **substitutes** for a UE feature the server cannot reach (today: `terrain` — a
GeometryScript mesh standing in for an un-sculptable Landscape actor) must say so, in its
own output, and never let the user assume they got standard UE. The disclosure **rides in
the tool's return payload as a first-class field** (like the status block), so the truth
survives even when the driving agent forgets to narrate it. Shape:

> ⚠ Heads up: I (the MCP server) **cannot sculpt real Landscape actors** in UE 5.8. Two
> honest paths, and I'll tell you straight which I recommend:
>
> **✅ Recommended — you sculpt, I ride shotgun.** For any terrain whose *look* matters,
> sculpt the real Landscape yourself in the editor: you keep sculpt/paint layers,
> landscape-grade material blending, grass types, LODs, and proper streaming — the real,
> full-fidelity thing. I assist from the sidelines: I **read** everything you do — measure
> it, and place, scatter, and material on top of the real surface. There's just no good
> pathway for me to move the sculpt tools myself.
>
> **Or — my `terrain` workaround**, a static mesh standing in for a Landscape. It is **not**
> the real thing (no sculpt/paint layers, no landscape material blending, no grass types) —
> but reach for it when these outweigh the lost fidelity:
> - **I can do it *alone*** — no human hands needed, so it's the only terrain an agent can
>   build end-to-end (batch levels, scheduled/autonomous builds, a quick repro test surface).
> - **Exact, known geometry** — I authored every height, so placing on it has clean
>   provenance; no measure-then-place guesswork.
> - **Scriptable reshaping** — I can `flatten`/`carve`/`shape` it on demand to fit a build
>   (flatten the cabin pad, carve the streambed); I can't do that to your hand-sculpt.
> - **Fast "just give me a ground"** — one call, no editor fiddling, when a rough surface
>   beats a beautiful one.
>
> So: sculpt it yourself (recommended), or should I lay down a `terrain` mesh?

The user must always be able to tell, at a glance, what is **standard UE** and what is
**"I'm an MCP server — no eyes, no hands — so here is my best honest substitute."**

*Labeling* is permanent and non-negotiable: every payload from a workaround verb carries
the flag. The *"Continue?"* confirm gates the **first** use per level/session; once the
user acknowledges, keep labeling but stop re-asking — honesty is forever, nagging is not (a
gate on every call would violate "effortlessly useful").

**Recommend the correct path; the workaround is the fallback, not the default.** When a
workaround exists, the disclosure must *actively recommend* the real UE path (the user does
the part the server can't — sculpt the Landscape by hand) and then **honestly list when the
workaround is genuinely the better pick** (agent autonomy / no human in the loop, exact
authored geometry with clean provenance, scriptable reshaping, a fast throwaway surface).
Never present them as neutral equals when one is correct: lead with the recommendation, but
never hide the real reasons to choose otherwise.

**Sidekick mode is that recommended path.** The user does the un-scriptable part (sculpt,
with their eyes and hands); the MCP does everything adjacent it genuinely **can** touch —
reading the real hand-sculpted surface back through perception (`feel`, `terrain
op=describe`, ground traces), then placing, scattering (`foliage`, `pcg`), materialing, and
measuring on top of the **real** Landscape. The server is a sidekick to the user's hands,
not a pretender to replace them.

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
