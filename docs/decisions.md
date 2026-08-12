# Design decisions

One entry per decision, written when the decision was taken rather than
reconstructed at the end. Each has the same four parts:

- **Context** — the problem that needed solving.
- **Decision** — what was chosen.
- **Why** — the concrete reason, not a generic one.
- **When this would NOT apply** — the situation in which the same choice would be
  wrong. A decision you cannot argue against is one you have not really made.

---

## Two collections, not messages embedded in the conversation

**Context.** MongoDB makes it tempting to store a conversation as one document
with a `messages` array inside it. One read returns everything.

**Decision.** `conversations` and `messages` are separate collections, joined by
`conversation_id`.

**Why.** A chat has no natural length limit. A growing array runs into the 16MB
document cap, and every `$push` rewrites the whole document — the write cost grows
with the conversation. The sidebar query would also have to either drag every
message along or rely on a projection that is easy to get wrong later.

**When this would NOT apply.** If conversations were bounded — a support ticket
with at most a few dozen messages — embedding would be better: the turn write
becomes genuinely atomic, and reading a conversation is a single document fetch.

---

## No multi-document transactions

**Context.** Writing a turn touches two collections. In a relational database
this would be one transaction.

**Decision.** No transactions. MongoDB runs as a standalone `mongod`, which does
not support them, and the data model was shaped so they are not needed.

**Why.** What protects the history is the *order of operations*, not a
transaction. The model is called first and the writes happen afterwards, so the
window in which a crash can split a turn is the gap between two consecutive
writes rather than the 5–30 seconds of the model call. The two messages then go
out as a single `insert_many`, one command on the wire, so the pair cannot be
split. The only write left outside that guarantee is the `updated_at` bump on the
conversation, and its worst case is one row briefly out of order in the sidebar —
no data lost, and the conversation itself reads correctly because it is loaded
from `messages`.

**When this would NOT apply.** If a failed write could produce a state a user
could act on incorrectly — anything touching money, inventory or permissions —
the standalone deployment would be the thing to change, not the guarantee.

Running MongoDB as a single-node replica set purely to unlock transactions was
considered and rejected: it adds an `rs.initiate()` to startup and a whole class
of new failure modes, to protect the ordering of one row in a list.

---

## A failed generation persists nothing

**Context.** The model call is the step most likely to fail — rate limits,
timeouts, a rejected key. Something has to happen to the message the user already
typed.

**Decision.** The turn is atomic. Validate, load history, call the model, then
write both messages together. If the call fails, nothing was written.

**Why.** The alternative — save the user message first, then generate — creates a
new problem to solve the old one: conversations that end in an unanswered
question, and a retry path that has to avoid duplicating the message, which means
a client-supplied idempotency key and a unique index to enforce it. Not writing
anything removes all of it. `GET /conversations/{id}` can never return a dangling
user message, so the UI has one fewer state to render.

**Trade-off accepted.** The typed text lives in the composer until the turn
succeeds, so closing the tab loses it. With streaming, the turn is persisted when
the stream closes, so a client that disconnects mid-stream loses that turn.

**When this would NOT apply.** If messages were expensive to re-enter — a long
form, a voice transcription, an upload — losing the input would be worse than the
dangling-message state, and saving first would be right.

---

## The sidebar shows only the title

**Context.** A conversation list usually shows a preview of the last message and
sometimes a message count.

**Decision.** Title only.

**Why.** Both extra fields are facts about `messages`, not about the conversation.
Showing them means either copying them onto the conversation document on every
turn — two writes per turn, and a copy that can drift out of sync — or computing
them at read time with a lookup pipeline that scans messages to count them.
Neither is needed to decide which conversation to open. Dropping the requirement
removed both problems instead of choosing between them.

**When this would NOT apply.** With many conversations that have similar titles, a
preview is what makes the list scannable, and the denormalized copy becomes worth
its cost.

---

## Conversations are ordered by last activity

**Context.** With the sidebar reduced to titles, the conversation document could
have held nothing but `title` and `created_at`, making a turn a single write.

**Decision.** Keep `updated_at` and order by it, so a conversation you just
replied to moves to the top.

**Why.** Ordering by creation date means resuming an old conversation leaves it
buried where it was, which is exactly the behavior that makes a list feel broken.
The cost is one extra `$set` per turn, and its failure mode is one row temporarily
out of order.

**When this would NOT apply.** If conversations were archival records rather than
a working list, creation order would be the more meaningful one.

---

## The LLM port has a single streaming method

**Context.** Streaming responses was a stretch goal. Adding it later changes the
signature of everything between the endpoint and the adapter.

**Decision.** The port exposes only `stream() -> AsyncIterator[str]` from the
first commit. The JSON endpoint consumes the generator and joins it.

**Why.** The expensive part of streaming is not the SSE endpoint, it is the shape
of the service layer. Deciding it on day one costs a little ceremony in the tests
and makes streaming an additive change — a new endpoint plus frontend work —
instead of a refactor attempted with the deadline in sight.

**When this would NOT apply.** If streaming were definitively out of scope, a
plain `generate()` returning a completion object would be simpler and would carry
metadata (token usage, finish reason) more naturally.

---

## `/health/ready` returns 200 when the API key is missing

**Context.** The app deliberately starts without an API key. The readiness probe
has to say something about that.

**Decision.** 200 with `"status": "degraded"` and a `checks` object naming the
unconfigured provider. 503 is reserved for MongoDB being unreachable.

**Why.** Readiness is consumed by orchestrators to decide whether to route traffic
and whether to restart the container. A missing key is a configuration state the
app tolerates by design — everything except generation works. Returning 503 would
mean `depends_on: service_healthy` never passes and Docker restarts a healthy
container in a loop, breaking `docker compose up` for precisely the person who did
not set a key. That is the scenario the brief asks about.

**When this would NOT apply.** If the service existed only to call the model, a
missing key would make it genuinely useless and 503 would be honest.

---

## `/api/v1/config` is separate from the health endpoints

**Context.** The frontend needs to know whether the provider is configured, in
order to show a banner before the first message. That information is already in
`/health/ready`.

**Decision.** A separate endpoint for the frontend.

**Why.** They are contracts for different audiences with different stability
requirements. Health is for an orchestrator and should be free to change shape;
`/config` is a UI contract. And the banner needs the model name and a
documentation URL, neither of which belongs in a health probe. Both read from the
same function in the service layer, so there is one source of truth and two
presentations.

**When this would NOT apply.** If the frontend needed nothing beyond a boolean,
the extra endpoint would not earn its place.

---

## One error envelope for every error

**Context.** FastAPI returns `{"detail": ...}` for `HTTPException`, a different
shape for validation errors, and whatever the handler returns for domain errors.

**Decision.** Every error response — including 404 and 422 — has the same four
fields: `reason`, `message`, `retryable`, `docs_url`. The validation and
`HTTPException` handlers are overridden to match.

**Why.** The frontend gets one shape to parse and one field to branch on.
`retryable` means the retry logic does not need a table of status codes, and
`docs_url` points at a README anchor per `reason`, so troubleshooting lives in the
one document a reviewer is already reading.

**When this would NOT apply.** In a public API with existing consumers, replacing
the framework's default error shape is a breaking change that needs versioning.

---

## Provider failures are not collapsed into one status code

**Context.** The easy path is catching everything from the provider and returning
503.

**Decision.** Four distinct outcomes: missing key → 503 `missing_api_key`;
rejected credentials → 502 `invalid_credentials`; rate limited → 429
`rate_limited` with `Retry-After`; timeout or provider down → 504/502
`provider_unavailable`.

**Why.** The backend already knows which one happened, so collapsing them throws
away information the client needs. Only two of the four are worth retrying —
retrying an invalid credential just burns time — and `retryable` in the envelope
says which.

**When this would NOT apply.** If the distinction leaked information useful to an
attacker, a deliberately vague error would be the right call.

---

## The fake LLM is a test double, never a runtime mode

**Context.** A "demo mode" that returns canned answers would let the app appear to
work without an API key.

**Decision.** The fake exists only in tests. It is never wired in
`core/dependencies.py`.

**Why.** In a chatbot the generation *is* the product. Simulating it would make
the app look like it works while hiding whether the real integration does — which
is the first thing a reviewer needs to verify. Without a key the app boots and
says so; it does not pretend.

**When this would NOT apply.** In a product where the model is one feature among
many, a stubbed mode is a reasonable way to demo everything else.

---

## MongoDB is real in integration tests; only the LLM is faked

**Context.** Both dependencies are external, so both are candidates for faking.

**Decision.** The LLM is always a double. MongoDB is real in integration tests,
and faked only for service-level unit tests.

**Why.** They fail differently. Faking the model buys determinism, no network, no
quota and no key in CI. Faking MongoDB buys nothing — it is deterministic, free
and offline in a container — while hiding exactly the bugs the adapter can have:
wrong query syntax, an index that is not used, dates that come back in an
unexpected type.

**When this would NOT apply.** If the datastore were a managed cloud service with
no local equivalent, a fake plus a small contract test suite would be the
pragmatic answer.

---

## The frontend is built and served by nginx, on one port

**Context.** The usual development setup runs Vite on one port and the API on
another, with CORS between them.

**Decision.** One container serves the built static files and proxies `/api` to
the backend. One port, no CORS.

**Why.** The brief requires `docker compose up` with no extra steps. Two ports
means explaining two URLs and configuring CORS for a reviewer who only wants to
see the chat work. Hot reload is a development convenience and does not belong in
the path someone uses to evaluate the project.

**When this would NOT apply.** If the frontend were the main deliverable, the
development experience would matter more than the reviewer's first run.

---

## Architecture rules are enforced by CI, not by convention

**Context.** Layered architecture tends to erode: a service imports an adapter
"just this once" and the boundary is gone.

**Decision.** Three `import-linter` contracts run in CI — layers point inward,
`services` cannot import `adapters`/`api`/`core`, and `domain` imports nothing
else in the project.

**Why.** A rule that only exists in a README is a suggestion. This one fails the
build, which means the architecture described here is the architecture that is
actually there.

**When this would NOT apply.** In a small script or a genuine prototype, the
contracts cost more than the drift they prevent.
