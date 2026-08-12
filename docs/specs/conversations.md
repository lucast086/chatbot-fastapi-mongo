# Conversation flow — Spec

**Location**: `app/services/chat_service.py`
**Status**: `stable`
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
  to a configured limit — which counts the message being sent, so a limit of 1
  means no history at all — so the exchange reads as a conversation rather than
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

Each one names the test that covers it, so changing a behaviour here has an
obvious blast radius in the suite.

| # | Criterion | Covered by |
|---|---|---|
| 1 | A successful turn stores exactly two messages, question before answer | `test_a_turn_stores_exactly_two_messages_question_first` |
| 2 | A successful turn returns both messages and the updated conversation | `test_a_turn_returns_both_messages_and_the_conversation` |
| 3 | The conversation's last-activity time advances, moving it to the top of the list | `test_answering_moves_the_conversation_to_the_top`, `test_answering_moves_a_conversation_back_to_the_top_of_the_list` |
| 4 | The first turn sets the conversation's title from the user's message | `test_the_first_turn_titles_the_conversation_from_the_message` |
| 5 | A later turn does not overwrite an existing title | `test_a_later_turn_does_not_overwrite_the_title` |
| 6 | The window is exactly the configured size: the message being sent plus the most recent previous ones | `test_the_history_window_is_exactly_the_configured_size` |
| 7 | The model receives them oldest first | `test_the_model_receives_history_oldest_first`, `test_history_reaches_the_model_in_order_across_several_turns` |
| 8 | A provider failure stores nothing | `test_a_provider_failure_stores_nothing`, `test_a_failed_turn_leaves_nothing_in_the_database` |
| 9 | Re-sending the same message after a failure produces exactly one turn | `test_resending_after_a_failure_produces_exactly_one_turn`, `test_resending_after_a_failure_leaves_exactly_one_turn` |
| 10 | Each provider failure maps to its own cause and retryable flag | `test_each_provider_failure_has_its_own_status_and_reason`, `test_provider_failures_become_the_right_domain_error` |
| 11 | A missing API key is reported without attempting a network call | `test_no_api_key_raises_missing_api_key_without_calling_the_provider` |
| 12 | A rate limit passes the provider's wait time through when present | `test_a_rate_limit_passes_the_providers_own_retry_after_through`, `test_a_rate_limit_sets_retry_after`, `test_no_retry_after_header_when_the_provider_did_not_send_one` |
| 13 | An empty or whitespace-only message is rejected before any model call | `test_an_empty_message_is_rejected_before_any_model_call`, `test_an_empty_message_is_rejected_by_the_schema` |
| 14 | Sending to an unknown conversation is reported as not found | `test_sending_to_an_unknown_conversation_is_not_found`, `test_sending_to_an_unknown_conversation_is_404` |
| 15 | An empty answer from the provider does not produce a stored turn | `test_an_empty_answer_does_not_produce_a_stored_turn` |
| 16 | A generated title never costs a turn | `test_a_failed_title_leaves_the_derived_one_in_place`, `test_titles_are_only_generated_for_the_first_turn` |
| 17 | A streamed turn is persisted only when the stream completes | `test_a_streamed_turn_is_persisted_when_the_stream_completes`, `test_a_failure_during_generation_persists_nothing` |
| 18 | A pre-flight failure on the stream route keeps a real status code | `test_a_failure_before_the_stream_opens_is_a_real_status_code`, `test_an_invalid_message_is_a_real_status_code` |

**Result: 18 of 18 mapped.** Criteria 3, 7, 8 and 9 are covered twice on
purpose — once against a fake store and once against a real MongoDB, because a
fake can satisfy the service's expectations while the adapter does not.
