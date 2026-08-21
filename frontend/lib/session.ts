const SESSION_STORAGE_KEY = "support_chat_session_id";

/**
 * The client never mints its own session_id — the server does, on first
 * `connected` (see backend/websocket/handler.py). This just persists
 * whatever the server assigned so a reload/reconnect can send it back and
 * resume the same conversation instead of starting a new one.
 */
export function getStoredSessionId(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(SESSION_STORAGE_KEY);
}

export function storeSessionId(sessionId: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(SESSION_STORAGE_KEY, sessionId);
}
