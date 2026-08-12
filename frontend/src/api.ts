/**
 * The API client.
 *
 * Every error the backend returns has the same four fields, so there is one
 * place that parses them and one shape the UI branches on. `retryable` is what
 * decides whether a retry button is worth offering — the UI never has to keep
 * its own table of which status codes are worth trying again.
 */

const BASE = "/api/v1";

export interface ApiError {
  reason: string;
  message: string;
  retryable: boolean;
  docs_url: string;
  /** Streaming path only: the header cannot be sent once the stream is open. */
  retry_after?: number;
}

export class ChatApiError extends Error {
  constructor(
    readonly detail: ApiError,
    readonly status: number,
    readonly retryAfterSeconds: number | null,
  ) {
    super(detail.message);
  }
}

export interface ConversationSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  /** Which model produced this answer. Null on user messages. */
  model?: string | null;
}

export interface ConversationDetail extends ConversationSummary {
  model: string | null;
  messages: Message[];
}

export interface AppConfig {
  provider_configured: boolean;
  /** Tried in order; the one that answers is reported per message. */
  models: string[];
  streaming_enabled: boolean;
  docs_url: string;
}

export interface SendMessageResult {
  user_message: Message;
  assistant_message: Message;
  conversation: ConversationSummary;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });

  if (!response.ok) {
    const retryAfter = response.headers.get("Retry-After");
    let detail: ApiError;
    try {
      detail = (await response.json()) as ApiError;
    } catch {
      // A response the backend did not produce — a proxy error page, say.
      // Falling back keeps the UI on one code path instead of crashing here.
      detail = {
        reason: "internal_error",
        message: `The server returned ${response.status}.`,
        retryable: response.status >= 500,
        docs_url: "",
      };
    }
    throw new ChatApiError(detail, response.status, retryAfter ? Number(retryAfter) : null);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  getConfig: () => request<AppConfig>("/config"),
  listConversations: () => request<ConversationSummary[]>("/conversations"),
  getConversation: (id: string) => request<ConversationDetail>(`/conversations/${id}`),
  createConversation: () =>
    request<ConversationSummary>("/conversations", {
      method: "POST",
      body: JSON.stringify({}),
    }),
  deleteConversation: (id: string) =>
    request<void>(`/conversations/${id}`, { method: "DELETE" }),
  sendMessage: (id: string, content: string) =>
    request<SendMessageResult>(`/conversations/${id}/messages`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),
};

/**
 * Server-sent events for a streamed answer.
 *
 * Pre-flight failures (unknown conversation, invalid message, missing key)
 * still arrive as a normal HTTP error, so they are thrown exactly like the JSON
 * route's. Only a failure that happens mid-generation comes back as an `error`
 * event — carrying the same four fields, so `onError` handles both.
 */
export async function streamMessage(
  conversationId: string,
  content: string,
  handlers: {
    onChunk: (text: string) => void;
    onDone: (info: { title: string; model: string | null }) => void;
    onError: (error: ChatApiError) => void;
  },
): Promise<void> {
  const response = await fetch(`${BASE}/conversations/${conversationId}/messages/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });

  if (!response.ok || !response.body) {
    const detail = (await response.json()) as ApiError;
    throw new ChatApiError(detail, response.status, null);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // Events are separated by a blank line. A chunk can split one in half, so
    // the tail stays in the buffer until its terminator arrives.
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";

    for (const block of blocks) {
      const nameLine = block.split("\n").find((l) => l.startsWith("event: "));
      const dataLine = block.split("\n").find((l) => l.startsWith("data: "));
      if (!nameLine || !dataLine) continue;
      const name = nameLine.slice(7);
      const data = JSON.parse(dataLine.slice(6));

      if (name === "chunk") handlers.onChunk(data.content as string);
      else if (name === "done")
        handlers.onDone({
          title: data.title as string,
          model: (data.model as string) ?? null,
        });
      else if (name === "error")
        handlers.onError(new ChatApiError(data as ApiError, 200, data.retry_after ?? null));
    }
  }
}
