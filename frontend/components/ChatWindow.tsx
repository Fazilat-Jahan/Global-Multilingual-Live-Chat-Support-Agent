"use client";

import type { ChatMessage } from "./ChatWidget";
import type { ConnectionStatus } from "@/lib/websocket";
import MessageList from "./MessageList";
import ChatInput from "./ChatInput";

interface ChatWindowProps {
  messages: ChatMessage[];
  statusLine: string | null;
  connectionStatus: ConnectionStatus;
  isStreaming: boolean;
  onSend: (content: string) => void;
  onClose?: () => void;
}

const STATUS_LABEL: Record<ConnectionStatus, string> = {
  connecting: "Connecting…",
  open: "Online",
  closed: "Reconnecting…",
};

const STATUS_DOT: Record<ConnectionStatus, string> = {
  connecting: "bg-amber-400",
  open: "bg-emerald-400",
  closed: "bg-red-400",
};

export default function ChatWindow({
  messages,
  statusLine,
  connectionStatus,
  isStreaming,
  onSend,
  onClose,
}: ChatWindowProps) {
  return (
    <div className="flex h-full w-full flex-col bg-white sm:rounded-2xl sm:shadow-2xl sm:border sm:border-slate-200 overflow-hidden">
      <div className="flex items-center justify-between bg-brand-600 px-4 py-3 text-white">
        <div>
          <div className="text-sm font-semibold">Support Chat</div>
          <div className="flex items-center gap-1.5 text-xs text-brand-50/90">
            <span className={`h-1.5 w-1.5 rounded-full ${STATUS_DOT[connectionStatus]}`} />
            {STATUS_LABEL[connectionStatus]}
          </div>
        </div>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            aria-label="Close chat"
            className="rounded-full p-1 hover:bg-white/10 transition-colors"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 6 6 18M6 6l12 12" strokeLinecap="round" />
            </svg>
          </button>
        )}
      </div>

      <MessageList messages={messages} statusLine={statusLine} />
      <ChatInput onSend={onSend} disabled={connectionStatus !== "open" || isStreaming} />
    </div>
  );
}
