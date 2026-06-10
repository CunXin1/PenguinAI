# PenguinAI — TODO

> Updated: **2026-06-09**

---

## 1. 完善 ML 层
- [ ] 接入 Gemma 4 LLM（vLLM 本地部署或 Vertex AI），替换当前 ML-only fallback
- [ ] 实现 Reddit scraper（PRAW）+ Twitter scraper（Playwright），填充 social_posts
- [ ] 实现 fetch_fundamentals（yfinance / Massive），填充 fundamentals 表
- [ ] 补全 ml/tests（trainer、model_registry、celery tasks 测试覆盖）
- [ ] 集成 MLflow 实验追踪 + 模型版本管理
- [ ] 模型 drift 监控 + 预测质量回测框架
- [ ] RAG pgvector ivfflat 索引调优

## 2. 后端重启自愈 + 数据补全机制
- [ ] 启动时检测 data/30min_data 是否存在，缺失则触发 Massive 30min 拉取
- [ ] Celery worker 启动时自动 load models，失败则 log + 降级运行
- [ ] 各 API 数据源断线重连 + 重试逻辑

## 3. FOMC 完善 ✅
- [x] CME FedWatch 市场预期利率概率
- [x] 利率图表时间跨度选择器（1Y/3Y/5Y/10Y/ALL）
- [x] Hawk/Dove 趋势可调数量滑块
- [x] SPY 市场反应合并到 Hawk/Dove 面板（Tabbed）
- [x] 会议日程默认过去10次 + 未来10次
- [x] 声明默认显示10条 + Show More
- [x] 数字参数可通过 config.py / .env 配置
- [x] Fed/FOMC 新闻模块（Google News RSS）
- [x] 全屏布局修复（max-w-7xl + lg:grid-cols-3）
- [x] 组件拆分到 frontend/src/components/fomc/

## 4. 完善前端 UI/UX
- [ ] 移动端响应式优化（dashboard 卡片布局、图表触控交互）
- [ ] Loading skeleton 统一风格（替换各处不一致的 loading 状态）
- [ ] 图表交互增强：tooltip、crosshair、时间范围拖拽
- [ ] 信号卡片迷你 sparkline + 当日涨跌幅
- [ ] 暗色主题微调：对比度、hover 状态、focus ring
- [ ] 错误/空状态页面统一设计
- [ ] 3M/1Y 图表数据显示修复（fallback 到 bars_1d 已修，需验证）

## 5. 用户界面
- [ ] /profile 页面完善：修改显示名、头像上传、密码修改
- [ ] 用户 tier 展示 + 升级引导（FREE → PRO → PREMIUM）
- [ ] Watchlist 管理：添加/删除/排序自选股，后端持久化（替换 localStorage）
- [ ] 通知偏好设置：邮件提醒、信号推送
- [ ] 用户操作历史 / 最近查看的 ticker
- [ ] Auth store（zustand）+ protected routes + token 过期处理
- [ ] 邮件验证和密码重置的邮件发送对接（SES / Resend）

## 6. About 界面
- [ ] /about 页面：产品介绍、团队信息、技术架构概览
- [ ] 信号生成方法论说明（ML + NLP + LLM pipeline 的非技术解释）
- [ ] 免责声明：信号仅供参考，非投资建议
- [ ] 隐私政策 + 服务条款
- [ ] 联系方式 / 反馈入口

## 7. 完善财报界面
- [ ] 财报前后股价反应图（earnings event overlay on price chart）— 目前仅数值徽章 + EPS sparkline，缺 K 线 overlay
- [ ] 按 surprise 排序（日期分组 + ticker 搜索已有，surprise 排序缺失）
- [ ] 与信号联动：财报 surprise 如何影响信号置信度的可视化（信号页目前仅并列展示财报）
- [ ] incoming→past 时间兜底：report_date 已过但 Finnhub 未回填 eps_actual 的行会永久停留在 upcoming 并显示负倒计时，需按日期剔除/折叠

---

## 代码中的 TODO / 缺口

### 后端 auth — 邮件发送未对接
- [ ] `backend/app/api/routes/auth.py:73` — TODO: send verification email with link containing verify_token
- [ ] `backend/app/api/routes/auth.py:121` — TODO: send verification email（resend）
- [ ] `backend/app/api/routes/auth.py:168` — TODO: send email with reset link containing token
- [ ] 对接邮件服务（SES / Resend / SendGrid），替换当前只 log token 的行为

### 后端 auth — OAuth 未实现
- [ ] `backend/app/api/routes/auth.py:227` — OAuth（Google / Apple）返回 501，需实现

### ML — fetch_fundamentals stub
- [ ] `ml/tasks/daily_pipeline.py:85` — fetch_fundamentals 是空 stub，需接 yfinance 或 Massive

### 前端 mock 数据残留
- [ ] `frontend/src/lib/mock.ts` — MOCK_USER、MOCK_UNIVERSE 仍被 screener 和个股页 fallback 使用
- [ ] `frontend/src/app/signals/[ticker]/page.tsx:81` — 网络错误时降级到 demo data，应改为错误提示
- [ ] Screener 页面仍读 MOCK_UNIVERSE，需对接 /api/tickers/universe 真实数据

### 前端 Watchlist — localStorage 未迁移
- [ ] `frontend/src/hooks/useWatchlist.ts` — guest 用户用 localStorage，登录用户需迁移到后端 /api/watchlist

### 数据库迁移
- [ ] Alembic baseline 缺失 — db/migrations/versions/ 为空，schema 仍靠 docker-entrypoint SQL 创建
- [ ] 生成 baseline migration，对齐 ORM models 和 db/schema/*.sql，部署走 alembic upgrade head

### 前端图表
- [ ] 3M/1Y 图表 fallback 已修（market_data.py），Docker 重启后需验证
- [ ] 1D 图表依赖 market_data_1min（实时流），无流时应 fallback 到 bars_30m 当天数据
