"use client";

import { useEffect, useRef } from "react";
import type { ChatMessage } from "./ChatWidget";

interface MessageListProps {
  messages: ChatMessage[];
  statusLine: string | null;
}

export default function MessageList({ messages, statusLine }: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, statusLine]);

  return (
    <div className="flex-1 overflow-y-auto px-3 py-4 space-y-3 bg-slate-50">
      {messages.map((message) => (
        <div key={message.id}>
          <div
            className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed whitespace-pre-wrap break-words ${
                message.role === "user"
                  ? "bg-brand-500 text-white rounded-br-sm"
                  : message.kind === "error"
                    ? "bg-red-50 text-red-700 border border-red-200 rounded-bl-sm"
                    : "bg-white text-slate-800 border border-slate-200 rounded-bl-sm"
              }`}
            >
              {message.text}
              {message.streaming && (
                <span className="inline-block w-1.5 h-3.5 bg-current opacity-50 ml-0.5 align-middle animate-pulse" />
              )}
            </div>
          </div>
          {message.escalated && (
            <div className="flex justify-start mt-1">
              <span className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-full px-2.5 py-0.5">
                Forwarded to human support
              </span>
            </div>
          )}
        </div>
      ))}

      {statusLine && (
        <div className="flex justify-start">
          <div className="text-xs text-slate-500 italic px-1">{statusLine}</div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
