import { storeSessionId } from "./session";

export type ServerEventType =
  | "connected"
  | "message_received"
  | "message_queued"
  | "agent_started"
  | "agent_handoff"
  | "tool_started"
  | "tool_completed"
  | "response_delta"
  | "response_completed"
  | "response_retracted"
  | "request_cancelled"
  | "escalation"
  | "error";

export interface ServerEvent {
  type: ServerEventType;
  [key: string]: unknown;
}

export type ConnectionStatus = "connecting" | "open" | "closed";

type EventListener = (event: ServerEvent) => void;
type StatusListener = (status: ConnectionStatus) => void;

const RECONNECT_BASE_DELAY_MS = 1000;
const RECONNECT_MAX_DELAY_MS = 10000;

/**
 * Thin client over the backend's WebSocket protocol (backend/websocket/events.py).
 * Owns: anonymous session_id persistence, auto-reconnect with backoff,
 * heartbeat pong replies, and resending a message that was sent but never
 * acked (message_received) before an unexpected disconnect.
 */
export class ChatSocket {
  private ws: WebSocket | null = null;
  private readonly baseUrl: string;
  private sessionId: string | null;
  // Spec 12.1: signed session token, required on every (re)connect once the
  // backend has SESSION_SECRET configured. The same token is reused across
  // reconnects within its 24h lifetime — this class never refreshes it.
  private readonly token: string | null;
  private readonly eventListeners = new Set<EventListener>();
  private readonly statusListeners = new Set<StatusListener>();
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private manuallyClosed = false;
  private pendingMessage: { messageId: string; content: string } | null = null;

  constructor(baseUrl: string, sessionId: string | null, token: string | null = null) {
    this.baseUrl = baseUrl;
    this.sessionId = sessionId;
    this.token = token;
  }

  onEvent(listener: EventListener): () => void {
    this.eventListeners.add(listener);
    return () => this.eventListeners.delete(listener);
  }

  onStatusChange(listener: StatusListener): () => void {
    this.statusListeners.add(listener);
    return () => this.statusListeners.delete(listener);
  }

  connect(): void {
    this.manuallyClosed = false;
    this.emitStatus("connecting");

    const params = new URLSearchParams();
    if (this.sessionId) params.set("session_id", this.sessionId);
    if (this.token) params.set("token", this.token);
    const query = params.toString();
    const url = query ? `${this.baseUrl}?${query}` : this.baseUrl;
    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      this.reconnectAttempts = 0;
      this.emitStatus("open");
      if (this.pendingMessage) {
        this.sendRaw({
          type: "user_message",
          message_id: this.pendingMessage.messageId,
          content: this.pendingMessage.content,
        });
      }
    };

    this.ws.onmessage = (event: MessageEvent<string>) => {
      const data = JSON.parse(event.data) as ServerEvent & { session_id?: string; message_id?: string };

      if (data.type === "connected" && data.session_id) {
        this.sessionId = data.session_id;
        storeSessionId(data.session_id);
      }
      if (data.type === "message_received") {
        this.pendingMessage = null;
      }
      if ((data as { type: string }).type === "ping") {
        this.sendRaw({ type: "pong" });
        return;
      }

      this.eventListeners.forEach((listener) => listener(data));
    };

    this.ws.onclose = () => {
      this.emitStatus("closed");
      if (!this.manuallyClosed) this.scheduleReconnect();
    };

    this.ws.onerror = () => {
      this.ws?.close();
    };
  }

  sendUserMessage(content: string): void {
    const messageId = crypto.randomUUID();
    this.pendingMessage = { messageId, content };
    this.sendRaw({ type: "user_message", message_id: messageId, content });
  }

  /** Phase 15 (spec 12.4): ask the server to discard the in-flight response.
   *  The LLM call is not forcibly aborted — the response is dropped once the
   *  stream completes and a request_cancelled event is sent. */
  sendCancel(): void {
    this.sendRaw({ type: "cancel_request" });
  }

  close(): void {
    this.manuallyClosed = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
  }

  private scheduleReconnect(): void {
    const delay = Math.min(RECONNECT_BASE_DELAY_MS * 2 ** this.reconnectAttempts, RECONNECT_MAX_DELAY_MS);
    this.reconnectAttempts += 1;
    this.reconnectTimer = setTimeout(() => this.connect(), delay);
  }

  private sendRaw(payload: Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(payload));
    }
  }

  private emitStatus(status: ConnectionStatus): void {
    this.statusListeners.forEach((listener) => listener(status));
  }
}
