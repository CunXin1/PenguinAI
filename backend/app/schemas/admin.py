from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

# ── Section A: System Health ──────────────────────────────────────────────────


class ServiceHealth(BaseModel):
    name: str
    status: str  # healthy | degraded | down
    latency_ms: float | None = None
    detail: str = ""


class SystemHealthOverview(BaseModel):
    overall: str  # healthy | degraded | critical
    checked_at: datetime
    services: list[ServiceHealth]


# ── Section B: Database Health ────────────────────────────────────────────────


class ConnectionPool(BaseModel):
    pool_size: int
    checked_in: int
    checked_out: int
    overflow: int
    max_overflow: int


class TableStat(BaseModel):
    name: str
    approx_rows: int
    size_bytes: int
    size_human: str
    latest_ts: datetime | None = None


class DatabaseHealth(BaseModel):
    connection_pool: ConnectionPool
    active_connections: int
    tables: list[TableStat]
    total_db_size_bytes: int
    total_db_size_human: str


# ── Section C: Endpoint Health ────────────────────────────────────────────────


class RouteInfo(BaseModel):
    method: str
    path: str
    name: str | None = None


class ProbeResult(BaseModel):
    endpoint: str
    status_code: int | None = None
    latency_ms: float | None = None
    error: str | None = None


class EndpointHealth(BaseModel):
    routes: list[RouteInfo]
    probes: list[ProbeResult]


# ── Section D: Task Status ────────────────────────────────────────────────────


class TaskRunInfo(BaseModel):
    name: str
    task: str
    schedule: str
    last_run: datetime | None = None
    last_status: str | None = None  # SUCCESS | FAILURE | RUNNING
    last_duration_s: float | None = None


class QueueDepth(BaseModel):
    name: str
    pending: int


class WorkerInfo(BaseModel):
    name: str
    status: str  # online | offline
    active_tasks: int
    processed: int
    concurrency: int
    queues: list[str]


class TaskStatus(BaseModel):
    scheduled_tasks: list[TaskRunInfo]
    queues: list[QueueDepth]
    workers: list[WorkerInfo]


# ── Section E: Data Sources ───────────────────────────────────────────────────


class RealtimeSourceStatus(BaseModel):
    name: str
    alive: bool
    uptime_s: float | None = None
    restarts: int = 0
    detail: str = ""


class DataFreshness(BaseModel):
    table: str
    latest_ts: datetime | None = None


class FearGreedSourceHealth(BaseModel):
    status: str  # healthy | degraded | down | unknown
    source: str | None = None  # 'cnn' | 'computed' (VIX-proxy fallback)
    score: float | None = None
    rating: str | None = None
    phase: str | None = None
    interval_min: int | None = None
    consecutive_failures: int = 0
    last_success_at: str | None = None
    last_run_at: str | None = None
    next_run_at: str | None = None
    last_error: str | None = None


class DataSourceStatus(BaseModel):
    realtime: list[RealtimeSourceStatus]
    freshness: list[DataFreshness]
    coverage: dict[str, int] = {}
    fear_greed: FearGreedSourceHealth | None = None


# ── Section F: Model Performance ──────────────────────────────────────────────


class ModelFileInfo(BaseModel):
    name: str
    file_path: str
    exists: bool
    size_bytes: int | None = None
    size_human: str | None = None
    last_modified: datetime | None = None


class SignalDistribution(BaseModel):
    total: int
    by_direction: dict[str, int]
    avg_confidence: float | None = None


class ModelPerformance(BaseModel):
    models: list[ModelFileInfo]
    signal_distribution: SignalDistribution


# ── Section G: User Management ────────────────────────────────────────────────


class UserStats(BaseModel):
    total: int
    by_tier: dict[str, int]
    verified: int
    active: int
    registered_today: int
    registered_this_week: int


class UserRow(BaseModel):
    id: str
    email: str
    display_name: str | None
    tier: str
    is_active: bool
    email_verified: bool
    created_at: datetime | None

    class Config:
        from_attributes = True


class UserListResponse(BaseModel):
    users: list[UserRow]
    total: int
    page: int
    per_page: int


class UserUpdateRequest(BaseModel):
    tier: str | None = None
    is_active: bool | None = None


# ── Section H: Manual Actions ─────────────────────────────────────────────────


class ActionResponse(BaseModel):
    triggered: bool
    task_id: str | None = None
    task_name: str


class TaskResultResponse(BaseModel):
    task_id: str
    status: str  # PENDING | STARTED | SUCCESS | FAILURE | REVOKED
    result: str | None = None


# ── Section I: System Logs ────────────────────────────────────────────────────


class LogEntry(BaseModel):
    timestamp: str
    level: str
    logger: str
    message: str


class LogsResponse(BaseModel):
    entries: list[LogEntry]
    total_buffered: int
    showing: int
    min_level: str
