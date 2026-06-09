"use client";

import Link from "next/link";
import { Shield, Settings } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { useAuth } from "@/hooks/useAuth";
import { HealthOverview } from "@/components/admin/HealthOverview";
import { DatabaseHealth } from "@/components/admin/DatabaseHealth";
import { TaskStatus } from "@/components/admin/TaskStatus";
import { DataSourceStatus } from "@/components/admin/DataSourceStatus";
import { ModelPerformance } from "@/components/admin/ModelPerformance";
import { ManualActions } from "@/components/admin/ManualActions";
import { UserManagement } from "@/components/admin/UserManagement";
import { EndpointHealth } from "@/components/admin/EndpointHealth";
import { SystemLogs } from "@/components/admin/SystemLogs";

export default function AdminPage() {
  const { user, isLoggedIn, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="max-w-7xl mx-auto px-4 py-12">
        <div className="h-8 w-64 bg-zinc-800 rounded animate-pulse" />
      </div>
    );
  }

  if (!isLoggedIn || !user || user.tier !== "ADMIN") {
    return (
      <div className="max-w-lg mx-auto px-4 py-20">
        <Card className="p-8 text-center space-y-4">
          <Shield size={40} className="text-zinc-600 mx-auto" />
          <h1 className="text-lg font-semibold text-zinc-200">Access Denied</h1>
          <p className="text-sm text-zinc-500">
            This page is restricted to administrators.
          </p>
          <Link
            href="/"
            className="inline-block mt-2 px-4 py-2 rounded-lg bg-sky-600 text-white text-sm font-medium hover:bg-sky-500 transition-colors"
          >
            Back to Dashboard
          </Link>
        </Card>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-zinc-900 dark:text-white flex items-center gap-2">
          <Settings size={20} className="text-sky-500 dark:text-sky-400" />
          System Administration
        </h1>
        <p className="text-sm text-zinc-500 mt-0.5">
          Infrastructure monitoring and controls
        </p>
      </div>

      {/* A. System Health — always visible at top */}
      <HealthOverview />

      {/* B + D. Database + Tasks side by side */}
      <div className="grid lg:grid-cols-2 gap-6">
        <DatabaseHealth />
        <TaskStatus />
      </div>

      {/* E. Data Sources — full width */}
      <DataSourceStatus />

      {/* F + H. Models + Actions side by side */}
      <div className="grid lg:grid-cols-2 gap-6">
        <ModelPerformance />
        <ManualActions />
      </div>

      {/* G. User Management — full width */}
      <UserManagement />

      {/* C + I. Endpoints + Logs side by side */}
      <div className="grid lg:grid-cols-2 gap-6">
        <EndpointHealth />
        <SystemLogs />
      </div>
    </div>
  );
}
