# Chatbot — FastAPI + MongoDB

[![CI](https://github.com/lucast086/chatbot-fastapi-mongo/actions/workflows/ci.yml/badge.svg)](https://github.com/lucast086/chatbot-fastapi-mongo/actions/workflows/ci.yml)
[![Coverage Status](https://coveralls.io/repos/github/lucast086/chatbot-fastapi-mongo/badge.svg?branch=main)](https://coveralls.io/github/lucast086/chatbot-fastapi-mongo?branch=main)

You type a message, a language model answers, and the conversation is persisted
so it can be resumed later.

**In a hurry?** [Run it](#run-it) is three commands.
**Here to review?** [Decisions and trade-offs](#decisions-and-trade-offs) and
[AI usage](#ai-usage) are the parts worth your time.

---

## Contents

- [Run it](#run-it) · [without the script](#or-without-the-script) · [try it](#try-it) · [if you skip the key](#if-you-skip-the-key)
- [What it does](#what-it-does) — and [what it deliberately does not](#what-it-deliberately-does-not-do)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting) — one section per error `reason`
- [Development](#development) — [architecture](#architecture), [project layout](#project-layout)
- [Decisions and trade-offs](#decisions-and-trade-offs) — and [with more time](#with-more-time)
- [AI usage](#ai-usage)
- [Documentation](#documentation)

---

## Tech stack

| Layer | Choice | Why, in one line |
|---|---|---|
| Language | Python 3.13, managed by `uv` | One tool for the interpreter and the lock file, no `sudo` to reproduce |
| API | FastAPI | Required by the brief |
| Database | MongoDB, via `pymongo`'s `AsyncMongoClient` | Required by the brief. Not `motor` — it is deprecated and the async driver now ships inside `pymongo` |
| Model provider | OpenRouter, through the OpenAI SDK | OpenAI-compatible, so the adapter works against any such endpoint including a local one |
| Frontend | React + Vite, built and served by nginx | One origin, no CORS, one URL to hand a reviewer |
| Tests | pytest, against a real MongoDB and a faked model | Faking the database would hide the bugs adapters actually have |
| Quality gates | ruff, mypy `--strict`, import-linter | The architecture is enforced by the build, not by review |
| CI | GitHub Actions | Native badge, checks visible where the code is |

---

## Run it

You need Docker with Compose v2. Nothing else.

```bash
git clone https://github.com/lucast086/chatbot-fastapi-mongo.git
cd chatbot-fastapi-mongo
./scripts/start.sh
```

It asks for an API key — paste one, and you have a working chatbot in a single
pass. **Get a free key at <https://openrouter.ai/keys>**; no card is required
for the `:free` models this project defaults to. **The input is hidden, and a key
passed as `--key` instead would end up in your shell history.**

Then open **<http://localhost:8080>**.

### Or without the script

The script only sets the key and calls Compose. Nothing depends on it:

```bash
cp .env.example .env     # then put your key in OPENROUTER_API_KEY
docker compose up
```

### Try it

Chat in the browser, or from the terminal:

```bash
# create a conversation
curl -X POST http://localhost:8080/api/v1/conversations \
  -H 'Content-Type: application/json' -d '{}'

# send a message (use the id from above)
curl -X POST http://localhost:8080/api/v1/conversations/<id>/messages \
  -H 'Content-Type: application/json' \
  -d '{"content":"What is the difference between guanciale and pancetta?"}'
```

Interactive API docs: <http://localhost:8000/docs>.

**Check that it persists:** send a message, then `docker compose down &&
docker compose up -d`, reload the page. The conversation is still there.
`docker compose down -v` is what wipes it.

### If you skip the key

Press Enter at the prompt, or run `docker compose up` with no `.env` at all.
The app starts, MongoDB starts, the UI loads, and you can create, list and
delete conversations. Only answering messages fails, and it says so with a
banner when the page opens rather than after you have typed something.

This is deliberate — a missing key is a configuration state, not a crash — and
it is why `/health/ready` returns 200 with `"status": "degraded"` instead of
failing. See [`missing_api_key`](#troubleshooting-missing-api-key).

---

## What it does

- Multiple conversations: create, list, open, delete
- Answers with conversation history as context, bounded by a configurable window
- Conversations are named from the first message, then renamed by the model
- Several free models tried in order, so a rate limit on one does not stop you
  — every answer says which model produced it
- Answers stream token by token over server-sent events
- Typed provider errors with a single response envelope and a retry hint
- Runs and stays usable with no API key configured
- Conversations survive `docker compose down` + `up`

### What it deliberately does not do

Retrieval-augmented generation, authentication, message editing, answer
regeneration, conversation renaming by hand, or a model picker in the UI. Each
was considered and cut; the reasoning is in [`docs/plan.md`](docs/plan.md).

---

## Configuration

Every variable has a working default. The API key is the only exception, and its
absence degrades the app rather than stopping it.

| Variable | Default | What it does |
|---|---|---|
| `OPENROUTER_API_KEY` | *(empty)* | The only one without a usable default |
| `OPENROUTER_MODELS` | three free models | Comma separated, tried in order. See [rate limits](#troubleshooting-rate-limited) |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | Any OpenAI-compatible endpoint, including a local one |
| `FIRST_TOKEN_TIMEOUT_SECONDS` | `20` | How long to wait for a model's first token before trying the next |
| `HISTORY_LIMIT` | `20` | How many messages are sent as context |
| `MAX_HISTORY_CHARS` | `24000` | Ceiling on the whole prompt. Oldest messages are dropped to fit, rather than letting the provider reject it |
| `GENERATE_TITLES` | `true` | One extra call after the first turn. `false` halves what a first turn costs |
| `WEB_PORT` | `8080` | The port you open |
| `API_PORT` | `8000` | Published for Swagger UI and curl; not needed to use the app |
| `MONGO_PORT` | `27017` | Published for `mongosh`; not needed either |
| `SYSTEM_PROMPT` | a one-line instruction | Prepended to every request. Change it to change the assistant's behaviour |
| `MAX_MESSAGE_LENGTH` | `8000` | Longest message accepted, in characters. Enforced by the service, so raising it works |
| `MAX_OUTPUT_TOKENS` | `2048` | Cap on an answer's length |
| `REQUEST_TIMEOUT_SECONDS` | `60` | Overall timeout for one model call |
| `MONGO_DB` | `chatbot` | Database name |
| `APP_ENV` / `LOG_LEVEL` | `development` / `INFO` | |

Using a different provider only needs `OPENROUTER_BASE_URL` and
`OPENROUTER_MODELS` — the adapter talks the OpenAI wire format, so a local
Ollama or LM Studio works without a code change.

---

## Troubleshooting

Every error response carries a `docs_url` pointing at the matching section here.

```json
{
  "reason": "rate_limited",
  "message": "The model provider is rate limiting requests. Try again shortly.",
  "retryable": true,
  "docs_url": "…#troubleshooting-rate-limited"
}
```

### troubleshooting-missing-api-key

**503.** No key is configured. Everything except generation works — this is the
expected state on a fresh clone, not a fault.

`cp .env.example .env`, set `OPENROUTER_API_KEY`, then `docker compose up -d`.

### troubleshooting-invalid-credentials

**502.** The provider rejected the key. Retrying will not help. Check for a
truncated paste or stray quotes, and that the key is still active at
<https://openrouter.ai/keys>. A key that is valid but has no access to the
configured model reports the same way — the fix is the same, correct the
configuration.

### troubleshooting-rate-limited

**429**, and you should rarely see it. Free models are rate limited *per
model*, so when one refuses, the next in `OPENROUTER_MODELS` is tried
automatically — that is what the model name under each answer is telling you.

This error only appears when **every** configured model is limited at once. Wait
for the suggested time, or add another model from
<https://openrouter.ai/models?q=free> to the list.

Nothing was saved. Your message is still in the composer, and sending it again
is the retry.

### troubleshooting-model-unavailable

**502.** Every configured model is gone or no longer free. A single retired
model is skipped automatically and the next one is tried, so this means the
whole list has aged out — likely if you run this repository long after it was
written.

Pick current ones from <https://openrouter.ai/models?q=free> and set
`OPENROUTER_MODELS`. The error message includes the provider's own suggestion
when it offers one.

### troubleshooting-provider-unavailable

**504.** A timeout, a connection failure, or an error on the provider's side.
Retryable. If it persists, check <https://status.openrouter.ai>.

### troubleshooting-not-found

**404.** The conversation does not exist — usually a stale browser tab pointing
at something that was deleted. Reload.

### troubleshooting-validation-error

**422.** The message was empty, whitespace only, or longer than 8000 characters.

### troubleshooting-client-error

**400 or 405.** The request itself was wrong — usually the wrong HTTP verb on a
valid path. The `Allow` header lists what that path accepts. Not a fault in the
application.

### troubleshooting-internal-error

**500.** Something the application did not anticipate. This one is a bug rather
than a configuration problem — `docker compose logs api` will have the
traceback, which is deliberately not sent in the response.

### Other problems

**I set the key but the banner still says no key.** Almost always this:
`docker compose restart` does **not** re-read `.env`. Restarting reuses the
container with the environment it was created with. Use `docker compose up -d`
instead — it notices the configuration changed and recreates the container.

```bash
docker compose exec api sh -c 'echo $OPENROUTER_API_KEY'   # what it actually has
```

**Port already in use.** Set `WEB_PORT`, `API_PORT` or `MONGO_PORT` in `.env`.

**The page loads but nothing works.** Check `curl
http://localhost:8080/health/ready`. `"status":"unavailable"` means MongoDB is
not reachable; `docker compose logs mongo` will say why.

**Conversations disappeared.** `docker compose down -v` removes the volume.
Plain `down` does not.

---

## Development

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # if you do not have uv
uv sync
```

| Script | What it does, and why it exists |
|---|---|
| `./scripts/start.sh` | Sets the API key and brings the stack up in one pass. A wrapper around Compose, not a dependency. |
| `./scripts/test.sh` | Runs the suite. Starts MongoDB first and stops it again **only if this script started it**, so it does not kill a session you already had open. |
| `./scripts/lint.sh` | Exactly the checks the CI `quality` job runs — ruff, `mypy --strict`, import-linter — so you find a failure here instead of on a pull request. |

Tests need neither an API key nor a network. The one test that talks to the real
provider is marked `live`, skipped without a key, and excluded from CI:

```bash
uv run pytest -m live    # needs OPENROUTER_API_KEY
```

### Architecture

Ports and adapters. Dependencies point inward, and the arrow never reverses:

```
        api ──▶ services ──▶ domain ◀── adapters
                                 ▲
                               core (wires the two sides together)
```

| Layer | Knows about | Never knows about |
|---|---|---|
| `api` | HTTP, services, domain | MongoDB, OpenRouter |
| `services` | domain ports | any concrete implementation, HTTP |
| `domain` | nothing else in the project | everything |
| `adapters` | domain | HTTP, services, configuration |
| `core` | all of it — the composition root | — |

**Four `import-linter` contracts enforce this in CI**, not by convention. The
build fails if any is broken, which is what makes the table above a fact rather
than an intention.

The fourth one — `adapters` may only know the domain — was added after an AI
review pointed out that the first three left the adapter ring completely
unconstrained: an adapter importing `app.api.errors`, the textbook violation,
passed all of them. Verified by introducing exactly that import and watching CI
stay green.

### Project layout

```
app/
├── api/
│   ├── errors.py              Domain errors → HTTP. The one error envelope.
│   ├── schemas.py             Pydantic wire models. Never reach the domain.
│   └── routers/
│       ├── conversations.py   CRUD + the JSON message endpoint
│       └── streaming.py       The SSE variant
├── services/
│   ├── chat_service.py        The turn lifecycle. See docs/specs/.
│   └── conversation_service.py
├── domain/
│   ├── models.py              Frozen dataclasses. No Pydantic, no bson.
│   ├── errors.py              The provider error taxonomy
│   └── ports/                 Protocols: the store and the model
├── adapters/
│   ├── mongo/                 Connection, indexes, the conversation store
│   └── openrouter/            The model client and the fallback chain
├── core/
│   ├── config.py              pydantic-settings; every value has a default
│   └── dependencies.py        The only module importing both ports and adapters
└── main.py                    Lifespan, health checks, /config

frontend/                      React + Vite, built and served by nginx
tests/
├── adapters/                  Against a real MongoDB; the model is faked
├── api/                       HTTP contract: status codes, the envelope
├── services/                  Business logic against doubles
└── test_spec_traceability.py  Fails if the spec names a test that does not exist
docs/
├── plan.md                    Scope, and the brief's ambiguities resolved
├── decisions.md               One entry per decision, each argued against itself
├── ai-usage.md                Tooling, and every rejected suggestion
└── specs/conversations.md     Behaviour spec, written before the code
```

---

## Decisions and trade-offs

The reasoning behind every non-obvious choice, each with the case where it would
be the wrong call, is in [`docs/decisions.md`](docs/decisions.md). The four that
shape the system most:

**A failed generation persists nothing.** The model is called first and both
messages are written afterwards in a single command. The alternative — saving
the question first — produces conversations ending in an unanswered message and
needs an idempotency key so retrying does not duplicate it. Not writing removes
both problems. The cost is that a client disconnecting mid-stream loses that
turn.

**No transactions, and none needed.** MongoDB runs standalone, so multi-document
transactions are unavailable. What protects the history is the order of
operations, not a transaction: the only write left outside the atomic pair is
the conversation's last-activity timestamp, whose worst case is one row briefly
out of order in the sidebar.

**The sidebar shows titles only.** Adding a message preview means either copying
data onto the conversation on every turn, or a lookup pipeline at read time.
Dropping the requirement removed both instead of choosing between them.

**Five provider errors, not one.** The backend knows which failure occurred and
only some are worth retrying, so `retryable` in the envelope carries that and
the frontend needs no table of status codes. The fifth,
[`model_unavailable`](#troubleshooting-model-unavailable), was added after a
live test caught the default model in this repository having already been
retired — four categories looked complete until something real disagreed.

### With more time

- A token-based history budget instead of a message count. The window is the
  first thing that breaks on long conversations with a small context model.
- Token usage and finish-reason accounting. A port typed `AsyncIterator[str]`
  has nowhere to carry them, so a truncated answer is indistinguishable from a
  complete one and there is no cost visibility. Fixing it means a terminal
  metadata frame on the port — the honest change rather than fields nothing
  populates, which is what was there before and got removed.
- Serialised writes per conversation. Two turns sent at once interleave; see
  `docs/plan.md` ambiguity 5 for exactly what competes.
- Refreshing the model list from OpenRouter's `/api/v1/models` on a schedule
  instead of hardcoding it. The hardcoded list skips retired models rather
  than breaking, which gets most of the benefit — but it still ages.
- Cursor pagination on the message list. Loading an entire conversation is fine
  at this size and will not stay fine.
- A frontend test suite. There is none: the backend is what the brief says it
  cares about, and with the clock running that is where the tests went.
- Metrics and request ids. The logs already say which model answered, how long
  it took to the first token, and why any earlier one was skipped — enough to
  debug a turn, not enough to answer "how often does the first model fail?"
  without grepping. That is a Prometheus counter and a histogram; it is
  infrastructure for something that runs once on a reviewer's laptop, which is
  why it is here rather than in the code.
- Evaluating answer *quality*. There are golden tests for the request — the
  system prompt goes first, history is in order, both roles are included — and
  none for the response, deliberately: free models are non-deterministic, rate
  limited, and rotate through the fallback chain, so a scored eval set would be
  flaky and burn the quota the demo needs. The `live` test covers the only
  claim worth making here, that the integration works end to end.
- Trivy on the built images in CI, and a non-root nginx.
- Authentication: `owner_id` on the conversation, a compound index, and one
  dependency that filters every query. Nothing in the domain would change.

---

## AI usage

Which tools, where they helped, and — the part that actually says something —
seven suggestions I turned down and why:
[`docs/ai-usage.md`](docs/ai-usage.md).

The short version: the pattern in what I rejected is the AI optimising a
solution instead of questioning the requirement. The clearest case is the
sidebar, where two rounds of increasingly clever design disappeared the moment
someone asked why it needed to show anything beyond a title.

## Documentation

| Document | Contents |
|---|---|
| [`docs/plan.md`](docs/plan.md) | Scope, what was cut, and how the brief's ambiguities were resolved |
| [`docs/decisions.md`](docs/decisions.md) | One entry per decision: context, choice, reasoning, and when it would be wrong |
| [`docs/ai-usage.md`](docs/ai-usage.md) | Tooling, process, and every rejected suggestion |
| [`docs/specs/conversations.md`](docs/specs/conversations.md) | Behaviour spec for the conversation flow, written before the code, with each criterion mapped to its test |
| [`docs/challenge.md`](docs/challenge.md) | The original brief |
