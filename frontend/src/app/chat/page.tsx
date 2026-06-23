"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  Sparkles,
  Send,
  Loader2,
  Shield,
  Plus,
  Trash2,
  Crown,
  AlertTriangle,
  MessageSquare,
  Wrench,
  PanelLeft,
} from "lucide-react";
import { Card } from "@/components/ui/Card";
import { ChatCards } from "@/components/chat/ChatCards";
import { useAuth } from "@/hooks/useAuth";
import { chat as chatApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { ChatCard, ChatQuota, Conversation, StoredMessage } from "@/lib/types";

const MAX_INPUT = 2000;

const SUGGESTIONS = [
  "What's the latest quote for NVDA?",
  "Show me AAPL's recent earnings.",
  "What's in my watchlist?",
  "Summarize recent news for TSLA.",
];

/** A rendered message — stored, or a pending/streaming optimistic turn. */
type Msg = {
  role: "user" | "assistant";
  content: string;
  tools_used?: string[];
  cards?: ChatCard[];
  id?: string;
  streaming?: boolean;
  localId?: string; // client-side handle for optimistic turns (targeted updates + rollback)
};

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

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [loadingThread, setLoadingThread] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [quota, setQuota] = useState<ChatQuota | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  // The conversation currently shown — read by async stream handlers (state would be stale).
  const activeIdRef = useRef<string | null>(null);
  useEffect(() => {
    activeIdRef.current = activeId;
  }, [activeId]);
  // Aborts the in-flight stream when the user switches threads / unmounts, so a stale
  // stream can't keep running server-side or write into another conversation.
  const abortRef = useRef<AbortController | null>(null);
  const abortStream = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);
  useEffect(() => () => abortRef.current?.abort(), []);

  // Load the conversation list + quota once signed in.
  useEffect(() => {
    if (!isLoggedIn) return;
    chatApi.listConversations().then(setConversations).catch(() => setConversations([]));
    chatApi.quota().then(setQuota).catch(() => setQuota(null));
  }, [isLoggedIn]);

  // Keep the latest message in view.
  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  const unlimited = !quota || quota.limit <= 0 || quota.remaining < 0;
  const exhausted = !unlimited && quota.remaining <= 0;

  const openConversation = useCallback(async (id: string) => {
    abortStream(); // stop any in-flight stream before swapping the rendered thread
    setActiveId(id);
    activeIdRef.current = id;
    setError(null);
    setSidebarOpen(false);
    setLoadingThread(true);
    try {
      const detail = await chatApi.getConversation(id);
      setMessages(
        detail.messages.map((m: StoredMessage) => ({
          role: m.role,
          content: m.content,
          tools_used: m.tools_used,
          cards: m.cards ?? undefined,
          id: m.id,
        }))
      );
    } catch {
      setError("Couldn't load that conversation.");
      setMessages([]);
    } finally {
      setLoadingThread(false);
    }
  }, [abortStream]);

  const newChat = useCallback(() => {
    abortStream();
    setActiveId(null);
    activeIdRef.current = null;
    setMessages([]);
    setError(null);
    setInput("");
    setSidebarOpen(false);
  }, [abortStream]);

  const removeConversation = useCallback(
    async (id: string, e: React.MouseEvent) => {
      e.stopPropagation();
      const removed = conversations.find((c) => c.id === id);
      setConversations((cs) => cs.filter((c) => c.id !== id));
      if (id === activeId) newChat();
      try {
        await chatApi.deleteConversation(id);
      } catch {
        // Functional reinsert (not a stale snapshot) so a concurrent list update from an
        // in-flight stream's onDone isn't clobbered. Re-sort by recency to restore order.
        if (removed)
          setConversations((cs) =>
            cs.some((c) => c.id === id)
              ? cs
              : [...cs, removed].sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1))
          );
      }
    },
    [conversations, activeId, newChat]
  );

  const send = useCallback(
    async (text: string) => {
      const content = text.trim();
      if (!content || sending || exhausted) return;

      setInput("");
      setSending(true);
      setError(null);

      // Optimistic user turn + empty assistant bubble, tagged with stable local ids so
      // streamed updates and rollback target THESE messages — never "the last array
      // element", which can change if the user switches threads mid-stream.
      const userLid = crypto.randomUUID();
      const asstLid = crypto.randomUUID();
      setMessages((m) => [
        ...m,
        { role: "user", content, localId: userLid },
        { role: "assistant", content: "", streaming: true, localId: asstLid },
      ]);
      const patchAsst = (fn: (msg: Msg) => Msg) =>
        setMessages((m) => m.map((x) => (x.localId === asstLid ? fn(x) : x)));
      const rollback = () =>
        setMessages((m) => m.filter((x) => x.localId !== userLid && x.localId !== asstLid));

      const controller = new AbortController();
      abortRef.current = controller;
      let createdConvId: string | null = null;

      try {
        // Lazily create a thread on the first message so empty threads never pile up.
        let convId = activeId;
        if (!convId) {
          const conv = await chatApi.createConversation();
          convId = conv.id;
          createdConvId = conv.id;
          setActiveId(conv.id);
          activeIdRef.current = conv.id;
          setConversations((cs) => [conv, ...cs]);
        }

        await chatApi.sendMessageStream(
          convId,
          content,
          {
            onDelta: (t) => patchAsst((x) => ({ ...x, content: x.content + t })),
            onTool: (name) =>
              patchAsst((x) => ({ ...x, tools_used: [...(x.tools_used ?? []), name] })),
            onCard: (card) => patchAsst((x) => ({ ...x, cards: [...(x.cards ?? []), card] })),
            onDone: (d) => {
              patchAsst((x) => ({
                ...x,
                streaming: false,
                id: d.message_id,
                tools_used: d.tools_used ?? x.tools_used,
              }));
              createdConvId = null; // produced a reply — keep the thread
              if (d.usage) setQuota(d.usage);
              setConversations((cs) => {
                const rest = cs.filter((c) => c.id !== convId);
                const existing = cs.find((c) => c.id === convId);
                const now = new Date().toISOString();
                return [
                  {
                    id: convId!,
                    title: d.title,
                    created_at: existing?.created_at ?? now,
                    updated_at: now,
                  },
                  ...rest,
                ];
              });
            },
            onError: (detail) => {
              setError(detail);
              rollback();
              // The server refunds quota on any in-band failure but doesn't resend a 429,
              // so reconcile the counter unconditionally (cheap, read-only).
              chatApi.quota().then(setQuota).catch(() => {});
            },
          },
          null,
          controller.signal
        );
      } catch (e) {
        if (!controller.signal.aborted) {
          const err = e as { message?: string };
          setError(err.message ?? "Something went wrong. Please try again.");
          rollback();
        }
      } finally {
        // A thread created in THIS send that never produced a reply is an orphan — delete
        // it so a failed first message doesn't leave an empty conversation behind. Skip on
        // abort (user switched away; the thread may be perfectly valid).
        if (createdConvId && !controller.signal.aborted) {
          const orphan = createdConvId;
          chatApi.deleteConversation(orphan).catch(() => {});
          setConversations((cs) => cs.filter((c) => c.id !== orphan));
          if (activeIdRef.current === orphan) {
            setActiveId(null);
            activeIdRef.current = null;
            setMessages([]);
          }
        }
        if (abortRef.current === controller) abortRef.current = null;
        setSending(false);
      }
    },
    [activeId, sending, exhausted]
  );

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

  // ── Conversation sidebar ─────────────────────────────────────
  const sidebar = (
    <div className="flex flex-col h-full w-64 shrink-0 border-r border-zinc-200 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-900/30">
      <div className="p-3">
        <button
          onClick={newChat}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 text-white text-sm font-semibold transition-colors"
        >
          <Plus size={16} /> New chat
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-2 pb-3 space-y-1">
        {conversations.length === 0 ? (
          <p className="text-xs text-zinc-500 text-center px-2 py-6">
            No conversations yet.
          </p>
        ) : (
          conversations.map((c) => (
            <button
              key={c.id}
              onClick={() => openConversation(c.id)}
              className={cn(
                "group w-full flex items-center gap-2 px-2.5 py-2 rounded-lg text-left text-sm transition-colors",
                c.id === activeId
                  ? "bg-sky-500/10 text-sky-700 dark:text-sky-300"
                  : "text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800/60"
              )}
            >
              <MessageSquare size={14} className="shrink-0 opacity-60" />
              <span className="flex-1 truncate">{c.title}</span>
              <span
                role="button"
                tabIndex={0}
                onClick={(e) => removeConversation(c.id, e)}
                className="shrink-0 opacity-0 group-hover:opacity-100 text-zinc-400 hover:text-red-500 transition-opacity"
                aria-label="Delete conversation"
              >
                <Trash2 size={13} />
              </span>
            </button>
          ))
        )}
      </div>
    </div>
  );

  // ── Chat surface ─────────────────────────────────────────────
  return (
    <div className="max-w-6xl mx-auto h-[calc(100vh-7rem)] flex rounded-xl overflow-hidden border border-zinc-200 dark:border-zinc-800 my-4">
      {/* Sidebar — fixed on md+, slide-over on mobile */}
      <div className="hidden md:flex">{sidebar}</div>
      {sidebarOpen && (
        <div className="md:hidden fixed inset-0 z-40 flex">
          <div className="bg-zinc-950">{sidebar}</div>
          <div className="flex-1 bg-black/50" onClick={() => setSidebarOpen(false)} />
        </div>
      )}

      <div className="flex-1 flex flex-col min-w-0 bg-white dark:bg-zinc-950">
        {/* Header */}
        <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-zinc-200 dark:border-zinc-800 shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <button
              onClick={() => setSidebarOpen(true)}
              className="md:hidden text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
              aria-label="Conversations"
            >
              <PanelLeft size={18} />
            </button>
            <div className="min-w-0">
              <h1 className="text-base font-bold text-zinc-900 dark:text-white flex items-center gap-2">
                <Sparkles size={18} className="text-sky-500 dark:text-sky-400 shrink-0" />
                <span className="truncate">Assistant</span>
              </h1>
              <p className="text-xs text-zinc-500">
                {unlimited ? (
                  "Unlimited messages"
                ) : (
                  <>
                    {quota!.remaining}/{quota!.limit} left
                    {quota!.reset_seconds > 0 && ` · resets in ${fmtReset(quota!.reset_seconds)}`}
                  </>
                )}
              </p>
            </div>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
          {loadingThread ? (
            <div className="h-full grid place-items-center">
              <Loader2 size={20} className="animate-spin text-sky-500" />
            </div>
          ) : messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center gap-5 py-10">
              <div>
                <div className="w-12 h-12 rounded-full bg-gradient-to-br from-sky-400 to-sky-600 grid place-items-center mx-auto mb-3">
                  <Sparkles size={22} className="text-white" />
                </div>
                <p className="text-sm text-zinc-600 dark:text-zinc-400 max-w-sm">
                  Ask about quotes, indicators, earnings, news, or your watchlist — the
                  assistant fetches live data with tools.
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
                key={m.id ?? i}
                className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}
              >
                <div className={cn("max-w-[85%]", m.role === "user" ? "" : "space-y-1.5")}>
                  <div
                    className={cn(
                      "rounded-2xl px-4 py-2.5 text-sm whitespace-pre-wrap break-words",
                      m.role === "user"
                        ? "bg-sky-500 text-white rounded-br-sm"
                        : "bg-zinc-100 dark:bg-zinc-800/70 text-zinc-800 dark:text-zinc-200 rounded-bl-sm"
                    )}
                  >
                    {m.content ? (
                      m.content
                    ) : m.streaming ? (
                      <span className="flex items-center gap-1.5 py-0.5">
                        <span className="w-1.5 h-1.5 rounded-full bg-zinc-400 animate-bounce [animation-delay:-0.3s]" />
                        <span className="w-1.5 h-1.5 rounded-full bg-zinc-400 animate-bounce [animation-delay:-0.15s]" />
                        <span className="w-1.5 h-1.5 rounded-full bg-zinc-400 animate-bounce" />
                      </span>
                    ) : (
                      ""
                    )}
                  </div>
                  {m.role === "assistant" && m.cards && m.cards.length > 0 && (
                    <ChatCards cards={m.cards} />
                  )}
                  {m.role === "assistant" && m.tools_used && m.tools_used.length > 0 && (
                    <div className="flex flex-wrap items-center gap-1 pl-1">
                      {Array.from(new Set(m.tools_used)).map((t) => (
                        <span
                          key={t}
                          className="inline-flex items-center gap-1 text-[10px] text-zinc-500 dark:text-zinc-400 bg-zinc-100 dark:bg-zinc-800/60 rounded px-1.5 py-0.5"
                        >
                          <Wrench size={9} /> {t}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))
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
          <Card className="p-3 mx-4 mb-3 shrink-0 flex items-center justify-between gap-3 border-amber-500/40">
            <div className="flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300">
              <Crown size={16} className="text-amber-500 dark:text-amber-400 shrink-0" />
              You&apos;ve used all {quota!.limit} messages
              {quota!.reset_seconds > 0 && ` — resets in ${fmtReset(quota!.reset_seconds)}`}.
            </div>
            <Link
              href="/pricing"
              className="shrink-0 px-3 py-1.5 rounded-lg bg-gradient-to-r from-sky-500 to-sky-600 hover:from-sky-400 hover:to-sky-500 text-white text-xs font-semibold transition-colors"
            >
              Upgrade
            </Link>
          </Card>
        )}

        {/* Composer */}
        <div className="px-4 pb-4 pt-1 shrink-0">
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
    </div>
  );
}
