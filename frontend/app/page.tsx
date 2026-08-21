import ChatWidget from "@/components/ChatWidget";

export default function Home() {
  return (
    <main className="min-h-screen bg-slate-100 p-8">
      <div className="mx-auto max-w-2xl">
        <h1 className="text-2xl font-semibold text-slate-800">Client Website (Demo)</h1>
        <p className="mt-2 text-slate-600">
          This page simulates a client&apos;s website with the support widget embedded in the
          bottom-right corner. Click the bubble to start a chat — no login required.
        </p>
      </div>
      <ChatWidget variant="launcher" />
    </main>
  );
}
