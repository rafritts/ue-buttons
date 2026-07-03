The one way is simple. The authoring context window can never see the PNG. It will gaslight itself endlessly into thinking that what it wants to see, is in the image because it has 200k tokens of it building what it expects to see. Therefore, the ONLY way this can work, is there is some mechanism that gives a PNG to another fresh 0 token context window. You, the authoring session, dont even get to ask questions to that LLM, because you will only ask leading questions. "How big is the tree in this image?" meanwhile there are no trees, only shrubs, so the veiwing LLM says "the trees are very short". Instant chaos and confusion. The only way it MIGHT work, is if that new LLM is given a single prompt like "Describe what you see in this image. Be precise and specific." and then you have to lean on whatever is returned.

---

 I want you to leverage your familiarity with UE5 (much more than mine), to think of tooling that an LLM would need to fly blind in UE5.  What is the workflow like in UE5?  How do i tell you that stuff is broken? How would i say "hey this has no texture" or "the wind functionality is applies incorrectly here"?  How would i build a general purpose linter for UE5? We are just talking right now.

---

## LLM feedback (2026-07-03 — the agent's own critique of the mechanism above)

The core thesis is right: the authoring context can never see the PNG, and the
fresh-viewer split is the only honest architecture. But the note stops one step before
the actual failure mode. Sharpening points, from the LLM in question:

1. **The fresh viewer doesn't fix the problem — it moves it.** The split kills leading
   *questions*, but the leading *read* survives: when the viewer's prose comes back, the
   200k-token authoring context interprets it with the same self-confirming prior.
   "The trees are very short" → the authoring session rationalizes it ("shrubs read as
   short from that angle — fine") and reports success anyway. So "lean on whatever is
   returned" is the weak clause — the returned prose must be **graded mechanically by
   the server against ground truth**, never interpreted by the authoring context. The
   server knows it painted 37 trees at ~4 m; it diffs the viewer's report against that.
   The authoring session only ever sees the diff verdict.

2. **Absence-blindness.** "Describe what you see, be precise" has a recall problem: an
   unprimed viewer describes what's salient and almost never reports what's *missing* —
   and missing is exactly what matters (no texture, no fog, no shadows). Vision LLMs are
   also agreeable: shown a broken scene, the failure mode isn't a wrong description, it's
   a *plausible* one — the viewer politely fills in what a scene "usually has." Expect
   false positives of normality.

3. **Canary calibration.** Before trusting any report, the server plants a known object —
   a red sphere at a known spot — and checks the viewer got it. Fail the canary, discard
   the whole report. That turns "maybe it hallucinated" into a measurable rejection rule.

4. **Forced-choice from a question bank, not per-scene questions.** Open description has
   the recall problem; questions the authoring session writes are leading. The escape:
   neutral forced-choice probes authored **per defect class** ("Is the ground textured,
   or a uniform flat color?"), stored with the lint rules (SPEC-07's rules-as-data),
   selected by the server. Nobody with scene expectations ever writes a question.

5. **Scope it to recognition-shaped questions only.** Vision is recognition, so it may
   only answer categorical appearance questions that have no numeric instrument (texture
   presence, lighting mood, "reads as a forest"). Distance, alignment, size, and
   count-precision stay with `feel`/`describe` forever — the viewer must never become a
   lazy substitute for an instrument that exists.

**Remove:** the implicit hope in "be precise and specific." Precision instructions don't
defeat priors — architecture does (blind viewer → server-graded diff → canary gate). The
single-neutral-prompt idea survives, but as one component, not the mechanism.

Net: the note above describes how to get an *untainted look*. The full mechanism is an
*untainted verdict* — look, grade, and calibrate split across parties so that no one
both expects and judges. None of this changes the standing policy (NO LLM VISION; the
`view` verb stays deleted) — it is the recorded bar any future revisit must clear.