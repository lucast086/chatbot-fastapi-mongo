/**
 * The whole UI. One file on purpose: the brief says the frontend only has to be
 * enough to try the chat, and splitting ~250 lines across a component tree
 * would be structure without a reader to serve.
 *
 * Three behaviours here are not cosmetic:
 *  - the provider banner is shown from /config on load, not after a failed
 *    message, so someone who forgot the API key learns it immediately;
 *  - a failed send puts the text back in the composer, because the backend
 *    stored nothing and re-sending is the retry;
 *  - every async update is guarded on the conversation still being open.
 *    Switching conversations mid-turn used to paint the answer, and the
 *    leftover draft, into whichever thread happened to be on screen.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  ChatApiError,
  streamMessage,
  type AppConfig,
  type ConversationSummary,
  type Message,
} from "./api";

export default function App() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<ChatApiError | null>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  // Mirrors activeId for async callbacks. State read inside a promise that
  // started earlier is the value from that render, which is exactly the stale
  // read these guards exist to avoid.
  const activeIdRef = useRef<string | null>(null);

  useEffect(() => {
    api.getConfig().then(setConfig).catch(() => undefined);
    void refreshConversations();
  }, []);

  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight });
  }, [messages, sending]);

  const refreshConversations = useCallback(async () => {
    try {
      setConversations(await api.listConversations());
    } catch {
      // The sidebar failing to load must not take the composer down with it.
    }
  }, []);

  async function openConversation(id: string) {
    setActiveId(id);
    setError(null);
    setMessages([]);
    // A draft belongs to the conversation it was typed in. Carrying it over
    // means the next thing you send lands somewhere you did not write it.
    setDraft("");
    activeIdRef.current = id;

    const detail = await api.getConversation(id);
    // Two quick clicks race: whichever fetch resolves last would otherwise win
    // and paint its messages under a sidebar that says something else.
    if (activeIdRef.current !== id) return;
    setMessages(detail.messages);
  }

  async function startConversation() {
    const created = await api.createConversation();
    setConversations((current) => [created, ...current]);
    setActiveId(created.id);
    activeIdRef.current = created.id;
    setMessages([]);
    setDraft("");
    setError(null);
  }

  async function removeConversation(id: string, event: React.MouseEvent) {
    event.stopPropagation();
    await api.deleteConversation(id);
    setConversations((current) => current.filter((c) => c.id !== id));
    if (activeId === id) {
      setActiveId(null);
      activeIdRef.current = null;
      setMessages([]);
      setDraft("");
    }
  }

  async function send(event: React.FormEvent) {
    event.preventDefault();
    const content = draft.trim();
    if (!content || sending) return;

    let conversationId = activeId;
    if (!conversationId) {
      const created = await api.createConversation();
      setConversations((current) => [created, ...current]);
      conversationId = created.id;
      setActiveId(created.id);
      activeIdRef.current = created.id;
    }

    setSending(true);
    setError(null);
    // Cleared immediately: the message is already rendered in the thread, so
    // leaving it in the composer shows it twice. It comes back on failure,
    // which keeps "the text in the box is the retry" true where it matters.
    setDraft("");
    try {
      if (config?.streaming_enabled) {
        await sendStreaming(conversationId, content);
      } else {
        const result = await api.sendMessage(conversationId, content);
        if (activeIdRef.current === conversationId) {
          setMessages((current) => [...current, result.user_message, result.assistant_message]);
        }
      }
      await refreshConversations();
    } catch (caught) {
      setError(caught as ChatApiError);
      if (activeIdRef.current === conversationId) setDraft(content);
    } finally {
      setSending(false);
    }
  }

  async function sendStreaming(conversationId: string, content: string) {
    const userMessage: Message = {
      id: `local-${Date.now()}`,
      role: "user",
      content,
      created_at: new Date().toISOString(),
    };
    const pendingId = `local-${Date.now()}-a`;

    // Every update below is guarded on the conversation still being open.
    // Without this, a turn started in one conversation keeps writing into
    // whatever thread the user switched to — the answer to a question they
    // asked somewhere else appears under an unrelated one.
    const stillHere = () => activeIdRef.current === conversationId;

    setMessages((current) => [
      ...current,
      userMessage,
      { id: pendingId, role: "assistant", content: "", created_at: userMessage.created_at },
    ]);

    let failure: ChatApiError | null = null;
    await streamMessage(conversationId, content, {
      onChunk: (text) => {
        if (!stillHere()) return;
        setMessages((current) =>
          current.map((m) => (m.id === pendingId ? { ...m, content: m.content + text } : m)),
        );
      },
      onDone: ({ model }) => {
        if (!stillHere()) return;
        // The answering model is only known when the stream closes, since the
        // backend may have fallen through to a later one.
        setMessages((current) => current.map((m) => (m.id === pendingId ? { ...m, model } : m)));
      },
      onError: (caught) => {
        failure = caught;
      },
    });

    if (failure) {
      // The backend stored nothing, so the optimistic pair has to come back out
      // rather than sit there looking persisted.
      if (stillHere()) {
        setMessages((current) =>
          current.filter((m) => m.id !== pendingId && m.id !== userMessage.id),
        );
      }
      throw failure;
    }
  }

  const providerMissing = config !== null && !config.provider_configured;

  return (
    <div className="app">
      <aside className="sidebar">
        <button className="new" onClick={startConversation}>
          + New conversation
        </button>
        <ul>
          {conversations.map((conversation) => (
            <li
              key={conversation.id}
              className={conversation.id === activeId ? "active" : ""}
              onClick={() => openConversation(conversation.id)}
            >
              <span title={conversation.title}>{conversation.title}</span>
              <button
                className="delete"
                aria-label={`Delete ${conversation.title}`}
                onClick={(event) => removeConversation(conversation.id, event)}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
        {config && (
          <footer className="model" title={config.models.join("\n")}>
            {config.models.length === 1
              ? config.models[0]
              : `${config.models[0]} +${config.models.length - 1} fallback`}
          </footer>
        )}
      </aside>

      <main>
        {providerMissing && (
          <div className="banner warning">
            <strong>No API key configured.</strong> Conversations and history work,
            but messages cannot be answered. Set <code>OPENROUTER_API_KEY</code> and
            restart — see the{" "}
            <a href={config.docs_url} target="_blank" rel="noreferrer">
              README
            </a>
            .
          </div>
        )}

        <div className="thread" ref={threadRef}>
          {messages.length === 0 && <p className="empty">Send a message to start.</p>}
          {messages.map((message) => (
            <article key={message.id} className={`message ${message.role}`}>
              <span className="who">
                {message.role === "user" ? "You" : "Assistant"}
                {message.model && <em className="by"> · {message.model}</em>}
              </span>
              <p>{message.content || (message.role === "assistant" ? "Thinking…" : "")}</p>
              {message.truncated && (
                <p className="truncated">
                  This answer hit the output limit and is cut off. Raise
                  <code> MAX_OUTPUT_TOKENS</code> or ask for something shorter.
                </p>
              )}
            </article>
          ))}

        </div>

        {error && (
          <div className="banner error">
            <strong>{error.detail.message}</strong>
            {error.detail.retryable && (
              <>
                {" "}
                <button onClick={send}>Retry</button>
                {error.retryAfterSeconds !== null && (
                  <span> (suggested wait: {error.retryAfterSeconds}s)</span>
                )}
              </>
            )}
            {error.detail.docs_url && (
              <>
                {" "}
                <a href={error.detail.docs_url} target="_blank" rel="noreferrer">
                  What does this mean?
                </a>
              </>
            )}
          </div>
        )}

        <form className="composer" onSubmit={send}>
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) void send(event);
            }}
            placeholder="Type a message…"
            rows={2}
          />
          <button type="submit" disabled={sending || !draft.trim()}>
            {sending ? "Sending…" : "Send"}
          </button>
        </form>
      </main>
    </div>
  );
}
