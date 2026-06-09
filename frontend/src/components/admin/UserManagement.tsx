"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Users, Search, ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";
import { Card } from "@/components/ui/Card";
import { StatTile } from "@/components/ui/StatTile";
import { admin } from "@/lib/api";
import { cn, timeAgo } from "@/lib/utils";
import type { AdminUserListResponse, AdminUserStats } from "@/lib/types";

const TIER_COLORS: Record<string, string> = {
  FREE: "text-zinc-400 bg-zinc-800 border-zinc-700",
  PRO: "text-sky-400 bg-sky-500/10 border-sky-500/30",
  PREMIUM: "text-amber-400 bg-amber-500/10 border-amber-500/30",
  ADMIN: "text-red-400 bg-red-500/10 border-red-500/30",
};

const TIERS = ["FREE", "PRO", "PREMIUM", "ADMIN"];

export function UserManagement() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [tierFilter, setTierFilter] = useState("");
  const [editingUser, setEditingUser] = useState<string | null>(null);

  const { data: stats } = useQuery<AdminUserStats>({
    queryKey: ["admin", "user-stats"],
    queryFn: () => admin.userStats(),
    refetchInterval: 60_000,
  });

  const { data: userList, isLoading } = useQuery<AdminUserListResponse>({
    queryKey: ["admin", "users", page, search, tierFilter],
    queryFn: () => admin.userList(page, 20, search, tierFilter),
    refetchInterval: 60_000,
  });

  const updateMutation = useMutation({
    mutationFn: ({ userId, data }: { userId: string; data: { tier?: string; is_active?: boolean } }) =>
      admin.updateUser(userId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      queryClient.invalidateQueries({ queryKey: ["admin", "user-stats"] });
      setEditingUser(null);
    },
  });

  const totalPages = userList ? Math.ceil(userList.total / userList.per_page) : 0;

  return (
    <Card className="p-5 space-y-4">
      <div className="flex items-center gap-2">
        <Users size={16} className="text-sky-400" />
        <h2 className="text-sm font-semibold text-zinc-200">Users</h2>
      </div>

      {/* Stats row */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <StatTile label="Total" value={stats.total} accent="brand" />
          <StatTile label="Verified" value={stats.verified} accent="up" />
          <StatTile label="Today" value={stats.registered_today} accent="neutral" />
          <StatTile label="This Week" value={stats.registered_this_week} accent="neutral" />
        </div>
      )}

      {/* Tier breakdown */}
      {stats && (
        <div className="flex gap-2 flex-wrap">
          {Object.entries(stats.by_tier).map(([tier, count]) => (
            <button
              key={tier}
              onClick={() => setTierFilter(tierFilter === tier ? "" : tier)}
              className={cn(
                "px-2 py-1 rounded text-[11px] font-semibold border transition-colors",
                TIER_COLORS[tier] ?? "text-zinc-400 bg-zinc-800 border-zinc-700",
                tierFilter === tier && "ring-1 ring-sky-500"
              )}
            >
              {tier}: {count}
            </button>
          ))}
        </div>
      )}

      {/* Search */}
      <div className="flex items-center gap-2 rounded-lg bg-zinc-900 border border-zinc-800 px-3 py-2 focus-within:border-sky-500/60 transition-colors">
        <Search size={14} className="text-zinc-500" />
        <input
          placeholder="Search by email or name..."
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
          className="bg-transparent outline-none text-sm text-zinc-200 placeholder-zinc-600 w-full"
        />
      </div>

      {/* User table */}
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-zinc-500 border-b border-zinc-800">
              <th className="text-left py-1.5 font-medium">Email</th>
              <th className="text-left py-1.5 font-medium">Name</th>
              <th className="text-center py-1.5 font-medium">Tier</th>
              <th className="text-center py-1.5 font-medium">Active</th>
              <th className="text-right py-1.5 font-medium">Joined</th>
              <th className="text-right py-1.5 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {userList?.users.map((u) => (
              <tr key={u.id} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                <td className="py-1.5 text-zinc-300">{u.email}</td>
                <td className="py-1.5 text-zinc-400">{u.display_name ?? "—"}</td>
                <td className="py-1.5 text-center">
                  {editingUser === u.id ? (
                    <select
                      defaultValue={u.tier}
                      onChange={(e) => {
                        updateMutation.mutate({ userId: u.id, data: { tier: e.target.value } });
                      }}
                      onBlur={() => setEditingUser(null)}
                      autoFocus
                      className="bg-zinc-800 border border-zinc-700 rounded px-1 py-0.5 text-[10px] text-zinc-200 outline-none"
                    >
                      {TIERS.map((t) => (
                        <option key={t} value={t}>{t}</option>
                      ))}
                    </select>
                  ) : (
                    <span
                      className={cn(
                        "px-1.5 py-0.5 rounded text-[10px] font-semibold border cursor-pointer",
                        TIER_COLORS[u.tier] ?? "text-zinc-400 bg-zinc-800 border-zinc-700"
                      )}
                      onClick={() => setEditingUser(u.id)}
                    >
                      {u.tier}
                    </span>
                  )}
                </td>
                <td className="py-1.5 text-center">
                  <button
                    onClick={() =>
                      updateMutation.mutate({ userId: u.id, data: { is_active: !u.is_active } })
                    }
                    className={cn(
                      "px-1.5 py-0.5 rounded text-[10px] font-semibold border transition-colors",
                      u.is_active
                        ? "text-emerald-400 bg-emerald-500/10 border-emerald-500/30"
                        : "text-red-400 bg-red-500/10 border-red-500/30"
                    )}
                  >
                    {u.is_active ? "Active" : "Banned"}
                  </button>
                </td>
                <td className="py-1.5 text-right text-zinc-500">
                  {u.created_at ? timeAgo(u.created_at) : "—"}
                </td>
                <td className="py-1.5 text-right">
                  {editingUser !== u.id && (
                    <button
                      onClick={() => setEditingUser(u.id)}
                      className="text-[10px] text-sky-400 hover:text-sky-300"
                    >
                      Edit
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between text-[11px] text-zinc-500">
          <span>
            Page {page} of {totalPages} ({userList?.total} users)
          </span>
          <div className="flex gap-1">
            <button
              onClick={() => setPage(Math.max(1, page - 1))}
              disabled={page <= 1}
              className="p-1 rounded hover:bg-zinc-800 disabled:opacity-30"
            >
              <ChevronLeft size={14} />
            </button>
            <button
              onClick={() => setPage(Math.min(totalPages, page + 1))}
              disabled={page >= totalPages}
              className="p-1 rounded hover:bg-zinc-800 disabled:opacity-30"
            >
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      )}
    </Card>
  );
}
