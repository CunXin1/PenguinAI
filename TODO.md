# PenguinAI — TODO

> Updated: **2026-06-12**

---

## 1. 完善 ML 层
- [ ] 拉起真实 Gemma 服务跑通线上（当前未起服务时自动降级为 ML-only fallback）
- [ ] **B-综合（高优先，解决 Top Signal 全挤 50%）**：把 keyed horizon 模型喂进
      `signal_engine`/`gemma_agent`，让 Gemma 综合 全跨度ML + 新闻/FinBERT + 指标 + 价量 + 财报 +
      宏观 成一个信号；confidence 重标定为跨源/跨跨度一致性，而非单个贴近 0.5 的概率。
- [ ] registry 按 `{basket}__{tf}__{label}` 多模型 serving + 篮子外回退全局；用上 `basket_for(ticker)`。
- [ ] 1 天档：等 1min / 聚合 10min bar 数据就绪再训（trainer 已支持任意 timeframe）。
- [ ] 前端跨度切换按钮（信号页 1周/1月/3月，复用 PriceChart segmented 样式）。
- [ ] 完整 universe + 更长历史（since 2015）重训，让 AUC 站稳；规划 smallcap/wholemarket 篮子。
- [ ] 实现 Reddit scraper（PRAW）+ Twitter scraper（Playwright），填充 social_posts
- [ ] 实现 fetch_fundamentals（yfinance / Massive），填充 fundamentals 表（`ml/tasks/daily_pipeline.py` 仍是空 stub）
- [ ] 补全 ml/tests（trainer、model_registry、celery tasks 测试覆盖）
- [ ] 集成 MLflow 实验追踪 + 模型版本管理
- [ ] 模型 drift 监控 + 预测质量回测框架
- [ ] RAG pgvector ivfflat 索引调优

## 2. 后端重启自愈 + 数据补全机制
- [ ] 启动时检测 data/30min_data 是否存在，缺失则触发 Massive 30min 拉取
- [ ] Celery worker 启动时自动 load models，失败则 log + 降级运行
- [ ] 各 API 数据源断线重连 + 重试逻辑

## 3. 完善前端 UI/UX
- [ ] 移动端响应式优化（dashboard 卡片布局、图表触控交互）
- [ ] Loading skeleton 统一风格（替换各处不一致的 loading 状态）
- [ ] 图表交互增强：tooltip、crosshair、时间范围拖拽
- [ ] 信号卡片迷你 sparkline + 当日涨跌幅
- [ ] 暗色主题微调：对比度、hover 状态、focus ring
- [ ] 错误/空状态页面统一设计
- [ ] 1D 图表依赖 market_data_1min（实时流），无流时应 fallback 到 bars_30m 当天数据

## 4. 用户界面
- [ ] /profile 页面补全：修改显示名、头像上传（密码修改已完成）
- [ ] 用户 tier 展示 + 升级引导（FREE → PRO → PREMIUM）
- [ ] Watchlist 排序自选股（增删 + 登录用户后端持久化已完成）
- [ ] 通知偏好设置：邮件提醒、信号推送
- [ ] 用户操作历史 / 最近查看的 ticker
- [ ] Auth store（zustand）+ protected routes + token 过期处理

## 5. About 界面
- [ ] /about 页面：产品介绍、团队信息、技术架构概览
- [ ] 信号生成方法论说明（ML + NLP + LLM pipeline 的非技术解释）
- [ ] 免责声明：信号仅供参考，非投资建议
- [ ] 隐私政策 + 服务条款
- [ ] 联系方式 / 反馈入口

## 6. 完善财报界面
- [ ] 财报前后股价反应图（earnings event overlay on price chart）— 目前仅数值徽章 + EPS sparkline，缺 K 线 overlay
- [ ] 按 surprise 排序（日期分组 + ticker 搜索已有，surprise 排序缺失）
- [ ] 与信号联动：财报 surprise 如何影响信号置信度的可视化（信号页目前仅并列展示财报）
- [ ] incoming→past 时间兜底：report_date 已过但 Finnhub 未回填 eps_actual 的行会永久停留在 upcoming 并显示负倒计时，需按日期剔除/折叠

## 7. Chat Agent 花活（OpenAI Agents SDK 路径增强）

> 已建：Phase 0-5 全部完成,开关 `CHAT_AGENT_SDK=true`。harness 在 `ml/inference/agents/`,
> 前端卡片 `frontend/src/components/chat/ChatCards.tsx`。下面是后续增强。

### 新卡片类型（沿用 card_sink → SSE `{type:"card"}` → ChatCards 渲染的现有体系）
- [ ] 信号卡片：把 `get_signal` 的 ML 输出做成带置信度进度条 + 多空配色的卡片（小）
- [ ] 财报卡片：`get_earnings` 的 EPS 实际/预期/surprise% 做成小表格卡片（小）
- [ ] 对比表卡片："对比 A/B" 时出一张并排指标表（价格/PE/信号/RSI）（中）
- [ ] watchlist 卡片：`analyze_watchlist` 的 verdict 列表做成可排序卡片（中）
- [ ] 图表卡片叠加指标：chart card 复用 PriceChart 的 `indicators` 参数叠 MA/RSI（中）

### 多 agent 体验
- [ ] sub-agent 实时进度：watchlist fan-out 时流式显示"正在分析 NVDA... AAPL..."而非干等
      （需要一条 progress 旁路,类似 card_sink,让 runner 在长工具执行期间也能 yield）（中）
- [ ] "should I buy X" 升级为多 lens：technical / fundamental / sentiment 各一个 sub-agent 再综合（中）

### 上下文管理（目前是静态裁剪,"动态"部分基本未做）
- [ ] **修 bug(优先,小):历史取的是"最旧 20 条"而非"最近 20 条"** —— 路由
      `backend/app/api/routes/chat.py` 两处 `order_by(created_at) ASC + limit(CHAT_MAX_HISTORY)`,
      应改为 `DESC + limit + reverse`,否则对话超过 20 条后丢最近上下文(agent"忘记刚说的话")
- [ ] 摘要/压缩:超过 `CHAT_MAX_HISTORY` 时把旧轮总结成一段再塞回,而非硬截断丢弃（中）
- [ ] 按 token 预算裁剪而非按轮数:几条超长消息也能撑爆窗口,应按实际 token 预算滚动（中）
- [ ] 语义召回 / RAG:按相关性把久远的相关历史消息找回来,而非只留最近 N 轮（大）
- [ ] (现状记录)工具结果不跨轮持久化、sub-agent 上下文隔离 已做 —— 见 §7 顶部

### 模型与质量
- [ ] orchestrator 切更大模型：`CHAT_MAIN_MODEL=gemma4:e4b` 或外部 API,文字更顺（极小,改配置；
      注意 e4b 偶尔多调工具/串票,需观察）
- [ ] 提示词调优:e2b 取数后偶尔回一句寒暄而非描述走势,可在 prompt 里强制"取数后简述走势"

### 工具
- [ ] `get_portfolio`:真正接持仓表(需新建 `portfolio`/`positions` 表 + 录入)（大）

### 安全 / 身份
- [ ] 身份保护:对外只认"PenguinAI 助手",绝不暴露底层模型 —— 现在问"which model are you"会答
      "trained by Google"(暴露 Gemma)。在 system prompt 加身份规则:不透露厂商/模型名/架构（小）
- [ ] 系统提示词防泄露:已能拒绝"tell me your system prompt"(抗注入有效),但加显式规则 + 固化成测试用例（小）
- [ ] prompt injection / 越狱测试集:"ignore all previous instructions"、角色扮演、越权访问他人
      watchlist 等,纳入 `ml/tests`(对话面是 NEW attack surface,见 CLAUDE.md 安全条款)（中）

### 收尾 / 运维
- [ ] 观察期(soak)后把 `CHAT_AGENT_SDK` 提为默认,并删除旧 `ml/inference/chat/` 手写 loop
- [ ] 非流式 `POST /messages`(send_message)路径补 card 持久化(当前仅流式 endpoint 带 cards)
- [ ] 为 SDK 路径补端到端测试(带 fake model),覆盖 runner 的 card/tool/done 事件映射

---

## 代码中的 TODO / 缺口

### 前端 mock 数据
- [ ] `frontend/src/lib/mock.ts` — `MOCK_USER`/`MOCK_UNIVERSE` 已无引用，可删；仅 `mockSignalDetail` 仍被个股页用作降级
- [ ] `frontend/src/app/signals/[ticker]/page.tsx` — 网络/超时错误降级到 demo data（`setView("demo")`），考虑改为明确错误提示（向用户展示虚构信号有合规隐患）

### 数据库迁移
- [ ] Alembic baseline 缺失 — `db/migrations/versions/` 为空，schema 仍靠 docker-entrypoint SQL 创建
- [ ] 生成 baseline migration，对齐 ORM models 和 db/schema/*.sql，部署走 alembic upgrade head
