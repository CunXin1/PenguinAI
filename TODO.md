# PenguinAI — TODO

> Updated: **2026-06-09**

---

## 1. 完善 ML 层
- [ ] 接入 Gemma 4 LLM（vLLM 本地部署或 Vertex AI），替换当前 ML-only fallback
- [ ] 实现 Reddit scraper（PRAW）+ Twitter scraper（Playwright），填充 social_posts
- [ ] 实现 fetch_fundamentals（yfinance / Massive），填充 fundamentals 表
- [ ] FOMC 声明抓取 + hawk/dove NLP 打分，填充 fomc_statements
- [ ] 补全 ml/tests（trainer、model_registry、celery tasks 测试覆盖）
- [ ] 集成 MLflow 实验追踪 + 模型版本管理
- [ ] 模型 drift 监控 + 预测质量回测框架
- [ ] RAG pgvector ivfflat 索引调优

## 2. 后端重启自愈 + 数据补全机制
- [ ] 启动时检测 data/30min_data 是否存在，缺失则触发 Massive 30min 拉取
- [ ] 启动时检测 bars_30m 行数，为 0 则自动运行 import pipeline
- [ ] 启动时检测 signal_cache 是否过期/为空，自动触发 refresh_top100
- [ ] Celery worker 启动时自动 load models，失败则 log + 降级运行
- [ ] 健康检查端点 /api/health：返回 DB、Redis、models、data freshness 状态
- [ ] docker-compose 加 ml-worker 服务，确保 Celery worker 随栈启动
- [ ] earnings 数据自动拉取（Finnhub API，设置 FINNHUB_API_KEY 后自动生效）
- [ ] 各 API 数据源断线重连 + 重试逻辑

## 3. Admin Page
- [ ] /admin 路由，仅 ADMIN tier 可访问
- [ ] Pipeline 状态面板：bars_30m/1d 行数、signal_cache 新鲜度、Celery task 最后执行时间
- [ ] 手动触发按钮：refresh_top100、retrain models、scrape social、fetch earnings
- [ ] 模型性能看板：最新 CV AUC、feature importance 图表
- [ ] 用户管理：查看/修改用户 tier、封禁账户
- [ ] 系统日志查看器

## 4. 个股新闻板块
- [ ] /signals/[ticker] 页面下方增加该 ticker 专属新闻 feed
- [ ] 后端端点 GET /api/news/ticker/{ticker}，从 Finnhub company news API 拉取
- [ ] FinBERT 实时打分每条新闻，显示 bullish/bearish/neutral 标签
- [ ] 新闻情绪聚合条：展示该股近期舆论方向

## 5. 新闻板块只展示热门股票
- [ ] 主页 /news 只显示 MAG7 + Top ETF 等核心标的的新闻
- [ ] 冷门股票新闻不在主页加载，减少 API 调用和页面噪声
- [ ] 用户在个股页面点击后按需搜索并展示该股新闻
- [ ] 新闻搜索/筛选功能：用户可输入 ticker 查看相关新闻

## 6. FOMC 新闻板块
- [ ] /fomc 页面：历次 FOMC 会议声明 + hawk/dove 打分时间线
- [ ] 可视化 hawk_dove_score 趋势图（影响全局信号的宏观过滤器）
- [ ] 下次会议倒计时 + 市场预期利率概率（CME FedWatch）
- [ ] 后端：SEC EDGAR FOMC 声明抓取 + NLP hawk/dove 分类器

## 7. 完善前端 UI/UX
- [ ] 移动端响应式优化（dashboard 卡片布局、图表触控交互）
- [ ] Loading skeleton 统一风格（替换各处不一致的 loading 状态）
- [ ] 图表交互增强：tooltip、crosshair、时间范围拖拽
- [ ] 信号卡片迷你 sparkline + 当日涨跌幅
- [ ] 暗色主题微调：对比度、hover 状态、focus ring
- [ ] 错误/空状态页面统一设计
- [ ] 3M/1Y 图表数据显示修复（fallback 到 bars_1d 已修，需验证）

## 8. 用户界面
- [ ] /profile 页面完善：修改显示名、头像上传、密码修改
- [ ] 用户 tier 展示 + 升级引导（FREE → PRO → PREMIUM）
- [ ] Watchlist 管理：添加/删除/排序自选股，后端持久化（替换 localStorage）
- [ ] 通知偏好设置：邮件提醒、信号推送
- [ ] 用户操作历史 / 最近查看的 ticker
- [ ] Auth store（zustand）+ protected routes + token 过期处理
- [ ] 邮件验证和密码重置的邮件发送对接（SES / Resend）

## 9. About 界面
- [ ] /about 页面：产品介绍、团队信息、技术架构概览
- [ ] 信号生成方法论说明（ML + NLP + LLM pipeline 的非技术解释）
- [ ] 免责声明：信号仅供参考，非投资建议
- [ ] 隐私政策 + 服务条款
- [ ] 联系方式 / 反馈入口

## 10. 完善财报界面
- [ ] /earnings 页面：未来一周财报日历（Finnhub earnings calendar）
- [ ] 已公布财报：EPS actual vs estimate、surprise %、beat/miss 标签
- [ ] 财报前后股价反应图（earnings event overlay on price chart）
- [ ] 按日期 / ticker / surprise 排序和筛选
- [ ] 与信号联动：财报 surprise 如何影响信号置信度的可视化
