# Chatbot — Claude Code Guide

## 1. Project

A chatbot: you type a message, a language model answers, and the conversation is
persisted so it can be resumed later. Built as a 48-hour take-home challenge, so
the bar is "small, tidy and well reasoned", not "large and half finished".

**Stack:** Python 3.13 · FastAPI · MongoDB · React + Vite (served by nginx) ·
OpenRouter through the OpenAI SDK.

**How it runs:** `docker compose up` from a clean clone. One port. Every
environment variable has a working default except the model provider API key.

---

## 2. Scope — CLOSED

This section is a constraint, not a summary. The scope was decided deliberately
and is not reopened while implementing. Rationale for each line lives in
`docs/decisions.md`.

**In:**

- Send a message, get a model answer, persist the turn
- Multiple conversations: create, list, open, delete
- Conversation title derived from the first user message
- Bounded history window sent to the model
- Typed provider-error taxonomy with a single error envelope
- Degraded startup with no API key (app boots, generation returns a typed error)
- Persistence across `docker compose down && up` (named volume)
- Minimal React UI, built and served by nginx behind `/api`

**DO NOT ADD** — each of these was considered and rejected:

| Do not add | Why |
|---|---|
| RAG, embeddings, vector search, document ingestion | Not asked for. Would take focus from the chat, which is what is evaluated. |
| Auth, users, `owner_id` | Not asked for. Document how it would be added; do not build it. |
| A rename-conversation endpoint | Titles are generated. Nothing needs renaming. |
| Last-message preview or message count in the sidebar | The sidebar shows the title only. Adding these reintroduces denormalization or a lookup pipeline for information nobody needs to pick a conversation. |
| Message editing, answer regeneration, conversation branching | Turns the data model into a tree. |
| A model picker in the UI | The model is configuration, not product. The UI shows which one is active. |
| Markdown rendering or syntax highlighting | The brief says the frontend is not judged on design. |
| Our own rate limiting, metrics, tracing, k8s manifests | Production infrastructure for something that runs once. |
| Cursor pagination, soft delete, audit trail | A simple `limit` and a hard delete are enough. |
| Multi-document transactions | MongoDB runs standalone here. See `docs/decisions.md`. |
| A devcontainer | Development tooling, not a deliverable. |

If something feels missing, check this table before proposing it. If it is not
here and not in "In", ask before building it.

---

## 3. Architecture

Ports and adapters, four layers, dependencies point inward:

```
api/       HTTP: routers, schemas, exception handlers
services/  business logic — knows ports, never implementations
domain/    entities, errors, Protocol ports. Pure Python.
adapters/  MongoDB, OpenRouter. The only place that knows a concrete technology.
core/      config and dependency wiring. The only module that imports both
           domain/ports and adapters.
```

These are enforced by `import-linter` in CI, not by convention:

1. Layers point inward: `api` → `services` → `domain`
2. `services` never imports `adapters`, `api` or `core`
3. `domain` imports nothing else in the project

The LLM port has exactly one method:

```python
class LLMPort(Protocol):
    def stream(self, messages: list[Message]) -> AsyncIterator[str]: ...
```

The JSON endpoint collapses the generator. This shape exists so adding SSE later
is a new endpoint, not a signature change across services.

---

## 4. Invariants

Break any of these and the design breaks with it.

- `domain/` imports nothing else in the project. `services/` never imports
  `adapters/`, `api/` or `core/`.
- Services raise `DomainError` subclasses. Never `HTTPException` — the
  translation to HTTP happens in one place, `api/exception_handlers.py`.
- The LLM port has exactly one method: `stream()`.
- **A failed generation persists nothing.** Call the model first, then write the
  turn as a single `insert_many([user_msg, assistant_msg])`.
- Every error response uses the same four-field envelope: `reason`, `message`,
  `retryable`, `docs_url`. Including 404 and 422.
- `/health/ready` returns **200** when only the API key is missing — the app is
  degraded, not broken. 503 is for MongoDB being unreachable.
- Timestamps are UTC, serialized as ISO-8601 with `Z`.
- Everything in this repository is written in **English**: code, comments,
  documentation, commit messages, API error messages and UI copy.

---

## 5. Commands

```bash
# TEST_COMMAND
poetry run pytest

# LINT_COMMAND
poetry run ruff format --check && poetry run ruff check && poetry run mypy && poetry run lint-imports
```

Run both before every commit. Live tests that hit the real provider are marked
`@pytest.mark.live` and are skipped unless `OPENROUTER_API_KEY` is set; they
never run in CI.

To run the app the way a reviewer will:

```bash
docker compose up
```

---

## 6. Conventions

- **Conventional Commits**: `<type>(<scope>): <description>`.
  Types: `feat` `fix` `refactor` `test` `docs` `chore` `build` `ci`.
- **Small, incremental commits.** The commit history is an explicit part of what
  is being evaluated. Do not squash a feature into one perfect commit, and do not
  batch unrelated changes together.
- Type hints everywhere; `mypy --strict` must pass.
- Credentials are `SecretStr` in settings and never logged.

---

## 7. Documentation map

| File | Purpose |
|---|---|
| `docs/challenge.md` | The original brief. Read-only reference. |
| `docs/plan.md` | Scope, what is deliberately out, and the ambiguities resolved. |
| `docs/decisions.md` | One entry per design decision: Context / Decision / Why / When this would NOT apply. |
| `docs/ai-usage.md` | How AI was used, and every suggestion that was rejected with its reason. |
| `docs/specs/conversations.md` | Canonical spec for the conversation flow: WHAT and WHY in Given/When/Then. Never HOW. |
| `README.md` | Setup, decisions, AI usage, troubleshooting. The `docs_url` anchors in error responses point here. |

`docs/specs/conversations.md` is the source of truth for the conversation flow's
observable behavior. If a change alters any Given/When/Then in it, update the
spec **before** the code, and make sure every behavior still maps to a test.

---

## 8. Standing triggers

These keep the two living documents honest. Do them at the moment, not at the end
— a rejection log reconstructed from memory on the last day is worthless and
reads that way.

```
A design decision is made          → append an entry to docs/decisions.md
A suggestion of yours is rejected  → append an entry to docs/ai-usage.md,
                                     with the reason it was rejected
A new provider error `reason`      → add the matching anchor section to README.md
                                     so its docs_url resolves
```
