"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { errorMessage, getChatHistory, postChat } from "@/lib/api";
import type { ChatMessage } from "@/lib/types";
import { ChatMessageView } from "./ChatMessageView";

interface ChatPanelProps {
  onReply: () => void;
}

/** The AI assistant dock: history, a composer, a loading indicator, and a collapse toggle. */
export function ChatPanel({ onReply }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getChatHistory().then(setMessages);
  }, []);

  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [messages, pending]);

  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const content = draft.trim();
    if (!content || pending) return;
    setPending(true);
    setError(null);
    try {
      const reply = await postChat(content);
      const now = new Date().toISOString();
      setMessages((current) => [
        ...current,
        { role: "user", content, actions: null, created_at: now },
        {
          role: "assistant",
          content: reply.message,
          actions: { trades: reply.trades, watchlist_changes: reply.watchlist_changes },
          created_at: now,
        },
      ]);
      setDraft("");
      onReply();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setPending(false);
    }
  }

  if (collapsed) {
    return (
      <aside data-testid="chat-panel" data-collapsed="true" className="flex w-10 flex-col bg-terminal-panel">
        <button
          data-testid="chat-toggle"
          type="button"
          aria-expanded={false}
          onClick={() => setCollapsed(false)}
          className="px-2 py-3 text-xs uppercase tracking-wide text-terminal-muted [writing-mode:vertical-rl] hover:text-terminal-text"
        >
          AI assistant
        </button>
      </aside>
    );
  }

  return (
    <aside data-testid="chat-panel" data-collapsed="false" className="flex min-h-0 w-full flex-col bg-terminal-panel lg:w-80">
      <header className="flex items-center justify-between border-b border-terminal-border px-3 py-2 text-xs uppercase tracking-wide text-terminal-muted">
        AI assistant
        <button
          data-testid="chat-toggle"
          type="button"
          aria-expanded={true}
          onClick={() => setCollapsed(true)}
          className="hover:text-terminal-text"
        >
          Hide
        </button>
      </header>
      <div ref={listRef} data-testid="chat-messages" className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3">
        {messages.map((message, index) => (
          <ChatMessageView key={`${message.created_at}-${index}`} message={message} />
        ))}
        {pending && (
          <p data-testid="chat-loading" role="status" className="text-xs text-terminal-muted">
            FinAlly is thinking...
          </p>
        )}
        {error && (
          <p data-testid="chat-error" role="alert" className="text-xs text-loss">
            {error}
          </p>
        )}
      </div>
      <form onSubmit={send} className="flex gap-2 border-t border-terminal-border p-2">
        <input
          data-testid="chat-input"
          aria-label="Message to FinAlly"
          value={draft}
          disabled={pending}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Ask about your portfolio"
          className="min-w-0 flex-1 rounded border border-terminal-border bg-terminal-bg px-2 py-1.5 outline-none focus:border-primary disabled:opacity-50"
        />
        <button
          data-testid="chat-send"
          type="submit"
          disabled={pending || draft.trim() === ""}
          className="rounded bg-secondary px-3 py-1.5 font-semibold text-terminal-text disabled:opacity-40"
        >
          Send
        </button>
      </form>
    </aside>
  );
}
