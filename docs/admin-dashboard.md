# Admin Dashboard 管理仪表板

> Last updated: 2026-06-09

## 概述

Admin Dashboard 是 PenguinAI 的系统管理仪表板，仅限 `ADMIN` tier 用户访问。提供全栈基础设施的实时监控、数据库健康检查、任务调度状态、数据源连接状况、模型性能追踪、用户管理和手动操作触发。

**前端路由**: `/admin`
**后端前缀**: `/api/admin/*`
**权限**: 所有端点均需 `require_tier("ADMIN")`

---

## ADMIN 账号

首次启动时自动创建 ADMIN 用户（通过 startup self-healing 检查 `check_and_seed_admin`）。

**配置方式**（`.env`）：
```env
ADMIN_EMAIL=admin@penguinai.com
ADMIN_PASSWORD=YourStrongPassword    # 留空 → 随机生成，打印到启动日志
```

**行为**：
- 数据库中不存在 `ADMIN_EMAIL` 对应的用户 → 自动创建，密码取 `ADMIN_PASSWORD` 或随机生成
- 用户已存在但密码与 `.env` 中 `ADMIN_PASSWORD` 不一致 → 自动更新密码 hash（每次启动同步）
- 用户已存在且密码匹配 → 仅确保 tier 为 ADMIN

**登录跳转**：ADMIN 用户登录后自动跳转到 `/admin`（非 ADMIN 用户跳转 `/`）。

---

## 架构

### 后端

FastAPI 子包结构：

```
backend/app/api/routes/admin/
├── __init__.py          # re-export router（main.py 零改动）
├── router.py            # 挂载所有子路由
├── health.py            # 系统健康 + API 端点探针
├── database.py          # 数据库连接池 + 表统计
├── tasks.py             # Celery 任务状态 + 队列深度
├── datasources.py       # 实时数据源 + 数据新鲜度
├── models.py            # ML 模型文件 + 信号分布
├── users.py             # 用户统计 + 列表 + 管理
├── actions.py           # 手动触发 Celery 任务
└── logs.py              # 内存日志缓冲 + 查询
```

辅助文件：
- `backend/app/schemas/admin.py` — Pydantic 响应模型
- `backend/app/core/utils.py` — `human_size()` 共享工具（database.py + models.py 使用）
- `backend/app/core/startup.py` — `check_and_seed_admin()` ADMIN 账号自愈

### 前端

```
frontend/src/app/admin/page.tsx              # 主页面（auth gate + 9 面板编排）
frontend/src/components/admin/
├── StatusDot.tsx               # 复用的绿/黄/红圆点指示器
├── HealthOverview.tsx          # A. 全局服务健康
├── DatabaseHealth.tsx          # B. 数据库健康
├── EndpointHealth.tsx          # C. API 端点探针
├── TaskStatus.tsx              # D. 任务 + Worker 状态
├── DataSourceStatus.tsx        # E. 数据源状态
├── ModelPerformance.tsx        # F. 模型性能
├── UserManagement.tsx          # G. 用户管理
├── ManualActions.tsx           # H. 手动触发
└── SystemLogs.tsx              # I. 系统日志
```

---

## 9 个监控面板详解

### A. System Health Overview — 系统健康总览

**端点**: `GET /api/admin/health/overview`
**轮询**: 30 秒

一眼判断整个系统是否正常。顶部 banner 显示全局状态（绿：All Systems Operational / 黄：Degraded / 红：Critical），下方网格展示每个服务的交通灯卡片。

**监控的服务**:

| 服务 | 检测方式 | 判定逻辑 |
|------|----------|----------|
| TimescaleDB | `SELECT 1` + 延迟测量 | 连接成功 = healthy，超时 = down |
| Redis | `PING` + 内存信息 | PONG = healthy，无响应 = down |
| Backend API | 自检 | 始终 healthy（自身服务中） |
| Celery Workers | `inspect.ping()` (timeout=2s, 线程池执行) | 有响应 = healthy，无 worker = down |
| RT Supervisor | `app.state.watchdog.health` | running = healthy, disabled = degraded |
| IBKR Stream | supervisor health → services.ibkr | alive = healthy |
| Finnhub WS | supervisor health → services.finnhub | alive = healthy |

**全局状态计算**:
- DB 或 Redis down → `critical`
- 任何服务 down 或 degraded → `degraded`
- 全部 healthy → `healthy`

**技术细节**:
- Celery `inspect()` 是同步阻塞调用，用 `asyncio.to_thread()` 包装避免阻塞事件循环
- 探针 URL 从 `request.base_url` 动态获取，Docker 环境可用

---

### B. Database Health — 数据库健康

**端点**: `GET /api/admin/db/health`
**轮询**: 60 秒

**展示内容**:
1. **连接池状态** — 进度条可视化（used/available），颜色随使用率变化（绿 < 60%、黄 60–80%、红 > 80%）
2. **表统计表格** — 每个关键表的近似行数、磁盘大小、最新时间戳
3. **总 DB 大小**

**关键设计决策**:
- 行数用 `pg_stat_user_tables.n_live_tup`（O(1) 近似值），不用 `COUNT(*)`。bars_30m 有 2.36 亿行，真正 COUNT 会花几分钟。
- 时间戳查询 `SELECT max(ts)` 在 TimescaleDB hypertable 上很快（chunk exclusion + 降序索引只读最后一个 chunk）。
- `human_size()` 工具函数从 `app.core.utils` 导入，database.py 和 models.py 共用。

**跟踪的表**: bars_30m, bars_1d, market_data_1min, signal_cache, social_posts, users, tickers, instruments, celebrity_holdings, earnings, news_articles, symbol_requests

---

### C. API Endpoint Health — 接口健康

**端点**: `GET /api/admin/health/endpoints`
**轮询**: 60 秒

1. **路由列表** — 枚举 FastAPI 所有注册的路由（method + path），可展开/折叠，按 HTTP method 颜色编码（GET=绿, POST=蓝, PATCH=黄, DELETE=红）
2. **探针结果** — 用 httpx 对 4 个关键只读端点发内部请求，报告状态码 + 延迟。未执行的探针显示灰色（非红色）。

**探针目标**: `/health`, `/api/market-data/status`, `/api/signals/top?limit=1`, `/api/tickers/search?q=AAPL`

---

### D. Pipeline & Task Status — 任务状态

**端点**: `GET /api/admin/tasks/status`
**轮询**: 15 秒

**展示内容**:
1. **队列深度** — `default` 和 `ml_inference` 队列中待处理任务数（通过异步 `redis.llen()` 查询）
2. **Worker 卡片** — 每个在线 worker 的名称、状态、当前活跃任务数
3. **定时任务表格** — 6 个 Beat 调度任务的上次执行时间、状态（SUCCESS/FAILURE/RUNNING）、耗时

**任务执行追踪机制**:
Celery 信号处理器（在 `ml/tasks/celery_app.py` 中注册）在任务开始/成功/失败时将元数据写入 Redis hash `admin:task_runs`，格式为：
```json
{
  "task_id": "abc-123",
  "status": "SUCCESS",
  "started_at": "2026-06-09T15:00:00Z",
  "finished_at": "2026-06-09T15:00:42Z",
  "duration_s": 42.3
}
```

**技术细节**:
- Redis 连接用 `try/finally` 确保 `aclose()` 不泄漏
- Celery `inspect()` 在 `asyncio.to_thread()` 中执行，不阻塞事件循环

---

### E. Data Source Status — 数据源状态

**端点**: `GET /api/admin/datasources/status`
**轮询**: 30 秒

**展示内容**:
1. **实时源卡片** — IBKR、Finnhub、Massive、30m Bar Closer 的连接状态、uptime、重启次数
2. **Fear & Greed (CNN) 健康卡** — `fng-sched` 调度器状态：`healthy` / `degraded`（CNN 不可达，
   改用 VIX 代理回退）/ `down`（连续失败 ≥3 次）/ `unknown`，并显示数据源（live CNN vs VIX proxy）、
   当前分值、最后成功时间、当前时段与刷新间隔、下次运行、连续失败数与最后错误。CNN 端点坏掉即在此显示
3. **数据新鲜度网格** — 每个关键表的最新时间戳（相对时间显示，如 "2h ago"）
4. **Symbol 覆盖** — 实时 1min 流的 symbol 数、instruments 总数、活跃 ticker 数

数据来源：实时服务状态从 `_watchdog.health.services` 读取；Fear & Greed 健康从 `app.state.fng_health`
（由调度器线程发布）读取，状态由 `datasources.py:_fng_status` 推导；新鲜度通过 `SELECT max(timestamp_col)` 查询。

---

### F. Model Performance — 模型性能

**端点**: `GET /api/admin/models/performance`
**轮询**: 5 分钟

**展示内容**:
1. **模型文件信息** — XGBoost 和 RandomForest 的文件路径、大小、最后修改时间
2. **Feature Importance** — 从 pickle 模型中提取 top 15 特征重要性，纯 CSS 水平条形图可视化
3. **Signal 分布** — signal_cache 中的 LONG/SHORT/NEUTRAL 计数、平均置信度

---

### G. User Management — 用户管理

**端点**:
- `GET /api/admin/users/stats` — 聚合统计
- `GET /api/admin/users` — 分页列表（支持搜索、tier 筛选）
- `PATCH /api/admin/users/{id}` — 修改 tier / 封禁（JSON body: `UserUpdateRequest`）

**展示内容**:
1. **统计卡片** — 总用户数、已验证、今日注册、本周注册
2. **Tier 分布** — FREE/PRO/PREMIUM/ADMIN 各多少人（可点击筛选）
3. **用户表格** — email、名称、tier（点击可改）、状态（Active/Banned 可切换）、注册时间
4. **分页控制** — 上/下页、总页数

**安全限制**:
- 不能修改自己的 tier（防止自降级）
- 不能封禁自己（防止锁死）
- tier 必须是有效值（FREE/PRO/PREMIUM/ADMIN）
- PATCH body 通过 `UserUpdateRequest` Pydantic model 校验

---

### H. Manual Actions — 手动触发

**端点**:
- `POST /api/admin/actions/{action}` — 触发任务
- `GET /api/admin/actions/task/{task_id}` — 查询任务状态

**7 个可触发的操作**:

| 操作 | Celery 任务 | 队列 | 说明 |
|------|-------------|------|------|
| Refresh Signals | `refresh_top100` | ml_inference | 刷新 Top-100 信号缓存 |
| Retrain Models | `run_daily_pipeline` | ml_inference | 完整日间 ML 训练流程 |
| Scrape Social | `scrape_social_media` | default | 抓取 Twitter + Reddit |
| Fetch Earnings | `fetch_earnings` | default | 拉取 Finnhub 财报数据 |
| Fetch Holdings | `fetch_celebrity_holdings` | default | 拉取国会/13F/ARK 持仓 |
| Refresh News | `refresh_hot_news` | default | 刷新热门 ticker 新闻 |
| Validate Symbols | `validate_symbol_requests` | default | 验证用户请求的 symbol |

**前端交互流程**:
1. 点击按钮 → POST 触发 → 返回 `task_id`
2. 每 3 秒轮询 `GET /api/admin/actions/task/{task_id}`（最多 60 次 = 3 分钟超时）
3. 显示 spinning 动画直到 SUCCESS/FAILURE
4. 5 秒后自动恢复为 idle 状态
5. 组件卸载时 `mountedRef` 阻止后续 setState

**技术细节**:
- Celery 实例创建时同时传入 `broker` 和 `backend`（两者都是 Redis），确保 `task_result` 端点能读到结果

---

### I. System Logs — 系统日志

**端点**: `GET /api/admin/logs?lines=200&level=INFO`
**轮询**: 手动刷新 / 可选 10 秒自动刷新

**实现机制**:
后端使用 `AdminLogBuffer`（继承 `logging.Handler`），内部维护一个 `deque(maxlen=2000)` 作为内存 ring buffer，在 app lifespan 启动时挂到 root logger。

**优点**: 不依赖文件系统、不需要外部日志服务、Docker 环境通用。
**缺点**: 只捕获 FastAPI 进程的日志，不包含 Celery worker 日志（worker 的失败通过 D 面板的任务状态追踪）。

**前端功能**:
- 5 级 severity 筛选按钮（DEBUG/INFO/WARNING/ERROR/CRITICAL）
- 等宽字体滚动容器，颜色编码（红=ERROR、黄=WARNING、灰=INFO）
- Auto 按钮切换 10 秒自动刷新
- 手动 Refresh 按钮

---

## 前端布局

```
┌─────────────────────────────────────────────────────┐
│  System Health Overview  (全宽)                       │
├────────────────────────┬────────────────────────────┤
│  Database Health        │  Tasks & Workers            │
├────────────────────────┴────────────────────────────┤
│  Data Sources  (全宽)                                 │
├────────────────────────┬────────────────────────────┤
│  Model Performance      │  Manual Actions             │
├────────────────────────┴────────────────────────────┤
│  User Management  (全宽)                              │
├────────────────────────┬────────────────────────────┤
│  API Endpoints          │  System Logs                │
└────────────────────────┴────────────────────────────┘
```

页面使用 `max-w-7xl`（比普通页面更宽），双栏用 `grid lg:grid-cols-2 gap-6` 实现响应式布局。

---

## 主题支持

所有组件同时支持 light mode 和 dark mode：
- 文字: `text-zinc-700 dark:text-zinc-300`
- 背景: `bg-zinc-50 dark:bg-zinc-900/40`
- 边框: `border-zinc-200 dark:border-zinc-800`
- 强调色: `text-emerald-600 dark:text-emerald-400` 等双色调
- 骨架屏: `bg-zinc-200 dark:bg-zinc-800`

---

## 错误处理

所有面板组件都有三种状态：
1. **Loading** — 骨架屏动画
2. **Error** — 红色错误文案 + Retry 按钮（点击触发 `refetch()`）
3. **Success** — 正常数据展示

HealthOverview 额外有全局错误样式（红色边框卡片）。

---

## 轮询策略

每个面板使用 TanStack React Query 的 `refetchInterval` 独立轮询，频率根据数据变化速度设置：

| 面板 | 轮询间隔 | 原因 |
|------|----------|------|
| Health Overview | 30s | 服务状态变化较慢 |
| Database | 60s | 表统计信息变化很慢 |
| Endpoints | 60s | 路由注册基本不变 |
| Tasks | 15s | 任务可能随时完成 |
| Data Sources | 30s | 实时流需要及时发现断连 |
| Models | 5min | 模型一天最多重训一次 |
| Users | 60s | 用户注册频率不高 |
| Logs | 手动/10s | 按需查看，避免不必要的流量 |

---

## 访问控制（四层保护）

1. **ADMIN 账号自动创建**: 启动时 `check_and_seed_admin()` 确保 ADMIN 用户存在，密码与 `.env` 同步
2. **Navbar 入口隐藏**: 仅 `user.tier === "ADMIN"` 时，在用户菜单下拉和移动端菜单中显示 "Admin" 链接
3. **前端页面门控**: `useAuth()` 检查 → 非 ADMIN 显示 "Access Denied" 卡片 + 返回按钮
4. **后端 API 保护**: 所有端点使用 `Depends(require_tier("ADMIN"))`，非 ADMIN 用户请求返回 403

---

## 文件清单

### 新建 (24 个文件)

**后端 (13)**:
- `backend/app/api/routes/admin/__init__.py`
- `backend/app/api/routes/admin/router.py`
- `backend/app/api/routes/admin/health.py`
- `backend/app/api/routes/admin/database.py`
- `backend/app/api/routes/admin/tasks.py`
- `backend/app/api/routes/admin/datasources.py`
- `backend/app/api/routes/admin/models.py`
- `backend/app/api/routes/admin/users.py`
- `backend/app/api/routes/admin/actions.py`
- `backend/app/api/routes/admin/logs.py`
- `backend/app/schemas/admin.py`
- `backend/app/core/utils.py`
- `docs/admin-dashboard.md`

**前端 (11)**:
- `frontend/src/app/admin/page.tsx`
- `frontend/src/components/admin/StatusDot.tsx`
- `frontend/src/components/admin/HealthOverview.tsx`
- `frontend/src/components/admin/DatabaseHealth.tsx`
- `frontend/src/components/admin/EndpointHealth.tsx`
- `frontend/src/components/admin/TaskStatus.tsx`
- `frontend/src/components/admin/DataSourceStatus.tsx`
- `frontend/src/components/admin/ModelPerformance.tsx`
- `frontend/src/components/admin/UserManagement.tsx`
- `frontend/src/components/admin/ManualActions.tsx`
- `frontend/src/components/admin/SystemLogs.tsx`

### 修改 (8 个文件)

- `backend/app/main.py` — lifespan 中初始化 AdminLogBuffer + 暴露 watchdog 到 `app.state`
- `backend/app/core/startup.py` — 添加 `check_and_seed_admin()` ADMIN 账号自愈
- `backend/app/core/config.py` — 添加 `ADMIN_EMAIL` / `ADMIN_PASSWORD` 配置项
- `ml/tasks/celery_app.py` — 添加 Celery 信号处理器（task_prerun/success/failure → Redis）
- `frontend/src/lib/api.ts` — 添加 `admin` API 命名空间（12 个方法）
- `frontend/src/lib/types.ts` — 添加 admin 相关 TypeScript 类型定义
- `frontend/src/components/layout/Navbar.tsx` — ADMIN 用户显示管理入口链接
- `frontend/src/app/auth/login/page.tsx` — ADMIN 登录后自动跳转 `/admin`
