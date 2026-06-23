# Roadmap / TODO

Planned enhancements, grouped by area. Each item notes which existing pieces to
reuse so the work stays consistent with the codebase. Status: all `TODO` (not built).

## English

### A. Chat assistant — rich, interactive replies

The chat agent (`docs/llm-chat-agent.md`) currently replies in plain text. Enrich it
so replies can render interactive cards inline, reusing existing components.

Design note (shared by A1-A3): the agent already knows which ticker/entity a tool was
called for. Extend the SSE stream with a new frame
`{"type":"card","kind":"chart|watchlist|news","ticker":"NVDA", ...}` emitted when the
relevant tool runs, and persist a compact "attachments" list on the assistant
message. The frontend renders the card under the message bubble. This keeps the model
text-only (no HTML from the model) while the UI stays rich and safe.

- [ ] **A1. Inline stock chart card.** When a reply discusses a specific ticker (e.g.
  "how is NVDA doing"), render the price chart under the reply. Reuse
  `frontend/src/components/charts/PriceChart.tsx` (TradingView Lightweight Charts),
  possibly a compact variant. Trigger: a `get_quote` / `get_history` / `get_indicators`
  tool call on a ticker emits a `card` frame; the page renders `<PriceChart ticker=.../>`.
- [ ] **A2. Inline watchlist card.** When the user asks about their watchlist, render
  it inline. Reuse `frontend/src/components/dashboard/WatchlistWidget.tsx` /
  `useWatchlist.ts`. Trigger: the `get_watchlist` tool call emits a `card` frame.
- [ ] **A3. Clickable news links.** When a reply references news, show the headlines as
  links that open the source. The `get_news` tool already returns `url` + `source` +
  `finbert_score` per article; surface them as a `card` (kind `news`) and render a small
  list reusing `frontend/src/components/dashboard/NewsPreview.tsx` styling.
- [ ] **A4. ML-backed bull/bear explanation.** Let the assistant explain bullish vs
  bearish using the EXISTING ML models. Add a read-only tool `get_signal(ticker)` that
  returns the cached signal from `signal_cache` (direction, confidence, `xgb_prob_up`,
  `rf_prob_up`, `ensemble_prob`, `ai_attribution`). The agent then explains the lean in
  words. Backed by the existing signal pipeline — no new model needed.
- [ ] **A5. "Should I buy X?" comprehensive view.** When asked whether a stock is
  worth it, the agent orchestrates several tools in one turn — `get_signal` (ML
  ensemble), `get_quote` + `get_history` (price/volume), `get_news` (sentiment),
  `get_fundamentals`, `get_earnings` — and synthesizes a balanced summary. Must stay
  signals-only: present the evidence and the model's lean, never a personalized
  buy/sell instruction. Reuses A1-A4 cards for the visuals.

### B. ML modeling — specialization

> **Status update — partly built; see `docs/ml-specialization.md`.** Per-*symbol* models
> (B1 as originally written) were **rejected** (overfit: ~16k bars/symbol, very low
> signal-to-noise). Built instead: per-**basket** × horizon models (`ml/models/baskets.py`
> `nasdaq10`; 1w on 30m direction, 1m/3m on daily beat-SPY). CV leakage was fixed
> (`purged_walk_forward_splits`). **Now built:** registry multi-model serving
> (`model_registry.predict_basket_horizons`) + global fallback for non-basket tickers,
> and the Gemma multi-horizon *synthesis* that fixes the ~50% confidence clustering
> (`signal_engine` + `gemma_agent`; serves daily features via the `indicators_daily`
> view; narrowed 0.52/0.48 band; confidence = cross-horizon agreement, no longer shown in
> the frontend). Still open: the 1-day tier (pending 1-min/10-min data) and the frontend
> horizon switcher (per-horizon probs are available but not yet surfaced as a UI toggle).

Today there is one global classifier (`ml/models/xgboost_trainer.py`,
`horizon_bars=16`, ~1.2 trading days). Extend to per-symbol and multi-horizon models.

- [ ] **B1. Per-symbol specialized models.** Train models tuned per symbol (or per
  cluster of similar symbols) instead of one global model, so a ticker's own dynamics
  are captured. Extend `xgboost_trainer.train()` to filter by symbol and persist
  per-symbol artifacts; the registry (`ml/models/model_registry.py`) loads the right
  one at serve time, falling back to the global model when a per-symbol model is absent.
- [ ] **B2. Multi-horizon models per symbol.** For the same stock, train separate
  models for different horizons: ~1 week, ~1 month, ~6 months, and long-term. The
  trainer already parameterizes `horizon_bars`; loop over a horizon set, persist one
  artifact per (symbol, horizon), and surface all horizons in the signal output /
  `get_signal` tool so the assistant can discuss short- vs long-term lean.

Notes for B: keep train/serve parity (the serving features must match the trainer's
`FEATURE_SQL` / `indicators_30min`). Per-symbol + multi-horizon multiplies the model
count, so plan storage/registry keys (`{symbol}__{horizon}`) and a retraining schedule
in the Celery beat / daily pipeline.

### C. Compliance — personalized-advice guardrail (HIGH PRIORITY, blocks launch)

Context: a chatbot that gives SPECIFIC stock picks tailored to a user's personal
situation (risk tolerance, visa/student status, capital) can be treated as acting as
an unregistered Investment Adviser under US securities law. "We never execute trades"
only avoids the Broker-Dealer issue — it does NOT cover the Investment Adviser issue.
The SEC's test is essentially whether the advice is PERSONALIZED; the publisher's
exemption is lost the moment the model matches specific tickers to a user's personal
profile. (This is the product owner's compliance plan captured as TODO, NOT legal
advice — consult a securities attorney before any public or paid launch.)

Do NOT delete the feature. The fix is de-personalization + disclaimers, landing it in a
compliant zone. C1 + C3 are the immediate must-do before any wider rollout.

- [ ] **C1. De-personalize the agent (most important).** Update the chat System Prompt
  so the model REFUSES personalized recommendations. When a user gives personal info
  (risk tolerance, F1/student status, capital), it must NOT match picks to that profile.
  Instead: (a) explicitly decline personalized advice, then (b) convert the ask into
  general education or a mechanical, factor-based screen over the public, fixed AI pool.
  Example — replace "since you're low-risk, buy VOO and AAPL" with "I can't give
  personalized advice. Low-volatility investors often look at broad ETFs; here are 5
  names our model's low-volatility factor surfaces, as research data." Where:
  `ml/inference/chat/agent.py:SYSTEM_PROMPT` and `backend/app/services/chat_llm.py:SYSTEM_PROMPT`.
- [ ] **C2. Frame the bot as a screener over a public, fixed pool.** It must not invent
  bespoke lists. Have it select from the site's public, all-users AI stock pool (e.g. the
  Top-100), phrased as "I filtered our public AI strategy pool for the 'low-volatility'
  tag." Adviser = tailoring a custom suit; screener = picking from clothes already on the
  rack for everyone. Safe as long as outputs come from a fixed, public, person-independent
  pool. Ties into A4/A5 (`get_signal`).
- [ ] **C3. UI legal defenses.** (a) First-entry consent modal that must be accepted
  before chatting. (b) Persistent small-print under the input box: "AI assistant is for
  quantitative data retrieval and education only; it does not provide personalized
  financial planning." (c) Auto-append a disclaimer under every reply that contains a
  ticker: "Displayed stocks are generated purely from mechanical screening parameters.
  This is not personalized financial advice." Where: `frontend/src/app/chat/page.tsx`.
- [ ] **C4. Launch posture (F1-safe).** Now (free beta): keep the chatbot, ship C1 + C3
  immediately — free + de-personalized reads as an academic/hobby project, low risk.
  Future (paid Pro): prefer keeping the interactive chatbot in the FREE tier, or in the
  paid tier expose only a STATIC "AI daily picks" page (no interactive personalization).
  Static list + paywall = squarely within the publisher exemption; interactive chatbot +
  paywall is a grey area — avoid it while on an F1 visa.

### D. Broader compliance audit (beyond the chatbot)

Findings from a read of the codebase. Same caveat as C: captured as TODO, NOT legal
advice — consult a securities attorney + a privacy counsel before a public/paid launch.
Two flavors of risk here: (i) US securities law (impersonal-publisher posture), and
(ii) data-licensing / privacy law.

- [ ] **D1. No legal pages or site-wide disclaimer (HIGH).** There are no Terms of
  Service, Privacy Policy, or Disclaimer pages, and no global footer — a "not financial
  advice" line exists only on `/chat` and `/pricing`. Add `/terms`, `/privacy`,
  `/disclaimer` pages and a persistent footer carrying: "Informational/impersonal
  research signals only. PenguinAI is not a registered investment adviser or
  broker-dealer and does not provide personalized advice or execute trades." Where:
  `frontend/src/app/{terms,privacy,disclaimer}/page.tsx` + a `Footer` component in
  `frontend/src/app/layout.tsx`.
- [ ] **D2. Performance / track-record claims.** `ProfileUser.win_rate` (and
  `lib/mock.ts win_rate: 63`) is a performance statistic. Showing any win-rate / return
  / accuracy number — especially a fabricated/mock one — is high-risk (anti-fraud +
  SEC marketing rules). Audit every user-facing stat: remove fabricated numbers, and if
  a real metric is shown, substantiate it, state the methodology, and add "past
  performance does not guarantee future results." Where: `frontend/src/lib/types.ts`
  (`ProfileUser`), `lib/mock.ts`, `frontend/src/app/profile/page.tsx`.
- [ ] **D3. Per-signal disclaimer + framing.** Signals (`LONG/SHORT/NEUTRAL`,
  confidence, `ai_analysis`) are impersonal (same for all users) — keep them that way to
  stay in the publisher zone. Add a short disclaimer on the signal cards / dashboard
  ("model output, not a buy/sell instruction"), and review the signal-pipeline prompt
  (`ml/inference/gemma_agent.py`) to ensure `ai_analysis` never uses imperative
  "you should buy/sell" phrasing. The product copy "signal recommendations"
  (`frontend/src/app/layout.tsx` description) could read as advice — consider
  "signals / analytics."
- [ ] **D4. Privacy + data deletion (GDPR/CCPA).** There is no account-deletion endpoint
  and no data export. The app stores PII (emails) and user free-text chat history (which
  may contain personal/financial details, e.g. the F1 example). Add: a Privacy Policy
  (D1), a `DELETE /api/auth/account` (or `/users/me`) that hard-deletes the user (cascades
  already remove conversations/messages/watchlist), an optional data export, and a chat
  retention policy. Minimize what chat history stores. Where: `backend/app/api/routes/auth.py`,
  `frontend/src/app/profile/page.tsx`.
- [ ] **D5. Market-data redistribution licensing.** The dashboard shows real-time prices
  to end users (IBKR / Finnhub / Massive), and pricing advertises "real-time coverage."
  Redistributing exchange/real-time market data to public users typically requires a
  redistribution agreement and may incur exchange fees; each provider's ToS must be
  checked. Options: confirm redistribution rights per provider, switch public display to
  delayed data where required, or add the required attributions/agreements. Where:
  `data/ingestion/realtime/*`, `frontend` market displays, `/pricing` copy.
- [ ] **D6. Third-party ToS for sourced data.** Before building the (currently stub)
  Twitter/Reddit scrapers, note that scraping X/Reddit generally violates their ToS —
  use the official APIs or drop the source. Quiver Quant (congressional trades) has
  redistribution terms to honor; SEC EDGAR 13F/13D is public domain (OK); arkfunds.io and
  Finnhub each have ToS. Where: `data/scrapers/*` (planned), `data/celebrity/*`,
  `data/news/*`.
- [ ] **D7. "Smart Money" framing.** Celebrity/congressional holdings are presented under
  a "Smart Money" label (`frontend/src/app/celebrity-holdings/...`). Keep it as factual
  public-disclosure data; avoid "follow/copy these trades" language that implies a
  recommendation. Add a note that 13F/disclosure data is delayed and informational.
- [ ] **D8. Paid customization vs advice (reinforces C4).** Pro ($10/mo) advertises
  "Train your own stock ML models — tune signals on tickers you pick" plus higher AI chat
  limits. Keep "train your own model" framed as a user-configured impersonal TOOL/screener
  (the user sets the parameters; the output is mechanical), not a personalized advisory
  service sold for a fee. Pair with C1/C2 so paid + interactive never becomes
  personalized-advice-for-compensation. Where: `frontend/src/app/pricing/page.tsx`, the
  future per-symbol training (B1).

Priority order: D1 + D2 are the fastest high-impact wins (legal pages + kill fabricated
performance stats). D4 (deletion) and D5 (data licensing) are the heavier items to plan
before charging money or scaling.

## 中文

### A. 聊天助手 —— 富交互回复

聊天 agent(见 `docs/llm-chat-agent.md`)目前只回纯文本。增强它,让回复能内联渲染
交互卡片,复用已有组件。

设计说明(A1-A3 共用):agent 本就知道某次工具调用是针对哪个 ticker/实体。给 SSE
流加一种新帧 `{"type":"card","kind":"chart|watchlist|news","ticker":"NVDA", ...}`,
在相关工具运行时发出,并在助手消息上持久化一个紧凑的 "attachments" 列表。前端在气泡
下方渲染卡片。这样模型仍只产出文本(不让模型吐 HTML),UI 既丰富又安全。

- [ ] **A1. 内联股票图表卡片。** 当回复谈到某个具体 ticker(如"NVDA 表现如何"),
  在回复下方渲染走势图。复用 `frontend/src/components/charts/PriceChart.tsx`
  (TradingView Lightweight Charts),可做一个紧凑变体。触发:对某 ticker 的
  `get_quote` / `get_history` / `get_indicators` 调用发出 `card` 帧,页面渲染
  `<PriceChart ticker=.../>`。
- [ ] **A2. 内联自选股卡片。** 用户问自选股时内联渲染。复用
  `frontend/src/components/dashboard/WatchlistWidget.tsx` / `useWatchlist.ts`。
  触发:`get_watchlist` 调用发出 `card` 帧。
- [ ] **A3. 可跳转的新闻链接。** 回复涉及新闻时,把标题做成可点击跳转源站的链接。
  `get_news` 工具本就返回每条的 `url` + `source` + `finbert_score`;以 `card`(kind
  `news`)呈现,复用 `frontend/src/components/dashboard/NewsPreview.tsx` 的样式渲染小列表。
- [ ] **A4. 基于 ML 模型的看涨/看跌说明。** 让助手用**已有的 ML 模型**解释看涨看跌。
  新增只读工具 `get_signal(ticker)`,从 `signal_cache` 返回缓存信号(direction、
  confidence、`xgb_prob_up`、`rf_prob_up`、`ensemble_prob`、`ai_attribution`),
  agent 据此用文字解释倾向。底层就是现有信号管线,不需要新模型。
- [ ] **A5. "这支股票推不推荐"的综合判断。** 当用户问某股值不值得时,agent 一轮内
  编排多个工具 —— `get_signal`(ML 集成)、`get_quote` + `get_history`(价量)、
  `get_news`(情绪)、`get_fundamentals`、`get_earnings` —— 综合成一个平衡的结论。
  必须保持"只出信号":呈现证据和模型倾向,绝不给个性化买卖指令。视觉上复用 A1-A4 卡片。

### B. ML 建模 —— 专门化

> **进展更新 —— 部分已建；详见 `docs/ml-specialization.md`。** 分 *symbol* 模型（原 B1）
> 已**否决**（过拟合：~1.6 万 bar/股、信噪比极低）。改建：分**篮子** × 跨度模型
> （`ml/models/baskets.py` 的 `nasdaq10`；1周用 30m 涨跌，1月/3月用日线 beat-SPY）。CV
> 泄漏已修（`purged_walk_forward_splits`）。仍待办：registry 多模型 serving + 全局回退、
> 1 天档（等 1min/10min 数据）、解决 ~50% confidence 聚集的 Gemma 多跨度*综合*、前端跨度
> 切换按钮。

目前是单一全局分类器(`ml/models/xgboost_trainer.py`,`horizon_bars=16`,约 1.2
个交易日)。扩展为分股票、分时间跨度的模型。

- [ ] **B1. 分 symbol 特训模型。** 按 symbol(或相似 symbol 的簇)训练专门模型,
  而不是一个全局模型,以捕捉个股自身的动态。扩展 `xgboost_trainer.train()` 按 symbol
  过滤并保存分 symbol 的模型;registry(`ml/models/model_registry.py`)在服务时加载
  对应模型,缺失时回退到全局模型。
- [ ] **B2. 同股票多时间跨度模型。** 对同一支股票,训练面向不同跨度的多个模型:
  约一周、约一个月、约半年、长期。trainer 已经把 `horizon_bars` 参数化;对一组跨度
  循环训练,按 (symbol, horizon) 各存一个模型,并在信号输出 / `get_signal` 工具里
  暴露所有跨度,这样助手能分别谈短期与长期倾向。

B 的注意:保持 train/serve 一致(服务特征必须匹配 trainer 的 `FEATURE_SQL` /
`indicators_30min`)。分 symbol + 多跨度会让模型数量翻倍,需规划存储/registry 键
(`{symbol}__{horizon}`)以及 Celery beat / daily pipeline 里的重训计划。

### C. 合规 —— 个性化投顾的防护栏(最高优先级,上线前必须处理)

背景:一个根据用户个人情况(风险承受度、签证/学生身份、资金量)给出**具体选股**的
聊天机器人,在美国证券法下可能被认定为"无牌投资顾问(Investment Adviser)"。
"我们完全不走交易"只能避开"无牌券商(Broker-Dealer)"的雷,**无法**避开"无牌投顾"
的雷。SEC 的核心判断标准就是建议是否**个性化(Personalized)**;一旦模型把特定股票
对号入座到用户的个人画像,出版商豁免权就丧失。(这是产品负责人的合规方案,作为 TODO
记录,**不构成法律意见**——任何公开或收费上线前请咨询证券律师。)

不要删功能。解法是"去个性化 + 免责声明",把功能降落到合规区。C1 + C3 是任何更大范围
推广前的**立即必做项**。

- [ ] **C1. 给 agent 去个性化(最重要)。** 改聊天的 System Prompt,让模型**拒绝**
  个性化推荐。当用户给出个人信息(风险承受度、F1/学生身份、资金量),不得把选股"对号
  入座"到该画像。而是:(a)明确拒绝个性化建议,(b)把问题转化为通用知识,或对"公开、
  固定的 AI 股票池"做机械的、基于因子的筛选。示范——把"既然你风险低,买 VOO 和 AAPL"
  换成"我无法提供个性化建议。低波动投资者通常关注宽基 ETF;以下是我们模型的低波动因子
  筛出的 5 个标的,供你作为研究素材。"位置:`ml/inference/chat/agent.py:SYSTEM_PROMPT`
  和 `backend/app/services/chat_llm.py:SYSTEM_PROMPT`。
- [ ] **C2. 把机器人定位成"对公开固定池的筛选器"。** 不能凭空捏造定制名单。让它从
  网站公开的、面向所有人的 AI 股票池(如 Top-100)里选,话术为"我帮你在我们公开的 AI
  策略库里,筛出了带'低波动'标签的标的"。投顾=量身定制西装;筛选器=从货架上本就挂着
  卖给所有人的衣服里挑。只要输出来自固定、公开、不因人而异的池子,就安全。与 A4/A5
  (`get_signal`)相关联。
- [ ] **C3. UI 法律防护。**(a)首次进入聊天的遮罩式同意弹窗,必须点同意才能对话。
  (b)输入框下方常驻小字:"AI 助手仅供量化数据检索与教学参考,不提供个性化理财规划。"
  (c)每条含股票代码的回复底部自动附带免责小字:"展示的股票纯粹基于机械筛选参数生成,
  不构成个性化投资建议。"位置:`frontend/src/app/chat/page.tsx`。
- [ ] **C4. 上线姿态(F1 安全)。** 现在(免费公测):保留聊天机器人,立刻上 C1 + C3
  ——免费 + 去个性化,属于学术/兴趣项目,风险低。未来(收费 Pro):优先把交互式聊天
  机器人放在**免费版**,或在收费版只暴露**静态的"AI 每日选股"页面**(无交互式个性化)。
  静态清单 + 收费 = 100% 落在出版商豁免内;交互式聊天 + 收费 是灰色地带——持 F1 签证
  期间避免。

### D. 更广的合规审计(聊天机器人之外)

读代码后的发现。与 C 同样的免责:作为 TODO 记录,**不构成法律意见**——公开/收费上线
前请咨询证券律师 + 隐私法律顾问。这里有两类风险:(i)美国证券法(保持"非个性化
出版商"姿态),(ii)数据许可 / 隐私法。

- [ ] **D1. 没有法律页面或全站免责(高优先)。** 没有服务条款、隐私政策、免责声明
  页面,也没有全站页脚——"非投资建议"只出现在 `/chat` 和 `/pricing` 两页。增加
  `/terms`、`/privacy`、`/disclaimer` 页面,以及一个常驻页脚:"仅提供信息性/非个性化
  研究信号。PenguinAI 不是注册投资顾问或券商,不提供个性化建议、不执行交易。"位置:
  `frontend/src/app/{terms,privacy,disclaimer}/page.tsx` + `layout.tsx` 里的 `Footer` 组件。
- [ ] **D2. 业绩 / 历史战绩宣称。** `ProfileUser.win_rate`(以及 `lib/mock.ts` 里的
  `win_rate: 63`)是业绩数字。展示任何胜率 / 收益 / 准确率——尤其是编造的/mock 的——
  风险很高(反欺诈 + SEC 营销规则)。审查每个面向用户的统计:删掉编造数字;若展示真实
  指标,需可被证实、说明计算口径,并加"过往业绩不代表未来表现"。位置:`lib/types.ts`
  (`ProfileUser`)、`lib/mock.ts`、`frontend/src/app/profile/page.tsx`。
- [ ] **D3. 每条信号的免责 + 措辞。** 信号(`LONG/SHORT/NEUTRAL`、置信度、`ai_analysis`)
  是非个性化的(对所有人相同)——保持这样才在出版商区。在信号卡片 / dashboard 上加一句
  简短免责("模型输出,非买卖指令"),并复查信号管线提示(`ml/inference/gemma_agent.py`),
  确保 `ai_analysis` 绝不用"你应该买/卖"的祈使语气。产品描述里的"signal recommendations"
  (`layout.tsx`)可能被读成建议,考虑改为"信号 / 分析"。
- [ ] **D4. 隐私 + 数据删除(GDPR/CCPA)。** 没有账号删除端点、没有数据导出。应用存了
  PII(邮箱)和用户自由文本聊天记录(可能含个人/财务细节,如 F1 那个例子)。增加:隐私
  政策(见 D1)、一个 `DELETE /api/auth/account`(或 `/users/me`)硬删除用户(级联已会
  删除会话/消息/自选股)、可选的数据导出、以及聊天保留策略。尽量少存聊天内容。位置:
  `backend/app/api/routes/auth.py`、`frontend/src/app/profile/page.tsx`。
- [ ] **D5. 行情数据再分发许可。** dashboard 向终端用户展示实时价格(IBKR / Finnhub /
  Massive),定价页宣传"实时覆盖"。把交易所/实时行情再分发给公众用户通常需要再分发协议、
  可能产生交易所费用;每家供应商的 ToS 都要查。选项:逐家确认再分发权限、必要处把公开
  展示改为延迟数据、或补齐所需的署名/协议。位置:`data/ingestion/realtime/*`、前端行情
  展示、`/pricing` 文案。
- [ ] **D6. 数据源的第三方 ToS。** 在做(目前是占位的)Twitter/Reddit 抓取器之前注意:
  抓取 X/Reddit 一般违反其 ToS——用官方 API 或放弃该源。Quiver Quant(国会交易)有
  再分发条款要遵守;SEC EDGAR 13F/13D 是公共领域(OK);arkfunds.io 和 Finnhub 各有
  ToS。位置:`data/scrapers/*`(计划中)、`data/celebrity/*`、`data/news/*`。
- [ ] **D7. "Smart Money"措辞。** 名人/国会持仓以"Smart Money"标签呈现
  (`frontend/src/app/celebrity-holdings/...`)。保持为客观的公开披露数据;避免"跟单/
  抄这些交易"这类暗示推荐的话术。加一句:13F/披露数据是延迟的、仅供参考。
- [ ] **D8. 收费定制 vs 投顾(强化 C4)。** Pro(每月 $10)宣传"训练你自己的股票 ML
  模型——在你选的票上调信号"加上更高的 AI 聊天额度。把"训练你自己的模型"定位为用户自行
  配置的**非个性化工具/筛选器**(参数由用户设,输出是机械的),而不是收费的个性化投顾
  服务。配合 C1/C2,确保"收费 + 交互"永远不变成"有偿个性化建议"。位置:
  `frontend/src/app/pricing/page.tsx`、未来的分 symbol 训练(B1)。

优先级:D1 + D2 是最快见效的高影响项(法律页面 + 删掉编造的业绩数字)。D4(删除权)和
D5(数据许可)是收费或扩张前要规划的较重项。
