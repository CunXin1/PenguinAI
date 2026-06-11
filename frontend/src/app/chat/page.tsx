"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Sparkles, Send, Loader2, Shield, Trash2, Crown, AlertTriangle } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { useAuth } from "@/hooks/useAuth";
import { chat as chatApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { ChatMessage, ChatQuota } from "@/lib/types";

const STORAGE_KEY = "penguinai_chat_history";
const MAX_INPUT = 2000;

const SUGGESTIONS = [
  "What does a LONG signal mean?",
  "Explain RSI and how PenguinAI uses it.",
  "How is the confidence score calculated?",
  "What's the difference between the FREE and PRO plans?",
];

function fmtReset(sec: number): string {
  if (sec <= 0) return "";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m`;
  return "<1m";
}

export default function ChatPage() {
  const { isLoggedIn, isLoading } = useAuth();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [quota, setQuota] = useState<ChatQuota | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Restore conversation from this device.
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) setMessages(JSON.parse(raw));
    } catch {
      /* corrupt cache — ignore */
    }
  }, []);

  // Persist on change.
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(messages));
    } catch {
      /* quota/full — non-fatal */
    }
  }, [messages]);

  // Load the quota once signed in.
  useEffect(() => {
    if (!isLoggedIn) return;
    chatApi
      .quota()
      .then(setQuota)
      .catch(() => setQuota(null));
  }, [isLoggedIn]);

  // Keep the latest message in view.
  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  const unlimited = !quota || quota.limit <= 0 || quota.remaining < 0;
  const exhausted = !unlimited && quota.remaining <= 0;

  const send = useCallback(
    async (text: string) => {
      const content = text.trim();
      if (!content || sending || exhausted) return;

      const next: ChatMessage[] = [...messages, { role: "user", content }];
      setMessages(next);
      setInput("");
      setSending(true);
      setError(null);
      try {
        const res = await chatApi.send(next);
        setMessages([...next, { role: "assistant", content: res.reply }]);
        setQuota(res.usage);
      } catch (e) {
        const err = e as { status?: number; message?: string };
        setError(err.message ?? "Something went wrong. Please try again.");
        if (err.status === 429) {
          chatApi.quota().then(setQuota).catch(() => {});
        }
      } finally {
        setSending(false);
      }
    },
    [messages, sending, exhausted]
  );

  const clearChat = () => {
    setMessages([]);
    setError(null);
    if (typeof window !== "undefined") localStorage.removeItem(STORAGE_KEY);
  };

  // ── Auth states ──────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-20 grid place-items-center">
        <Loader2 size={22} className="animate-spin text-sky-500" />
      </div>
    );
  }

  if (!isLoggedIn) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-6">
        <Card className="p-10 text-center">
          <Sparkles size={28} className="text-sky-400 mx-auto mb-3" />
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            Sign in to chat with the PenguinAI assistant.
          </p>
          <Link
            href="/auth/login"
            className="inline-flex mt-4 px-4 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 text-white text-sm font-semibold transition-colors"
          >
            Sign in
          </Link>
        </Card>
      </div>
    );
  }

  // ── Chat surface ─────────────────────────────────────────────
  return (
    <div className="max-w-3xl mx-auto px-4 py-6 flex flex-col h-[calc(100vh-7rem)]">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 mb-4 shrink-0">
        <div>
          <h1 className="text-xl font-bold text-zinc-900 dark:text-white flex items-center gap-2">
            <Sparkles size={20} className="text-sky-500 dark:text-sky-400" /> Assistant
          </h1>
          <p className="text-xs text-zinc-500 mt-0.5">
            {unlimited ? (
              "Unlimited messages"
            ) : (
              <>
                {quota!.remaining}/{quota!.limit} messages left
                {quota!.reset_seconds > 0 && ` · resets in ${fmtReset(quota!.reset_seconds)}`}
              </>
            )}
          </p>
        </div>
        {messages.length > 0 && (
          <button
            onClick={clearChat}
            className="flex items-center gap-1.5 text-xs text-zinc-500 hover:text-red-500 dark:hover:text-red-400 transition-colors px-2 py-1.5 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800/50"
          >
            <Trash2 size={14} /> New chat
          </button>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto space-y-4 pr-1">
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center gap-5 py-10">
            <div>
              <div className="w-12 h-12 rounded-full bg-gradient-to-br from-sky-400 to-sky-600 grid place-items-center mx-auto mb-3">
                <Sparkles size={22} className="text-white" />
              </div>
              <p className="text-sm text-zinc-600 dark:text-zinc-400 max-w-sm">
                Ask about signals, indicators, or how PenguinAI works.
              </p>
            </div>
            <div className="grid sm:grid-cols-2 gap-2 w-full max-w-lg">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => send(s)}
                  className="text-left text-sm text-zinc-700 dark:text-zinc-300 rounded-lg border border-zinc-200 dark:border-zinc-800 px-3 py-2.5 hover:border-sky-400/60 hover:bg-zinc-50 dark:hover:bg-zinc-900/60 transition-colors"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((m, i) => (
            <div
              key={i}
              className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}
            >
              <div
                className={cn(
                  "max-w-[85%] rounded-2xl px-4 py-2.5 text-sm whitespace-pre-wrap break-words",
                  m.role === "user"
                    ? "bg-sky-500 text-white rounded-br-sm"
                    : "bg-zinc-100 dark:bg-zinc-800/70 text-zinc-800 dark:text-zinc-200 rounded-bl-sm"
                )}
              >
                {m.content}
              </div>
            </div>
          ))
        )}

        {sending && (
          <div className="flex justify-start">
            <div className="bg-zinc-100 dark:bg-zinc-800/70 rounded-2xl rounded-bl-sm px-4 py-3 flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-zinc-400 animate-bounce [animation-delay:-0.3s]" />
              <span className="w-1.5 h-1.5 rounded-full bg-zinc-400 animate-bounce [animation-delay:-0.15s]" />
              <span className="w-1.5 h-1.5 rounded-full bg-zinc-400 animate-bounce" />
            </div>
          </div>
        )}

        {error && (
          <div className="flex items-center gap-2 text-xs text-red-500 dark:text-red-400 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">
            <AlertTriangle size={14} className="shrink-0" />
            {error}
          </div>
        )}

        <div ref={scrollRef} />
      </div>

      {/* Exhausted banner */}
      {exhausted && (
        <Card className="p-3 mt-3 shrink-0 flex items-center justify-between gap-3 border-amber-500/40">
          <div className="flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300">
            <Crown size={16} className="text-amber-500 dark:text-amber-400 shrink-0" />
            You&apos;ve used all {quota!.limit} messages
            {quota!.reset_seconds > 0 && ` — resets in ${fmtReset(quota!.reset_seconds)}`}.
          </div>
          <Link
            href="/profile"
            className="shrink-0 px-3 py-1.5 rounded-lg bg-gradient-to-r from-sky-500 to-sky-600 hover:from-sky-400 hover:to-sky-500 text-white text-xs font-semibold transition-colors"
          >
            Upgrade
          </Link>
        </Card>
      )}

      {/* Composer */}
      <div className="mt-3 shrink-0">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
          className="flex items-end gap-2 rounded-xl bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 px-3 py-2 focus-within:border-sky-500/60 transition-colors"
        >
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value.slice(0, MAX_INPUT))}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(input);
              }
            }}
            disabled={sending || exhausted}
            rows={1}
            placeholder={exhausted ? "Message limit reached" : "Ask anything about markets…"}
            className="flex-1 bg-transparent outline-none resize-none text-sm text-zinc-800 dark:text-zinc-200 placeholder-zinc-400 dark:placeholder-zinc-600 max-h-32 py-1.5 disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={sending || exhausted || !input.trim()}
            className="shrink-0 w-9 h-9 grid place-items-center rounded-lg bg-sky-500 hover:bg-sky-400 text-white transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            aria-label="Send"
          >
            {sending ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
          </button>
        </form>
        <p className="flex items-center gap-1.5 text-[11px] text-zinc-400 dark:text-zinc-600 mt-2 px-1">
          <Shield size={11} className="shrink-0" />
          PenguinAI provides signals, not financial advice. The assistant can be wrong — verify
          before acting.
        </p>
      </div>
    </div>
  );
}
