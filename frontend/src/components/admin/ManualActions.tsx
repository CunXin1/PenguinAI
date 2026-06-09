"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Play, Loader2 } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { admin } from "@/lib/api";
import { cn } from "@/lib/utils";

interface ActionDef {
  key: string;
  label: string;
  description: string;
}

const ACTIONS: ActionDef[] = [
  { key: "refresh-signals", label: "Refresh Signals", description: "Top-100 signal cache" },
  { key: "retrain-models", label: "Retrain Models", description: "Full daily ML pipeline" },
  { key: "scrape-social", label: "Scrape Social", description: "Twitter + Reddit" },
  { key: "fetch-earnings", label: "Fetch Earnings", description: "Finnhub earnings data" },
  { key: "fetch-celebrities", label: "Fetch Holdings", description: "Congress + 13F + ARK" },
  { key: "fetch-news", label: "Refresh News", description: "Hot ticker news" },
  { key: "validate-symbols", label: "Validate Symbols", description: "User symbol requests" },
];

type ActionState = "idle" | "triggered" | "polling" | "success" | "failure";

export function ManualActions() {
  const [states, setStates] = useState<Record<string, ActionState>>({});
  const [taskIds, setTaskIds] = useState<Record<string, string>>({});

  const triggerMutation = useMutation({
    mutationFn: (action: string) => admin.triggerAction(action),
    onMutate: (action) => {
      setStates((prev) => ({ ...prev, [action]: "triggered" }));
    },
    onSuccess: (data, action) => {
      if (data.task_id) {
        setTaskIds((prev) => ({ ...prev, [action]: data.task_id! }));
        setStates((prev) => ({ ...prev, [action]: "polling" }));
        pollTask(action, data.task_id);
      } else {
        setStates((prev) => ({ ...prev, [action]: "success" }));
        setTimeout(() => setStates((prev) => ({ ...prev, [action]: "idle" })), 5000);
      }
    },
    onError: (_, action) => {
      setStates((prev) => ({ ...prev, [action]: "failure" }));
      setTimeout(() => setStates((prev) => ({ ...prev, [action]: "idle" })), 5000);
    },
  });

  async function pollTask(action: string, taskId: string) {
    for (let i = 0; i < 60; i++) {
      await new Promise((r) => setTimeout(r, 3000));
      try {
        const result = await admin.taskResult(taskId);
        if (result.status === "SUCCESS") {
          setStates((prev) => ({ ...prev, [action]: "success" }));
          setTimeout(() => setStates((prev) => ({ ...prev, [action]: "idle" })), 5000);
          return;
        }
        if (result.status === "FAILURE" || result.status === "REVOKED") {
          setStates((prev) => ({ ...prev, [action]: "failure" }));
          setTimeout(() => setStates((prev) => ({ ...prev, [action]: "idle" })), 5000);
          return;
        }
      } catch {
        break;
      }
    }
    setStates((prev) => ({ ...prev, [action]: "idle" }));
  }

  return (
    <Card className="p-5 space-y-4">
      <div className="flex items-center gap-2">
        <Play size={16} className="text-sky-400" />
        <h2 className="text-sm font-semibold text-zinc-200">Manual Actions</h2>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {ACTIONS.map((action) => {
          const state = states[action.key] ?? "idle";
          const running = state === "triggered" || state === "polling";
          return (
            <button
              key={action.key}
              onClick={() => !running && triggerMutation.mutate(action.key)}
              disabled={running}
              className={cn(
                "flex items-center gap-3 rounded-lg border p-3 text-left transition-colors",
                state === "success"
                  ? "border-emerald-500/30 bg-emerald-500/5"
                  : state === "failure"
                    ? "border-red-500/30 bg-red-500/5"
                    : "border-zinc-800 bg-zinc-900/40 hover:bg-zinc-800/60",
                running && "opacity-70 cursor-wait"
              )}
            >
              {running ? (
                <Loader2 size={14} className="text-sky-400 animate-spin shrink-0" />
              ) : (
                <Play
                  size={14}
                  className={cn(
                    "shrink-0",
                    state === "success"
                      ? "text-emerald-400"
                      : state === "failure"
                        ? "text-red-400"
                        : "text-zinc-500"
                  )}
                />
              )}
              <div className="min-w-0">
                <p className="text-xs font-medium text-zinc-200">{action.label}</p>
                <p className="text-[10px] text-zinc-500 truncate">{action.description}</p>
              </div>
              {state === "success" && (
                <span className="ml-auto text-[10px] text-emerald-400 shrink-0">Done</span>
              )}
              {state === "failure" && (
                <span className="ml-auto text-[10px] text-red-400 shrink-0">Failed</span>
              )}
            </button>
          );
        })}
      </div>
    </Card>
  );
}
