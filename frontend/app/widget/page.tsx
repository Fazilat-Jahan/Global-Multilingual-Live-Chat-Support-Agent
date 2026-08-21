import ChatWidget from "@/components/ChatWidget";

/**
 * Standalone, chrome-less route meant to be embedded via <iframe> on any
 * plain HTML page (see public/test-embed.html) — the standard pattern for
 * third-party embeddable chat widgets.
 */
export default function WidgetPage() {
  return <ChatWidget variant="embedded" />;
}
