/**
 * The whole UI. One file on purpose: the brief says the frontend only has to be
 * enough to try the chat, and splitting ~250 lines across a component tree
 * would be structure without a reader to serve.
 *
 * Two behaviours here are not cosmetic:
 *  - the provider banner is shown from /config on load, not after a failed
 *    message, so someone who forgot the API key learns it immediately;
 *  - a failed send keeps the text in the composer, because the backend stored
 *    nothing and re-sending is the retry.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  ChatApiError,
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
    const detail = await api.getConversation(id);
    setMessages(detail.messages);
  }

  async function startConversation() {
    const created = await api.createConversation();
    setConversations((current) => [created, ...current]);
    setActiveId(created.id);
    setMessages([]);
    setError(null);
  }

  async function removeConversation(id: string, event: React.MouseEvent) {
    event.stopPropagation();
    await api.deleteConversation(id);
    setConversations((current) => current.filter((c) => c.id !== id));
    if (activeId === id) {
      setActiveId(null);
      setMessages([]);
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
    }

    setSending(true);
    setError(null);
    try {
      const result = await api.sendMessage(conversationId, content);
      setMessages((current) => [...current, result.user_message, result.assistant_message]);
      // Clear only after the turn succeeded. The backend persisted nothing on
      // failure, so the text in the box is the retry.
      setDraft("");
      await refreshConversations();
    } catch (caught) {
      setError(caught as ChatApiError);
    } finally {
      setSending(false);
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
        {config && <footer className="model">{config.model}</footer>}
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
          {messages.length === 0 && !sending && (
            <p className="empty">Send a message to start.</p>
          )}
          {messages.map((message) => (
            <article key={message.id} className={`message ${message.role}`}>
              <span className="who">{message.role === "user" ? "You" : "Assistant"}</span>
              <p>{message.content}</p>
            </article>
          ))}
          {sending && <article className="message assistant pending">Thinking…</article>}
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
