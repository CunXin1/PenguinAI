# Backend TODO — 走向成熟可部署的工业化后端

> 目标:把当前「MVP 骨架」推进到「生产就绪 / 工业化」。
> 现状基线(2026-06-08):API 网关完整;鉴权加固(密码强度+forgot/reset/change-password+timing-safe+rate limiting);market_clock(exchange_calendars);SupervisorWatchdog;测试套件 63 tests;database.py SQLite 兼容。
> 缺口集中在:**tier 正确性、覆盖率门槛、迁移版本、安全加固进阶、可观测性、可靠性、部署加固**。
>
> 优先级:**P0 阻断** → **P1 基线** → **P2 工业化** → **P3 部署加固** → **P4 功能补全**。

---

## P0 — 阻断项

### 修复权限 / 正确性
- [ ] **`/api/signals/top` 信息泄漏复核** — 无鉴权、不按 tier 过滤,会把 `tier_required=PRO/PREMIUM` 标的暴露给匿名用户。确认是否为有意 teaser 并补文档/测试。
- [ ] **自选股缺 tier 上限** — FREE 用户可无限添加。补 FREE/PRO 数量上限(配置化)。
  - 验收:超限返回 402/403 并有测试。
- [ ] **tier 逻辑去重(DRY)** — `signals.py _check_tier_access` 与 `deps.py require_tier` 各有一套 tier 排序。合并到单一来源。

### 启动期配置校验
- [ ] **生产环境禁止默认密钥** — `config.py SECRET_KEY="change_me"`。`DEBUG=false` 时若 SECRET_KEY 为默认值直接启动失败。

---

## P1 — 测试与迁移基线

### 测试补全
- [ ] **覆盖率门槛** — 接入 `pytest --cov=app --cov-fail-under=70`,逐步提到 85%。
- [ ] **补充 auth 测试缺口** — 未覆盖:`POST /forgot-password`、`POST /reset-password`(含过期/无效 token)、`POST /change-password`(含旧密码错误)、密码强度校验拒绝(弱密码 422)。约需 ~6–8 tests。

### 数据库迁移
- [ ] **生成 Alembic baseline 迁移** — `db/migrations/` 仍无版本文件;线上靠 `make db-init` 直灌 SQL。基于现有 ORM 表生成初版迁移,与 `db/schema/*.sql` 对齐。
  - 验收:`alembic upgrade head` 在空库可重建全部 schema;`alembic check` diff 为空。
- [ ] **部署期自动迁移** — 容器 entrypoint 执行 `alembic upgrade head`(幂等),取代手工 `db-init`。

### 类型检查转阻断
- [ ] **mypy 清零并去掉 `continue-on-error`** — CI 当前 mypy 非阻断。逐步补类型,最终改为 blocking。

---

## P2 — 工业化:安全 / 可观测性 / 可靠性

### 安全加固
- [ ] **限流扩展** — 当前仅 register/login/forgot/reset,需扩展到信号触发等端点;区分匿名 IP vs 用户维度。
- [ ] **登录防爆破** — 失败次数退避/临时锁定(Redis 计数)。当前 rate limiter 按 IP 限流但不按失败次数累计。
- [ ] **JWT 体系完善** — refresh token + 短期 access token;登出/撤销(Redis 黑名单或 jti)。
- [ ] **安全响应头** — HSTS、X-Content-Type-Options、X-Frame-Options、Referrer-Policy。
- [ ] **CORS 收紧** — 生产 `ALLOWED_ORIGINS` 不含 localhost。
- [ ] **请求体大小 / 超时限制**。
- [ ] **依赖漏洞扫描** — CI 接入 `pip-audit`。
- [ ] **Secrets 管理** — 生产从 AWS Secrets Manager/SSM 注入,非明文 `.env`。

### 可观测性
- [ ] **结构化日志** — JSON 日志 + request-id 中间件。
- [ ] **全局异常处理 + 统一错误响应** — 未捕获异常不泄漏堆栈到客户端。
- [ ] **健康检查分层** — 补 `/health/live`(liveness) + `/health/ready`(探测 DB+Redis,readiness)。
- [ ] **指标(Metrics)** — `prometheus-fastapi-instrumentator` 暴露 `/metrics`。
- [ ] **错误上报** — 接入 Sentry,关联 request-id。

### 可靠性 / 性能
- [ ] **冷门股触发幂等去重** — 用 Redis 锁避免同 ticker 重复入队。
- [ ] **Celery 派发容错** — broker 不可用时捕获异常返回 503。
- [ ] **查询/索引复核** — 确认热路径有覆盖索引。
- [ ] **分页统一** — `top`、`watchlist` 统一分页与上限。
- [ ] **优雅关闭** — lifespan 中 dispose engine;`--graceful-timeout`。

---

## P3 — 部署加固

### 容器
- [ ] **Dockerfile 加固** — 非 root、multi-stage、digest 固定、`HEALTHCHECK`、gunicorn worker 数配置化。

### 部署流程
- [ ] **CD 复核** — 与自动迁移、健康检查、回滚策略对齐。
- [ ] **API 版本化** — 路由前缀引入 `/api/v1`。
- [ ] **配置完整性校验** — 启动时校验全部必填 env,缺失即 fail-fast。
- [ ] **负载/压力测试** — k6 或 locust 基准。
- [ ] **DB 备份/恢复演练**。
- [ ] **运行手册(Runbook)**。

---

## P4 — 功能补全(产品向)

- [x] **OAuth 实现** — Google + Apple 已接入(authorize→callback→id_token 验签→find-or-create→签发 JWT;无状态签名 state)。见 `core/oauth.py` + `auth.py`。**上线前需**:在 Google/Apple 控制台创建凭据并填 `.env`(`GOOGLE_CLIENT_ID/SECRET`、`APPLE_CLIENT_ID/TEAM_ID/KEY_ID/PRIVATE_KEY`)。
- [x] **验证 / 重置邮件发送** — 已接入 `core/email.py`(`EMAIL_BACKEND=smtp` 走 SMTP,否则 console 兜底);register / resend-verification / forgot-password 三处均已发送。**上线前需**:配置 `SMTP_*`。
- [ ] **PREMIUM API Key 访问** — 发放/吊销 API key + 限流/计费。
- [ ] **用户自助** — 修改资料、登出、注销账号(GDPR/数据删除)。
- [ ] **Tier 升级链路** — 支付 webhook → `users.tier`。
- [ ] **Admin 增强** — 用户管理、缓存失效、模型热重载、审计日志。
- [ ] **审计与合规** — 操作审计表;「非投资建议」免责声明。

---

## 验收总览(Definition of Done — 工业化)

- [ ] CI 全绿:`ruff check` + `ruff format --check` + `mypy`(blocking)+ `pytest`(覆盖率 ≥85%)
- [ ] `alembic upgrade head` 可在空库重建全部 schema,迁移纳入 CD
- [ ] 限流全端点 + JWT 撤销 + secrets 外部注入 + 安全头齐备
- [ ] 结构化日志 + `/metrics` + `/health/{live,ready}` + Sentry 上线
- [ ] 冷门股触发幂等 + Celery 派发容错
- [ ] Docker 非 root/multi-stage/healthcheck;CD 含自动迁移与回滚
- [ ] 压测达标 + 备份恢复演练通过
