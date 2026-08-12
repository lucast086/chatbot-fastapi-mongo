# Conversation flow — Spec

**Location**: `app/services/chat_service.py`
**Status**: `in-progress`
**Last updated**: 2026-08-12

Written before the code that implements it. This describes WHAT the conversation
flow does and WHY, in behaviour terms — never how. The code describes how.

---

## Business purpose

Someone types a message and gets an answer from a language model, and the
exchange survives so the conversation can be picked up later. This is the
product; everything else in the system exists to support it.

Provider failures are part of this spec rather than a separate concern. Free-tier
models are rate limited and occasionally retired, so a failed generation is a
normal operating state, not an exception — and what the user is told when it
happens is part of what the flow does.

---

## Behavior

- **Given** a conversation and a non-empty message, **When** the user sends it,
  **Then** the model answers, and the question and the answer are stored
  together as one turn and returned to the caller.

- **Given** a conversation that already has messages, **When** the user sends
  another, **Then** the model receives the most recent messages as context, up
  to a configured limit, so the exchange reads as a conversation rather than
  isolated questions.

- **Given** a conversation with no messages yet, **When** the first turn
  completes, **Then** the conversation is named after that first message, so it
  can be told apart from others in the list.

- **Given** the model provider fails for any reason, **When** the user sends a
  message, **Then** nothing at all is persisted — the conversation is left
  exactly as it was, with no unanswered question stored.

- **Given** a provider failure, **When** the caller receives the error, **Then**
  it names the specific cause, states whether retrying can help, and links to
  the matching troubleshooting section.

- **Given** no API key is configured, **When** the user sends a message,
  **Then** the failure is reported as a missing key before any network call is
  attempted, and the rest of the application continues to work normally.

---

## Decisions made

**A turn is atomic.** The model is called first and the writes happen after, so
a failure leaves nothing behind. The alternative — storing the question first —
creates conversations that end in an unanswered message, and a retry path that
needs an idempotency key to avoid duplicating it. Not writing removes both.

**The history window is a message count, not a token budget.** Simpler, and
adequate at this scale. A token budget is the honest next step.

**The first-message title is not model-generated.** It uses data already in hand,
costs nothing and cannot fail. Since the title is the only thing distinguishing
conversations in the list, the list must not depend on a network call.

**Provider failures are five distinct outcomes, not one.** The backend knows
which occurred, and only some are worth retrying. See `docs/decisions.md`.

---

## Integration

**Consumes**
- A conversation store, for reading history and writing a completed turn. It is
  expected to store both messages of a turn as one indivisible write.
- A language model, given an ordered list of messages, streaming its answer back
  in fragments. It is expected to raise typed provider errors and never leak the
  provider SDK's own exception types.

**Guarantees to callers**
- A successful response contains the stored question, the stored answer, and the
  updated conversation.
- A failure never leaves a partial turn behind. Re-sending the same message after
  a failure is safe and produces exactly one turn.
- Every error carries a machine-readable cause, whether retrying can help, and a
  documentation link.
- Answering a message moves its conversation to the top of the list.

---

## Edge cases

| Case | Expected behaviour |
|---|---|
| Message is empty or only whitespace | Rejected before any model call, as a validation failure |
| Message exceeds the maximum length | Rejected as a validation failure, naming the limit |
| Conversation does not exist | Reported as not found; nothing is created implicitly |
| Provider rate limits us | Reported as retryable, passing the provider's own wait time through when it sent one, and omitting it rather than guessing when it did not |
| Configured model has been retired | Reported as a configuration problem and explicitly **not** retryable, naming the model |
| Provider returns an empty answer | Treated as a failed turn — an empty assistant message is stored nowhere |
| Conversation is longer than the history window | Only the most recent messages are sent; the stored history stays complete |

---

## Verification criteria

- [ ] A successful turn stores exactly two messages, question before answer
- [ ] A successful turn returns both messages and the updated conversation
- [ ] The conversation's last-activity time advances, moving it to the top of the list
- [ ] The first turn sets the conversation's title from the user's message
- [ ] A later turn does not overwrite an existing title
- [ ] The model receives at most the configured number of previous messages
- [ ] The model receives them oldest first
- [ ] A provider failure stores nothing: the message count is unchanged
- [ ] Re-sending the same message after a failure produces exactly one turn
- [ ] Each provider failure maps to its own cause and retryable flag
- [ ] A missing API key is reported without attempting a network call
- [ ] A rate limit passes the provider's wait time through when present
- [ ] An empty or whitespace-only message is rejected before any model call
- [ ] Sending to an unknown conversation is reported as not found
- [ ] An empty answer from the provider does not produce a stored turn
