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
}

export interface ConversationDetail extends ConversationSummary {
  model: string | null;
  messages: Message[];
}

export interface AppConfig {
  provider_configured: boolean;
  model: string;
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
