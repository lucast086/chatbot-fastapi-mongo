# Scope and plan

Written before any code. The brief (`challenge.md`) defines the product in one
sentence — "you type a message, a model answers, the conversation is saved and can
be resumed" — and leaves the rest to me. This document records what I chose to
build, what I deliberately left out, and how I resolved the parts of the brief
that are ambiguous on purpose.

The reasoning behind individual technical choices lives in `decisions.md`. How I
worked with AI, including the suggestions I turned down, lives in `ai-usage.md`.

---

## In scope

| Feature | Why it is in |
|---|---|
| Send a message, get a model answer, persist the turn | This is the product. |
| Multiple conversations: create, list, open, delete | The brief says a conversation "can be resumed". Without a list there is no way to resume one. Delete keeps the UI usable while someone is trying the app. |
| Title derived from the first user message | The sidebar shows only the title, so without this the list is unreadable. |
| Bounded history window sent to the model | Without it the conversation grows without limit and eventually exceeds the context window. |
| Typed provider errors with a single error envelope | Free-tier models are rate limited; a 429 is a matter of when, not if. The backend already knows the cause, so it should say which one it was. |
| Degraded startup with no API key | The brief asks what should happen here. The app boots, everything except generation works, and generation returns a typed error — never a stack trace. |
| Persistence across container restarts | Explicit requirement. Named volume. |
| Minimal React UI, built and served by nginx behind `/api` | One port, no CORS, no second URL to explain. |
| Tests: unit with doubles, integration against a real MongoDB | Deterministic, no network, no quota consumed. |

## Deliberately out of scope

| Left out | Why |
|---|---|
| RAG, embeddings, vector search, document ingestion | The brief does not ask for it. It would be the most visible way to spend the 48 hours on something that is not being evaluated, at the cost of the chat itself. |
| Authentication and users | Not asked for. Adding it properly means sessions, password handling and an ownership model; adding it badly is worse than not adding it. How I would add it is described below. |
| Renaming a conversation | Titles are generated from the first message. I started to add a `PATCH` endpoint and cut it: I was justifying it with "it is only ten lines", which is not a reason to add a feature. |
| Last-message preview and message count in the sidebar | Showing them means either copying data onto the conversation document on every turn, or a lookup pipeline at read time. Neither is needed to decide which conversation to open. Dropping the requirement removed both. |
| Message editing, answer regeneration, conversation branching | Each one turns the message list into a tree. That is a mature chat product, not a minimal one. |
| Model picker in the UI | The model is configuration. The UI shows which one is active; choosing it is an environment variable. |
| Markdown rendering, syntax highlighting | The brief states explicitly that the frontend is not judged on design. |
| Our own rate limiting, metrics, tracing, deployment manifests | Production concerns for something that runs once on a reviewer's laptop. Listed in the README as what I would do with more time. |
| Cursor pagination, soft delete, audit trail | A simple `limit` and a hard delete are enough at this size, and the limit is documented. |
| Multi-document transactions | MongoDB runs standalone here, so they are not available. With the final data model they are not needed either — see `decisions.md`. |

### If authentication were added

`owner_id` on the conversation document, a compound index on
`(owner_id, updated_at)`, and one FastAPI dependency that resolves the caller and
filters every query. Nothing in the domain model or the service layer changes.
Leaving the hook visible without building it is the honest version of "out of
scope".

---

## Ambiguities in the brief, and how I resolved them

The brief says ambiguity is probably deliberate and should be resolved with
judgement and documented. These are the ones I found.

**1. One conversation or many? And who owns them?**
There is no notion of a user anywhere in the brief. I built many conversations
belonging to a single implicit user, with no authentication.

**2. Does the model receive conversation history, and how much?**
Not specified, but without history it is not a conversation. The last
`HISTORY_LIMIT` messages (default 20) are sent, configurable by environment
variable. This is a window by message count, not by tokens — a real token budget
is in the "with more time" list.

**3. Is there a system prompt?**
A short fixed one, configurable by environment variable. It is always sent and
does not count against the history window.

**4. If generation fails, is the user's message saved?**
No. The turn is atomic: validate, read history, call the model, then write both
messages in a single command. If the model call fails, nothing was written. The
consequence is that the text stays in the composer until the turn succeeds, and
retrying is simply sending the same request again.

**5. Two browser tabs writing to the same conversation.**
Last write wins, no locking. Messages are inserts, so they cannot overwrite each
other; the only field that competes is `updated_at`.

**6. What happens with no API key?**
The app starts. MongoDB, the UI, conversations and persistence all work. Only
generation returns an error, and the UI shows a banner explaining it when you
open the page — not after your first failed message.

**7. What counts as "no manual steps beyond the API key"?**
`docker compose up` from a clean clone, with no `.env` file present, has to work.
That rules out `env_file: .env` in the compose file, which fails outright when the
file does not exist. Defaults are declared inline instead.

**8. Which free model?**
OpenRouter's `:free` models rotate and get retired, so the model name is an
environment variable with a default rather than a hardcoded constant. The README
says how to change it and where to find the current list.

**9. Input limits.**
Message content is 1 to 8000 characters, validated by Pydantic. Empty or
whitespace-only messages are rejected with the same error envelope as everything
else.

**10. Timestamps.**
Always UTC, serialized as ISO-8601 with `Z`. The frontend formats to local time.

**11. Can conversations be deleted?**
The brief is silent. Yes — hard delete, cascading to the conversation's messages.

---

## Order of work

Documentation first, then the skeleton, then Docker — so that
`docker compose up` works early and cannot silently regress while the rest is
built. The canonical spec for the conversation flow is written and committed
before the code that implements it.

Two features are explicitly last, in this order, and are the first things cut if
time runs short:

1. **Streaming over SSE.** The LLM port is stream-shaped from the first commit, so
   this is a new endpoint plus frontend work rather than a change to the service
   layer.
2. **Model-generated conversation titles.** They replace the truncated first
   message, which already works. This improves the sidebar rather than enabling it.
