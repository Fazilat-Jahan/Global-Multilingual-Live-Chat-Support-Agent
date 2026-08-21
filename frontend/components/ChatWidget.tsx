"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ChatSocket, type ConnectionStatus, type ServerEvent } from "@/lib/websocket";
import { getStoredSessionId } from "@/lib/session";
import ChatWindow from "./ChatWindow";

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

  const socketRef = useRef<ChatSocket | null>(null);
  const streamingMessageIdRef = useRef<string | null>(null);

  const handleEvent = useCallback((event: ServerEvent) => {
    switch (event.type) {
      case "agent_started":
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
        streamingMessageIdRef.current = null;
        setMessages((prev) => [
          ...prev,
          { id: crypto.randomUUID(), role: "assistant", text: event.message as string, kind: "error" },
        ]);
        break;

      default:
        break;
    }
  }, []);

  useEffect(() => {
    const socket = new ChatSocket(WS_URL, getStoredSessionId());
    socketRef.current = socket;

    const unsubscribeEvent = socket.onEvent(handleEvent);
    const unsubscribeStatus = socket.onStatusChange(setConnectionStatus);
    socket.connect();

    return () => {
      unsubscribeEvent();
      unsubscribeStatus();
      socket.close();
    };
  }, [handleEvent]);

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
          onSend={sendMessage}
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
