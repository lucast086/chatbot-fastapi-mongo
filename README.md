# Chatbot — FastAPI + MongoDB

A chatbot: you type a message, a language model answers, and the conversation is
persisted so it can be resumed later.

**Stack:** Python 3.13 · FastAPI · MongoDB · React + Vite served by nginx ·
OpenRouter through the OpenAI SDK.

> **Status: in progress.** Setup instructions, the API reference and the
> troubleshooting guide land as the corresponding pieces are built. Scope and
> decisions are already documented below.

---

## Documentation

| Document | What is in it |
|---|---|
| [`docs/plan.md`](docs/plan.md) | What is in scope, what was deliberately left out and why, and how the ambiguities in the brief were resolved. |
| [`docs/decisions.md`](docs/decisions.md) | One entry per design decision: context, decision, reasoning, and when the same choice would be wrong. |
| [`docs/ai-usage.md`](docs/ai-usage.md) | Which AI tools were used and how — including every suggestion that was rejected, with the reason. |
| [`docs/challenge.md`](docs/challenge.md) | The original brief. |

## In short

Built: multiple conversations with create/list/open/delete, message turns
persisted to MongoDB, a bounded history window sent to the model, typed provider
errors with a single response envelope, and a startup path that works with no API
key configured — the app boots, everything except generation works, and it says
so instead of throwing a stack trace.

Deliberately not built: retrieval-augmented generation, authentication,
message editing, and conversation renaming. The reasoning for each is in
[`docs/plan.md`](docs/plan.md).
