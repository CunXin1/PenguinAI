# Backend TODO — 走向成熟可部署的工业化后端

> 目标:把当前「MVP 骨架」推进到「生产就绪 / 工业化」。
> 现状基线(2026-06):API 网关骨架完整,与 CLAUDE.md 设计约束一致;CI/CD(AWS)/docker-compose/nginx/.env.example 均已就位。
> 缺口集中在:**测试、迁移版本、安全加固、可观测性、可靠性、部署加固**。
>
> 优先级:**P0 阻断**(CI 红 / 正确性 / 安全漏洞)→ **P1 基线**(测试 / 迁移)→ **P2 工业化**(安全 / 观测 / 可靠性)→ **P3 部署加固** → **P4 功能补全**。
> 勾选规则:每项都带**验收标准**,达成才勾。

---

## P0 — 阻断项(必须先做)

### 修复 CI 会失败的 lint
- [ ] **`== True` → `.is_(True)`**(触发 ruff **E712**,CI `ruff check app/` 直接红;且 `make lint-fix` 会自动改成 `is True` 破坏 SQLAlchemy 语义)
  - 位置:`app/api/deps.py:27`、`app/api/routes/auth.py:42`、`app/api/routes/tickers.py:21`、`app/api/routes/tickers.py:41`
  - 验收:`ruff check app/` 与 `ruff format --check app/` 全绿。

### 修复权限 / 正确性
- [ ] **冷门股缺 PRO 门控** — `GET /api/signals/{ticker}`(`app/api/routes/signals.py:55`)当前任意登录用户即可触发任意 ticker 的 Celery 计算。按 CLAUDE.md「全 2000 股 = PRO」,应对非 Top-100 标的加 `require_tier("PRO","PREMIUM")` 或在触发前判定。
  - 验收:FREE 用户请求冷门股返回 403;PRO 用户正常 202。
- [ ] **`/api/signals/top` 信息泄漏复核** — `signals.py:39` 无鉴权、不按 tier 过滤,会把 `tier_required=PRO/PREMIUM` 标的的 direction/confidence 暴露给匿名用户。
  - 决策:确认是否为有意 teaser。若是→在文档与代码注释中标明;若否→按 tier 过滤或脱敏高 tier 字段。
  - 验收:行为有明确产品语义并有测试覆盖。
- [ ] **自选股缺 tier 上限** — `watchlist.py:48` FREE 用户可无限添加。补 FREE/PRO 数量上限(配置化)。
  - 验收:超限返回 402/403 并有测试。
- [ ] **tier 逻辑去重(DRY)** — `signals.py:82 _check_tier_access` 与 `deps.py:36 require_tier` 各有一套 tier 排序。合并到 `app/core` 或 `deps` 单一来源。
  - 验收:仅一处定义 tier rank,两处调用同一函数。

### 启动期配置校验
- [ ] **生产环境禁止默认密钥** — `config.py:14 SECRET_KEY="change_me"`。增加校验:`DEBUG=false` 时若 `SECRET_KEY in {"change_me",""}` 直接启动失败。
  - 验收:生产配置缺失关键 env 时进程拒绝启动并给出清晰错误。

---

## P1 — 测试与迁移基线

### 测试(CI 已就绪,`tests/` 存在即自动跑)
- [ ] **搭建 `backend/tests/`** — `conftest.py` 提供:测试 DB(事务回滚 fixture 或独立 test schema)、`httpx.AsyncClient` + ASGITransport、已认证用户 fixture、Celery `send_task` mock。
  - 依赖补充:`pytest`、`pytest-asyncio`、`httpx`(已在 requirements)、`pytest-cov`。
- [ ] **认证测试** — 注册成功/重复邮箱 409、登录成功/错误密码 401、`/me` 带/不带 token、过期 token。
- [ ] **分层权限测试** — `require_tier` 各 tier 矩阵、ADMIN 绕过、冷门股 PRO 门控。
- [ ] **信号测试** — 缓存命中 200、缓存未命中 202 且触发 Celery(mock 验证 task name/args/queue)、过期缓存视为 miss、ticker 格式校验 422。
- [ ] **自选股测试** — 增/删/查、重复添加 409、不存在 ticker 404、tier 上限。
- [ ] **K线测试** — 三种 timeframe、days 边界、ticker 大小写归一。
- [ ] **覆盖率门槛** — 接入 `pytest --cov=app --cov-fail-under=70`,逐步提到 85%。
  - 验收:`make test` 实跑且 CI 中 backend job 跑测试通过,覆盖率达标。

### 数据库迁移
- [ ] **生成 Alembic baseline 迁移** — 目前 `db/migrations/` 只有 `env.py`/模板,无版本文件;线上靠 `make db-init` 直灌 SQL,无可追踪历史。基于现有 4 张 ORM 表生成初版迁移,并与 `db/schema/*.sql` 对齐(TimescaleDB hypertable / pgvector 的特殊 DDL 用迁移内 `op.execute()` 显式写)。
  - 验收:`alembic upgrade head` 在空库可重建出与 `db/schema` 一致的关系表;`alembic check`(autogenerate diff)为空。
- [ ] **部署期自动迁移** — 容器 entrypoint 或 CD 步骤执行 `alembic upgrade head`(幂等),取代手工 `db-init`。
  - 验收:CD 部署流程包含迁移且失败可回滚。

### 类型检查转阻断
- [ ] **mypy 清零并去掉 `continue-on-error`** — CI `ci.yml:66` 当前 mypy 非阻断。逐步补类型(尤其 `get_db` 返回 `AsyncGenerator`、路由返回模型),最终改为阻断。
  - 验收:`mypy app/` 无错误且 CI 中转为 blocking。

---

## P2 — 工业化:安全 / 可观测性 / 可靠性

### 安全加固
- [ ] **限流(Rate limiting)** — 对注册/登录/信号触发等加 Redis 后端限流(`slowapi` 或自研中间件)。区分匿名 IP 与用户维度。
  - 验收:超限返回 429,登录爆破被有效抑制。
- [ ] **登录防爆破** — 失败次数退避 / 临时锁定(Redis 计数)。
- [ ] **JWT 体系完善** — 增加 refresh token + 短期 access token;支持登出/撤销(Redis token 黑名单或 jti 版本号);`decode_access_token` 区分过期 vs 非法。
  - 验收:登出后旧 token 立即失效;access token 寿命缩短到分钟级。
- [ ] **安全响应头** — HSTS、X-Content-Type-Options、X-Frame-Options、Referrer-Policy 等(可在 `nginx/nginx.conf` 统一加,或 FastAPI 中间件)。
- [ ] **CORS 收紧** — 生产 `ALLOWED_ORIGINS` 不含 localhost;校验配置。
- [ ] **请求体大小 / 超时限制** — 防止大体积请求拖垮进程。
- [ ] **依赖漏洞扫描** — CI 接入 `pip-audit`(dependabot 已有,补主动扫描)。
- [ ] **Secrets 管理** — 生产从 AWS Secrets Manager / SSM 注入,而非明文 `.env`;`SECRET_KEY`/`DB_PASSWORD` 轮转方案。
  - 验收:仓库与镜像内无任何明文密钥;CD 注入通过。

### 可观测性
- [ ] **结构化日志** — JSON 日志(`structlog` 或标准 logging+formatter)+ request-id 中间件(贯穿到 Celery 派发)。
- [ ] **全局异常处理 + 统一错误响应** — `@app.exception_handler`,统一 `{error, detail, request_id}` schema;未捕获异常不泄漏堆栈到客户端。
- [ ] **健康检查分层** — 现 `/health`(`main.py:41`)为静态。补:
  - `/health/live`(进程存活,k8s liveness)
  - `/health/ready`(探测 DB + Redis 连通,k8s readiness)
  - 验收:依赖不可用时 `/ready` 返回 503。
- [ ] **指标(Metrics)** — `prometheus-fastapi-instrumentator` 暴露 `/metrics`(QPS、延迟、错误率、缓存命中率)。
- [ ] **错误上报** — 接入 Sentry(或等价),关联 request-id。
- [ ] **(可选)分布式追踪** — OpenTelemetry,串联 API → Redis → Celery → DB。

### 可靠性 / 性能
- [ ] **冷门股触发幂等去重** — `_trigger_signal_computation`(`signals.py:27`)同一 ticker 短时间多次请求会重复入队。用 Redis 锁/标记(TTL=计算预期时长)避免重复触发(防缓存击穿/惊群)。
  - 验收:并发请求同一冷门股只派发一次 Celery 任务。
- [ ] **Celery 派发容错** — broker 不可用时 `send_task` 异常需捕获并返回 503,而非 500;考虑超时。
- [ ] **DB 连接池调优** — `database.py` 引擎加 `pool_pre_ping=True`、连接/语句超时;按部署规格校准 `pool_size`/`max_overflow`。
- [ ] **查询/索引复核** — `signals.py:39` `order_by(confidence)`、`tickers` 排序等是否走索引;`signal_cache` 已有 `idx_signal_expires`,确认热路径有覆盖索引。
- [ ] **分页统一** — `universe` 已有 offset/limit;`top`、`watchlist` 统一分页与上限,响应带 total/cursor。
- [ ] **Redis 读缓存(可选)** — 对 `/top`、`universe` 等热读加短 TTL 缓存,减 DB 压力。
- [ ] **优雅关闭** — lifespan 中 dispose engine、等待在途请求;uvicorn/gunicorn `--graceful-timeout`。

---

## P3 — 部署加固

### 容器
- [ ] **Dockerfile 加固**(`backend/Dockerfile`):
  - 非 root 用户运行;`.dockerignore`(排除 `__pycache__`、`.env`、测试)
  - multi-stage(构建/运行分离,减体积)
  - 基础镜像固定到 digest(供应链安全)
  - `HEALTHCHECK` 指向 `/health/live`
  - 用 gunicorn + uvicorn worker,worker 数按 CPU 配置化(现为写死 `--workers 4`)
  - 验收:镜像非 root、体积合理、healthcheck 生效。

### 部署流程
- [ ] **CD 复核** — `.github/workflows/cd-aws.yml` 与 P1 自动迁移、健康检查、回滚策略对齐;蓝绿/滚动发布;迁移失败阻断发布。
- [ ] **API 版本化** — 路由前缀引入 `/api/v1`,为未来 breaking change 留余地(同步更新前端 `lib/api.ts`)。
- [ ] **配置完整性校验** — 启动时校验全部必填 env(Pydantic Settings + 显式断言),缺失即 fail-fast。
- [ ] **负载/压力测试** — k6 或 locust 基准:目标 QPS、p99 延迟、缓存命中率;纳入发版前检查。
- [ ] **DB 备份/恢复演练** — TimescaleDB 备份策略(WAL/快照)与恢复 runbook。
- [ ] **运行手册(Runbook)** — 常见故障(DB down、Redis down、Celery 积压)排查流程。

---

## P4 — 功能补全(产品向)

- [ ] **OAuth 实现** — `auth.py:57` 当前 501。落地 Google/Apple(config 已留字段),与邮箱账号合并逻辑。
- [ ] **PREMIUM API Key 访问** — 发放/吊销 API key,基于 key 的限流与计费维度(CLAUDE.md 标注 future)。
- [ ] **用户自助** — 改密、修改资料、登出、注销账号(GDPR/数据删除)。
- [ ] **Tier 升级链路** — 支付 webhook → 更新 `users.tier`(对接 Stripe 等)。
- [ ] **Admin 增强** — 用户管理、手动缓存失效、模型热重载触发、审计日志(admin 操作留痕)。
- [ ] **审计与合规** — 关键操作审计表;信号「仅供参考、非投资建议」免责声明在 API 响应/文档体现。

---

## 验收总览(Definition of Done — 工业化)

- [ ] CI 全绿:`ruff check` + `ruff format --check` + `mypy`(blocking)+ `pytest`(覆盖率 ≥85%)
- [ ] `alembic upgrade head` 可在空库重建全部 schema,迁移纳入 CD
- [ ] 限流 + JWT 撤销 + secrets 外部注入 + 安全头齐备
- [ ] 结构化日志 + `/metrics` + `/health/{live,ready}` + Sentry 上线
- [ ] 冷门股触发幂等 + Celery 派发容错 + 连接池调优
- [ ] Docker 非 root/multi-stage/healthcheck;CD 含自动迁移与回滚
- [ ] 压测达标(目标 QPS/p99 有基线数据)+ 备份恢复演练通过
