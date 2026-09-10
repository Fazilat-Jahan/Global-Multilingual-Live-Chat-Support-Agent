const SESSION_STORAGE_KEY = "support_chat_session_id";
const TOKEN_STORAGE_KEY = "support_chat_session_token";

/**
 * The client never mints its own session_id — the server does, via
 * POST /api/sessions/create (spec 12.1, see createSession() below). This
 * just persists whatever the server assigned so a reload/reconnect can send
 * it back and resume the same conversation instead of starting a new one.
 */
export function getStoredSessionId(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(SESSION_STORAGE_KEY);
}

export function storeSessionId(sessionId: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(SESSION_STORAGE_KEY, sessionId);
}

export function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_STORAGE_KEY);
}

export function storeToken(token: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
}

/** ws(s):// WebSocket URL -> matching http(s):// origin, for the plain HTTP
 *  session-creation call that must happen before the WebSocket upgrade. */
export function wsUrlToHttpBase(wsUrl: string): string {
  return wsUrl.replace(/^ws/, "http").replace(/\/ws\/chat\/?$/, "");
}

/**
 * Spec 12.1: mints a fresh session_id + signed HMAC token via
 * POST /api/sessions/create. Called once on widget open whenever there's no
 * stored session yet (or the stored one predates this feature and has no
 * token) — the WebSocket upgrade requires a valid token once the backend has
 * SESSION_SECRET configured; without one it just rejects the connection.
 */
export async function createSession(wsUrl: string): Promise<{ sessionId: string; token: string }> {
  const response = await fetch(`${wsUrlToHttpBase(wsUrl)}/api/sessions/create`, { method: "POST" });
  if (!response.ok) {
    throw new Error(`Failed to create session: ${response.status}`);
  }
  const data = (await response.json()) as { session_id: string; token: string; expires_at: string };
  storeSessionId(data.session_id);
  storeToken(data.token);
  return { sessionId: data.session_id, token: data.token };
}
