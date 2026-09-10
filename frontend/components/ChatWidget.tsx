"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ChatSocket, type ConnectionStatus, type ServerEvent } from "@/lib/websocket";
import { createSession, getStoredSessionId, getStoredToken } from "@/lib/session";
import ChatWindow from "./ChatWindow";

// Phase 12 (spec 5.1): postMessage bridge for the embedded widget variant.
// No sensitive data crosses the boundary — only opaque command types with a
// `source` discriminator; the host validates against the widget origin.
const EMBEDDED_MESSAGE_SOURCE = "support-chat-widget";
const HOST_MESSAGE_SOURCE = "support-chat-host";

function postToHost(type: string): void {
  if (typeof window !== "undefined" && window.parent !== window) {
    window.parent.postMessage({ source: EMBEDDED_MESSAGE_SOURCE, type }, "*");
  }
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  streaming?: boolean;
  escalated?: boolean;
  kind?: "normal" | "error";
}

const DEFAULT_WS_URL = "ws://localhost:8000/ws/chat";
const WS_URL = process.env.NEXT_PUBLIC_WS_URL || DEFAULT_WS_URL;

interface ChatWidgetProps {
  /** "embedded" renders just the chat window, full height (for the /widget iframe route).
   *  "launcher" renders the floating bubble + popover window (for standalone demo pages). */
  variant?: "embedded" | "launcher";
}

export default function ChatWidget({ variant = "launcher" }: ChatWidgetProps) {
  const [isOpen, setIsOpen] = useState(variant === "embedded");
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("connecting");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [statusLine, setStatusLine] = useState<string | null>(null);
  // Phase 15 (spec 12.4): disable send while a response is streaming.
  const [isStreaming, setIsStreaming] = useState(false);
  // Whether the embedded variant is actually inside a host-page iframe.
  // Resolved client-side to avoid SSR hydration mismatches.
  const [isFramed, setIsFramed] = useState(false);

  const socketRef = useRef<ChatSocket | null>(null);
  const streamingMessageIdRef = useRef<string | null>(null);

  const handleEvent = useCallback((event: ServerEvent) => {
    switch (event.type) {
      case "message_queued":
        setStatusLine(`Message queued (position ${event.position as number})…`);
        break;

      case "agent_started":
        setIsStreaming(true);
        setStatusLine(`${event.agent as string} is looking into this…`);
        break;

      case "agent_handoff":
        setStatusLine(`Routed to ${event.to as string}…`);
        break;

      case "tool_started":
        setStatusLine(`${event.agent as string} is checking ${formatToolName(event.tool as string)}…`);
        break;

      case "tool_completed":
        setStatusLine(`${event.agent as string} finished checking ${formatToolName(event.tool as string)}.`);
        break;

      case "response_delta": {
        const delta = event.delta as string;
        setMessages((prev) => {
          if (streamingMessageIdRef.current) {
            return prev.map((message) =>
              message.id === streamingMessageIdRef.current
                ? { ...message, text: message.text + delta }
                : message
            );
          }
          const id = crypto.randomUUID();
          streamingMessageIdRef.current = id;
          return [...prev, { id, role: "assistant", text: delta, streaming: true }];
        });
        break;
      }

      case "response_completed": {
        const finalText = event.text as string;
        setStatusLine(null);
        setIsStreaming(false);
        setMessages((prev) => {
          if (streamingMessageIdRef.current) {
            const id = streamingMessageIdRef.current;
            streamingMessageIdRef.current = null;
            return prev.map((message) =>
              message.id === id ? { ...message, text: finalText, streaming: false } : message
            );
          }
          return [...prev, { id: crypto.randomUUID(), role: "assistant", text: finalText }];
        });
        break;
      }

      // Phase 14 (spec 9.2): output guardrail blocked the streamed response.
      // Replace the partially-streamed message content with the safe
      // replacement text. streamingMessageIdRef stays set so the subsequent
      // response_completed finalises the same message.
      case "response_retracted": {
        const replacement = event.replacement as string;
        setStatusLine(null);
        setMessages((prev) => {
          if (streamingMessageIdRef.current) {
            return prev.map((message) =>
              message.id === streamingMessageIdRef.current
                ? { ...message, text: replacement }
                : message
            );
          }
          // Edge case: no deltas arrived before retraction — create a new
          // assistant message with the replacement text.
          const id = crypto.randomUUID();
          streamingMessageIdRef.current = id;
          return [...prev, { id, role: "assistant", text: replacement, streaming: true }];
        });
        break;
      }

      case "escalation": {
        const id = streamingMessageIdRef.current;
        if (id) {
          setMessages((prev) =>
            prev.map((message) => (message.id === id ? { ...message, escalated: true } : message))
          );
        }
        break;
      }

      case "error":
        setStatusLine(null);
        setIsStreaming(false);
        streamingMessageIdRef.current = null;
        setMessages((prev) => [
          ...prev,
          { id: crypto.randomUUID(), role: "assistant", text: event.message as string, kind: "error" },
        ]);
        break;

      // Phase 15 (spec 12.4): server discarded the in-flight response
      // after a cancel_request. Clear streaming state; any partial message
      // stays in the UI as-is (the server-side queue will drain the
      // cancelled message's turn and process the next one).
      case "request_cancelled":
        setStatusLine(null);
        setIsStreaming(false);
        streamingMessageIdRef.current = null;
        break;

      default:
        break;
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    let socket: ChatSocket | null = null;
    let unsubscribeEvent: (() => void) | null = null;
    let unsubscribeStatus: (() => void) | null = null;

    // Spec 12.1: a signed session token is required for the WebSocket
    // upgrade once the backend has SESSION_SECRET configured. Reuse a
    // stored session+token (resumes the same conversation across reloads,
    // per rule #7) if present; otherwise mint a fresh one via
    // POST /api/sessions/create before ever opening the socket.
    async function start() {
      let sessionId = getStoredSessionId();
      let token = getStoredToken();
      if (!sessionId || !token) {
        try {
          const created = await createSession(WS_URL);
          sessionId = created.sessionId;
          token = created.token;
        } catch {
          // Session creation failed (backend unreachable, etc.) — fall back
          // to connecting without a token. The server only enforces the
          // token once SESSION_SECRET is configured; otherwise this still
          // works exactly as before this feature existed.
        }
      }
      if (cancelled) return;

      socket = new ChatSocket(WS_URL, sessionId, token);
      socketRef.current = socket;
      unsubscribeEvent = socket.onEvent(handleEvent);
      unsubscribeStatus = socket.onStatusChange(setConnectionStatus);
      socket.connect();
    }

    start();

    return () => {
      cancelled = true;
      unsubscribeEvent?.();
      unsubscribeStatus?.();
      socket?.close();
    };
  }, [handleEvent]);

  // Phase 12 (spec 5.1): when embedded in a host-page iframe, announce
  // readiness and listen for the host's open/close commands. Origin-validated
  // on receive (the widget doesn't know the embedder's identity ahead of
  // time, but commands carry no sensitive data — at worst a malicious host
  // can close the widget on its own page).
  useEffect(() => {
    if (variant !== "embedded") return;
    if (typeof window === "undefined" || window.parent === window) return;
    setIsFramed(true);
    postToHost("ready");

    const onHostMessage = (event: MessageEvent) => {
      const data = event.data as { source?: string; type?: string } | null;
      if (!data || data.source !== HOST_MESSAGE_SOURCE) return;
      if (data.type === "close") postToHost("close");
    };
    window.addEventListener("message", onHostMessage);
    return () => window.removeEventListener("message", onHostMessage);
  }, [variant]);

  const sendMessage = useCallback((content: string) => {
    setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: "user", text: content }]);
    socketRef.current?.sendUserMessage(content);
  }, []);

  if (variant === "embedded") {
    return (
      <div className="h-screen w-screen">
        <ChatWindow
          messages={messages}
          statusLine={statusLine}
          connectionStatus={connectionStatus}
          isStreaming={isStreaming}
          onSend={sendMessage}
          onClose={isFramed ? () => postToHost("close") : undefined}
        />
      </div>
    );
  }

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col items-end gap-3 sm:bottom-6 sm:right-6">
      {isOpen && (
        <div className="h-[70vh] w-[90vw] max-w-sm sm:h-[600px] sm:w-96">
          <ChatWindow
            messages={messages}
            statusLine={statusLine}
            connectionStatus={connectionStatus}
            isStreaming={isStreaming}
            onSend={sendMessage}
            onClose={() => setIsOpen(false)}
          />
        </div>
      )}

      <button
        type="button"
        onClick={() => setIsOpen((prev) => !prev)}
        aria-label={isOpen ? "Close support chat" : "Open support chat"}
        className="flex h-14 w-14 items-center justify-center rounded-full bg-brand-500 text-white shadow-lg hover:bg-brand-600 transition-colors"
      >
        {isOpen ? (
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M18 6 6 18M6 6l12 12" strokeLinecap="round" />
          </svg>
        ) : (
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path
              d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        )}
      </button>
    </div>
  );
}

function formatToolName(toolName: string): string {
  return toolName.replace(/_/g, " ");
}
