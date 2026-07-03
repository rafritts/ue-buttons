# vision.md — what this server is becoming

> This MCP server aims to accomplish the heroic undertaking of letting an LLM drive UE5
> to completion. Pragmatism is chief among all things: we ship pragmatic, working code
> that is easy to reason about, maintain, and predict — over rigid ideas about how the
> codebase should be.

The user's charter and the visionary ideas behind the server, collected 2026-07-03 while
shaping SPEC-05. SPEC-05 keeps the verb-alignment *law*; this file keeps the *why* and
the destination. When a design decision needs a tiebreaker, it breaks toward this file.

## Why: UE5 is too absolute to wing it

Blender and UE5 are thoroughly taxing environments — absolute in their demands. Asking
an LLM to "wing it" by free-scripting `bpy` or `unreal` against the engine does not cut
it and never will: the APIs are version-skewed against the model's training, the editor
state is invisible without deliberate perception, spatial values invented from intuition
are hallucinations wearing confidence, and one wrong call crashes the editor (we have
the crash dumps to prove it). The server exists to close the gap between what the model
can *reason about* (intent) and what the engine *demands* (exactness) — with engineering,
not with hope.

## The inversion: fat server, thin agent

The typical MCP server is a thin wrapper — one tool per endpoint, raw JSON out, all
cognitive work exported to the agent, on the implicit assumption that the model's
context and reasoning are free. This project inverts that: **the agent's context is the
scarcest, most expensive, least reliable resource in the system; server-side
deterministic compute is nearly free.** Therefore anything deterministically computable
is the server's job to compute and serve unasked; the agent's context is spent
exclusively on intent. The server is fat and herculean precisely so the agent can be
thin and honest.

## The mechanism: affordances (HATEOAS)

Get ground truth to the agent as easily as possible — the relevant data should
practically THROW ITSELF at the agent, and staying in intent space should be
effortlessly trivial. Borrowed from REST's HATEOAS: **every finding, warning, and state
read carries the next legal move as a ready-to-fire MCP command.** A `validate` finding
doesn't just describe the defect — it says "here's the error → if you want to change it,
here's the command: `…`". The agent never translates a finding into a verb call by
reasoning; the response already contains the affordance.

The reactive half is already the house style: the status block (ground truth after every
act), the forced senses (perception that can't be skipped), self-correcting errors (the
valid values arrive WITH the failure), the author-time gate (the warning arrives WITH
its escape-hatch commands), lint findings that name their fix command.

The full form is **proactive**: the server precomputes the ACTION SPACE, and the agent
is lavishly fed affordance grapes by the herculean efforts of the server's deterministic
compute. The worked example: modular building assets get their snappable joints
precalculated — the agent asks "I have this wall piece, what are its snappable joints?"
and receives the joints by id + description, ranked by proximity to the work site, WITH
an example snap command ready to fire. The agent's move is pure intent selection ("snap
the east joint to the corner post"); every coordinate, tolerance, and rotation was
deterministic compute the server already did. (UE hands us the native construct:
StaticMesh **Sockets** — precomputed snap points surface as `asset op=sockets`.)

Affordances-with-commands is a **correctness** feature, not a convenience: every command
the server hands over is a command the agent didn't compose from possibly-hallucinated
parts. In a domain where the agent's failure mode is confidently inventing a coordinate,
"the server already wrote the command" is the strongest anti-hallucination mechanism
available. The nearest design ancestor isn't other MCP servers — it's compiler/language-
server diagnostics with fix-its, which is HATEOAS for programmers.

The burden that comes with it: when the agent is lavishly fed, it TRUSTS the grapes. A
wrong precomputed joint or stale affordance is worse than none — it arrives wearing
ground truth's clothes. The vision only works welded to the disciplines: live-verify,
provenance, gaps.md pruning. Fat server + sloppy verification = a machine for generating
confident errors.

## The language: one vocabulary for three parties

The verb surface is simultaneously the agent's API, the human's spoken vocabulary, and
UE's own taxonomy — SPEC-05's law (the 2×2, the shared-language test, the pragmatism
clause) exists so all three parties mean the same thing by every word. Affordances are
only effortless if the command they hand you is understood on sight by both the agent
(training data) and the human (the editor UI they actually use). "I painted foliage"
points at a dropdown the human can open; "I ran a scatter" points at nothing.

## The error philosophy: three tiers, and a ratchet

Best: **prevention** — author-time gates refuse or warn before the defect enters (the
verbs check asset × usage compatibility before mutating). Second: **immediate error** —
the status-block census surfaces defects on the next verb call, the closest a blind
agent gets to the human's two-second viewport glance. Worst case: **spelunking** — the
deixis/diagnose loop (the user points, the agent digs). The ratchet: every spelunk must
end as a new rule in the table, so the worst-case loop runs once per defect CLASS, never
twice. The defect taxonomy is finite and industry-shared (~a dozen context-mismatch
classes); this is a toolbox with a ceiling, not a cathedral.

## What "done" looks like

A UE-fluent agent lands with zero repo priors and builds a level to completion from
reflex — every noun in its narration is a UE noun the human can see in their own editor;
every warning arrives before the mistake or immediately after; every finding carries its
fix; every snap, placement, and measurement is server-computed ground truth; and the
human's role is taste, playtesting, and pointing — never translation, never spelunking
on the agent's behalf.
