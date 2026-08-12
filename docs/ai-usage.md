# How AI was used

The brief asks which tools I used, where I leaned on them most, and — the part
that actually says something — a case where the AI proposed something I decided
not to use, and why.

This file was started before the first line of code and appended to as work
happened. A rejection log written from memory on the last day is worthless, and
the git history of this file is the evidence that it was not.

---

## Tools

**Claude Code** (Opus 5), in the terminal, for the whole project: planning,
implementation, tests, review.

**SASA**, a spec-driven development workflow I maintain as a set of Claude Code
commands. It structures the path from a requirement to merged code: write the
canonical spec first, design against it, implement with TDD, then verify that
every specified behavior has a test.

---

## How I worked

### The spec-driven flow was used on one story, not on everything

SASA has twelve commands across four phases. I used four of them, on one story:
the conversation flow together with the provider error taxonomy, both in the same
spec.

- `sasa:propose` wrote `docs/specs/conversations.md` — the observable behavior in
  Given/When/Then — and then the design and task breakdown. Two approval gates.
- `sasa:apply` implemented it test-first, task by task.
- `sasa:verify` checked, in an isolated context, that every Given/When/Then in
  the spec maps to at least one test.
- `sasa:quick` guarded later small changes: it halts and redirects if a "quick
  fix" would actually alter specified behavior.

Everything else — the skeleton, Docker, the MongoDB adapter, the frontend, CI —
was written directly.

**Why partially.** The discovery phases (`vision`, `map`, `explore`, `roast`)
exist to work out what to build and for whom. Here the brief already answers
that. Inventing user interviews for a chatbot whose specification is one
paragraph long would be ceremony wearing the costume of rigor. I applied the full
process to the one part of the system where the risk is concentrated — the turn
lifecycle and what happens when the provider fails — and went straight at the
rest.

I also did not run the framework's installer; see rejection 7.

### What I leaned on AI for most

Drafting and then arguing about design options: data model shape, error
taxonomy, where the layer boundaries go. The value was not the first answer, it
was having something concrete to disagree with. Several of the entries below came
out of exactly that.

### The rule that kept scope from creeping

At every decision point: name one specific thing that would be wrong if this
shipped as-is. If the answer is concrete, fix that one thing and move on. If it
is "it could be better", it ships. Vague dissatisfaction is not a blocker, and
without that rule a 48-hour project quietly becomes a 96-hour one.

---

## Suggestions I did not use

### 1. A fake provider as a demo mode

**Suggested.** Ship a fake LLM adapter wired in by default, so the app produces
answers without an API key.

**Rejected because.** In a chatbot the generation *is* the product. Simulating it
would make the app look like it works while hiding whether the real integration
does — which is the first thing a reviewer needs to verify.

**What shipped instead.** The fake exists only as a test double, never wired at
runtime. Without a key the app boots, everything except generation works, and the
UI says so.

### 2. A `PATCH` endpoint to rename conversations

**Suggested.** Add renaming; it is only about ten lines.

**Rejected because.** "It is only ten lines" is the weakest possible argument for
a feature, and I noticed I was using it. The brief does not ask for renaming, the
generated title makes it unnecessary, and it drags along a schema, validation, a
test, a button and an inline editing state.

**What shipped instead.** Nothing. The title is derived from the first message.

### 3. Denormalizing the sidebar, and then a pipeline to avoid denormalizing

**Suggested.** First: copy `last_message_preview` and `message_count` onto the
conversation document so the sidebar is one cheap query. When that introduced a
write that could leave the copy stale, the follow-up suggestion was an
aggregation pipeline computing both at read time instead.

**Rejected because.** Both answers were solving the wrong problem. The implicit
requirement — that the sidebar should look like every chat app's sidebar — had
never been examined. It came from nowhere and two rounds of design went into
optimizing around it. The right question was not "which of these two", it was
"why are we showing anything besides the title".

**What shipped instead.** The sidebar shows titles. `conversations` holds
`{_id, title, created_at, updated_at, model}`. No copied fields, no pipeline, and
the atomicity section of `decisions.md` shrank to a paragraph.

### 4. A client-supplied idempotency key for retries

**Suggested.** Persist the user's message before calling the model, and have the
client send a `client_message_id` with a partial unique index, so retrying after
a 429 regenerates the answer without duplicating the message.

**Rejected because.** It solved a problem it had just created. The duplicate only
exists because the message was saved before knowing whether generation would
succeed. Make the turn atomic and there is nothing to deduplicate.

**What shipped instead.** Nothing is persisted if the model call fails. One
field, one index and a branch of logic removed.

### 5. A devcontainer

**Suggested.** A devcontainer pointing at the same compose file, in two variants.

**Rejected because.** It is development tooling, not a deliverable. Nobody asked
for it, and it is exactly the kind of surface that is subtly broken on the one
occasion someone opens it.

**What shipped instead.** Nothing in the repository.

### 6. A recommendation the AI then reversed on its own

**Suggested.** Of the two sidebar options above, the aggregation pipeline was
initially recommended, then revised to the denormalized version once the costs
were actually weighed.

**Worth recording because.** The first recommendation chased the elegance of "one
write per turn" without noticing it moved complexity from somewhere cheap — two
obvious lines on the write path — to somewhere expensive: twenty lines of pipeline
with worse performance, read by whoever maintains it next. A confident
recommendation is not a correct one.

**What shipped instead.** Neither, once the requirement itself was questioned.
See 3.

### 7. Running the workflow framework's installer

**Suggested.** Run `install.sh`, then clean up what did not apply.

**Rejected because.** The installer does nine things and one of them was useful.
It generates a project guide from a template that I would have had to rewrite
completely, creates four documentation directories full of placeholder files,
adds a blank pull request template, configures two MCP servers, indexes the
repository with a third-party tool, and writes persistent instructions that
contradict the plan. Accepting a tool's default path and scheduling the cleanup as
your own work is a bad trade: if the main artifact has to be rewritten anyway, the
installer produced negative value. **A process tool has to add, not subtract.**

**What shipped instead.** Four command files, one agent and one template, copied
by hand. Nothing to clean up afterwards. The commands I left out were dropped
after reading their stated prerequisites and confirming they degrade cleanly —
for example, the implementation command declares a code-indexing dependency but
has an explicit branch for greenfield projects that skips it.

---

## Reviewing the result with AI, adversarially

The brief says the submission is reviewed by several AI models in parallel. So
before calling it finished I did that to it myself: three agents, run
concurrently, each with a different brief — security and OWASP, architecture and
backend design, and Python plus LLM-product practices — each asked to produce a
pull-request review and to verify claims against the running code rather than
reason about them.

They found nine real defects. The rule I set for myself was that no finding got
fixed until I had reproduced it, and that mattered: everything below was
confirmed before being touched.

The four worth knowing about:

**A user-facing setting did the opposite of what it said.** `HISTORY_LIMIT=1`
means "no history, just this message". The window is computed as `limit - 1`,
which is `0`, and zero means *unlimited* to both MongoDB's `.limit()` and a
Python slice. So the smallest legal window shipped the entire transcript — and
the most natural reason to set it, cutting token spend on a free tier, was the
one that broke.

The interesting part is why 74 tests missed it. `FakeConversationStore`
reproduced the real store's bug in the same direction, so a service test agreed
with the adapter while both were wrong. That is what a double written against
the implementation instead of the contract buys you, and it is the single most
useful thing this review taught me.

**Five documents described behaviour the code did not have.** The route
docstring, an adapter comment, the frontend client, the README and a spec
criterion all said a missing API key is caught before the stream opens and
returns 503. It was not; it surfaced as an in-band event on a 200. Worse, the
test covering that criterion carried the docstring "the client still gets 503"
while posting to an unknown conversation and asserting 404 — it passed for a
reason unrelated to what it documented. I made the code match the claim rather
than the other way round.

**A decision document justified a security posture the compose file did not
implement.** The entry defending MongoDB without authentication rests on it
being reachable from localhost only. The port was published on `0.0.0.0`. The
reasoning was sound and the premise was false, which is a worse failure than
being wrong outright.

**A load-bearing claim was an overstatement.** "One command, so the pair cannot
be split" — MongoDB guarantees atomicity per document, and an ordered
`insert_many` keeps whatever it already wrote. A reviewer reproduced a stored
question with no answer. I corrected the entry in place and left the correction
visible rather than quietly rewriting history.

What I take from it: every one of those four is the same failure in a different
costume — **prose that outran the code**. The comments in this project are dense
and mostly earn their place, but a confident comment is read as a specification,
and four of them had drifted into being wrong. A wrong `# why` comment is worse
than no comment, because it is exactly the line the next reader trusts.

I did not accept everything. Suggestions to add rate limiting, cursor
pagination, container resource limits and a non-root nginx were all correct in
general and all declined for this scope — they are in the README's future-work
list with that reasoning, rather than half-built here.

## The pattern

Reading these back, the rejections are not random. Cases 2, 3 and 4 are the same
mistake in three costumes: **the AI optimized the solution instead of questioning
the requirement.** Once a requirement is taken as given, a proposal that serves it
looks correct, and each one of these did. The work that mattered was going one
level up and asking whether the requirement belonged there at all.

That is also why case 3 is the one I would point at. It is not a good decision
recorded after the fact — it is two rounds of increasingly clever design
disappearing the moment someone asked why the sidebar needed anything more than a
title.
