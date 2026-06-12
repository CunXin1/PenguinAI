# Repo Split Plan / 仓库拆分计划 — Public vs Private

Goal: keep the core IP (ML algorithms, signal pipeline, data ingestion, the future
paid Pro tier) **private**, while exposing a clean, open-source **public** repo
(frontend + curated docs) as the project's showcase.

目标：核心资产（ML 算法、信号流水线、数据采集、未来付费 Pro 版）放 **私有库**；
对外只开源一个干净的 **公开库**（前端 + 精选文档）作为门面。

---

## 0. Findings from the current repo / 现状盘点

Audited before writing this plan:

- [x] **No secrets in git history.** `.env` was never committed; no `.p8`/`.pem`/`*.key`
  ever added. `.gitignore` already covers `.env*`. 历史里没有泄露密钥，干净。
- [x] **Frontend is self-contained.** Nothing under `frontend/src` imports from
  `backend/`, `ml/`, or `data/`. It talks to the backend only over HTTP via
  `lib/api.ts`, with the contract mirrored in `lib/types.ts`. 前端零跨目录依赖，可独立抽出。
- [x] **No large/binary blobs tracked.** `data/30min_data`, `data/daily_data`, `models/`
  are gitignored. History is small (87 commits). 没有大文件，历史轻量。
- [x] Current remote: `github.com/CunXin1/PenguinAI` — **currently public**.

Implication: the only thing protecting the IP is *removing it from a public repo's
history*, not scrubbing secrets. The algorithms themselves are what must stop being public.

关键结论：要保护的是**算法本身别再留在公开库的历史里**，而不是清密钥（密钥本来就没泄露）。
所以公开库不能携带 `ml/` `data/` 的历史 —— 必须用 path 过滤或全新历史来建。

---

## 1. Recommended target architecture / 推荐目标架构

```
penguinai           (PRIVATE)  ← existing repo flipped to private. Full monorepo,
                                 full history, all code. This is the source of truth.
                                 现有库改私有，保留全部历史和代码，作为唯一开发源。

penguinai-web       (PUBLIC)   ← NEW repo. frontend/ + curated docs + marketing README.
                                 Built fresh so ml/ and data/ never enter its history.
                                 新建公开库，只含前端+精选文档，历史全新，绝不含核心代码。
```

**Source of truth = the private monorepo.** Develop everything there. The public web
repo is a **curated downstream mirror** — you push the frontend (and approved docs) out
to it on a cadence. Keeps the contract (`types.ts` ↔ backend schemas) in one place and
avoids two-repo coordination overhead.

唯一开发源 = 私有 monorepo。公开库是它的**下游精选镜像**，定期把前端推出去。
这样前后端契约只在一处维护，不用两库来回对。

> Why not the reverse (keep `CunXin1/PenguinAI` public, strip it)? Stripping files in a
> new commit leaves `ml/`/`data/` in the **history** of a public repo — anyone can
> `git log` them back. Flipping the existing repo to private is one click and loses nothing.
> 为什么不保留现有库为公开再删文件？删了历史里还在，公开库谁都能翻出来。直接转私有最稳。

### Alternative (only if you must keep `frontend/` developed in the open)
True two-repo split: frontend lives **only** in the public repo, backend/ml/data only in
private. Cost: you hand-sync the API contract across two repos forever. Not recommended
for a solo/small team. 备选：彻底两库分家，代价是 API 契约要长期人工对齐，小团队不划算。

---

## 2. Public vs Private split / 文件归属

### Goes PUBLIC (`penguinai-web`)
| Path | Notes |
|------|-------|
| `frontend/` | The whole Next.js app. Self-contained. |
| `docs/frontend-pages.md` | UI documentation, no IP. |
| `README.md` | **Rewrite** into a marketing/landing README (screenshots, "what it is", links to penguinai.com). Strip internal infra details. |
| `LICENSE` | **Add one** (see Decision C). |
| `.github/` workflows | Frontend-only CI (tsc + next lint + build). Drop backend jobs. |
| `frontend/.env.example` | Public-safe (just `NEXT_PUBLIC_API_BASE_URL`). |

### Stays PRIVATE (`penguinai` monorepo)
| Path | Why |
|------|-----|
| `ml/` | Core IP: XGBoost/RF trainers, FEATURE_COLS, Gemma agents, RAG, signal pipeline. |
| `data/` | All ingestion + scrapers + source integrations (competitive intel). |
| `backend/` | API gateway, auth, signal orchestration, chat agent, admin. |
| `db/` | Schema reveals the full data model. |
| `scripts/`, `Makefile`, `docker-compose.yml`, `nginx/` | Infra/ops. |
| `CLAUDE.md` | Reveals entire architecture + data sources + roadmap. **Never publish.** |
| `docs/` (most) | signal-pipeline, architecture, roadmap, data-sources, llm-*, backend-startup, admin-dashboard, deployment, celebrity-holdings, earnings, news-module, oauth, setup-checklist, changelog, api-reference. All reveal IP or internals. |
| `TODO.md`, this file | Internal. |

### Docs needing a decision (see Decision B)
`docs/api-reference.md` (1051 lines — full endpoint list) and `docs/oauth.md` could be
public if you want an open/published API surface, or stay private. Default: **private**.

---

## 3. Decisions you need to make / 待你拍板

- **Decision A — repo names & visibility.** Recommended: existing `CunXin1/PenguinAI`
  → **private** (keep name, or rename to `penguinai`); new public repo `penguinai-web`.
  Confirm names. 确认命名与可见性。
- **Decision B — how much docs go public.** Default = only `frontend-pages.md` + a new
  marketing README. Decide if `api-reference.md` should be public (open API) or private.
  决定 api-reference 是否公开。
- **Decision C — license for the public repo.** If you ever want to stop others from
  reselling your frontend, MIT/Apache-2.0 still allow that. Consider source-available
  (BSL/PolyForm-Noncommercial) if you want "look but don't compete." Or no license =
  all-rights-reserved (viewable, not legally reusable). 选公开库的许可证。

---

## 4. Migration TODO / 执行清单

> Do these in order. Nothing here is destructive to the private monorepo. 按序执行，私有库零风险。

### Phase 1 — Lock down the IP first (do this immediately)
- [ ] On GitHub: `CunXin1/PenguinAI` → Settings → Danger Zone → **Change visibility to Private.**
      先把现有公开库转为私有，立刻止血。
- [ ] Confirm collaborators/CI tokens still work after the flip.
- [ ] (Optional) Rotate any API keys that were only ever in your local `.env` but might
      have been pasted in issues/PRs/screenshots while public. History is clean, but
      double-check past PR descriptions. 检查历史 PR/issue 文本里有没有贴过密钥。

### Phase 2 — Build the public web repo (fresh, IP-free history)
- [ ] Create empty public repo `penguinai-web` on GitHub (no README/license yet).
- [ ] Locally, extract `frontend/` + chosen docs into it with **path-filtered history**
      (preserves frontend commit history, never carries ml/data). Two options:
      - **Clean slate (simplest):** new repo, copy `frontend/` in, single initial commit.
        丢历史，最省事。
      - **Keep frontend history:** `git filter-repo --path frontend/ --path docs/frontend-pages.md`
        on a clone, then push. 保留前端历史，用 filter-repo 只留这些路径。
- [ ] Flatten paths if desired (move `frontend/*` to repo root so it's a standalone app).
- [ ] Add `LICENSE` (Decision C), rewrite `README.md` for a public audience.
- [ ] Add frontend-only `.github/workflows/ci.yml` (tsc --noEmit + next lint + next build).
- [ ] Verify it builds standalone: `npm install && npm run build` with a dummy
      `NEXT_PUBLIC_API_BASE_URL`. 确认能独立构建。

### Phase 3 — Wire the public API contract for outsiders
- [ ] Public frontend points at your hosted API (`NEXT_PUBLIC_API_BASE_URL=https://api.penguinai...`).
- [ ] Decide CORS: backend `ALLOWED_ORIGINS` must include the public frontend's deploy
      origin (e.g. Vercel preview + prod domains). 后端 CORS 要放行公开前端域名。
- [ ] Document in the public README that the backend is proprietary and not included.
      README 里说明后端闭源、不包含在内。

### Phase 4 — Establish the sync workflow (private → public)
- [ ] Write a small script `scripts/export_public_web.sh` in the **private** repo that:
      copies `frontend/` + approved docs into a checkout of `penguinai-web`, commits, pushes.
      在私有库写个导出脚本，定期把前端同步到公开库。
- [ ] Decide cadence: per-release, or on every frontend change. Manual is fine to start.
- [ ] (Optional, later) Replace the script with a `git subtree split`/push flow if you
      want commit-level history sync. 以后想要逐提交同步可换 subtree。

### Phase 5 — Cleanup & guardrails
- [ ] Add a CI check in the **public** repo that fails if `backend/`, `ml/`, `data/`, or
      `CLAUDE.md` ever appear (prevents accidental IP leak on a bad sync). 公开库加守卫 CI。
- [ ] Add `SECURITY.md` + issue templates to the public repo if you want contributions.
- [ ] Update internal `docs/` to note the two-repo layout. 内部文档记一下双库结构。

---

## 5. Gotchas / 注意事项

- The existing public URL was already indexed/forkable. Flipping to private stops *future*
  exposure; anything already cloned can't be recalled. That's fine — the live IP keeps
  evolving privately. 已被 fork 的收不回，但后续开发都在私有库，问题不大。
- `frontend/lib/types.ts` is the contract with the backend. When it goes public, you're
  publishing your API shape. That's usually acceptable for a SaaS, but be aware. 公开 types 等于公开 API 形状。
- Don't let the sync script copy `frontend/.env.local` or any real env file. Only
  `.env.example`. 同步脚本别带真实 env。
- Keep `CLAUDE.md` out of the public repo permanently — it's a full architecture leak.

---

## 6. One-line summary / 一句话

Flip the current repo to **private** now (Phase 1), then publish a **fresh-history**
`penguinai-web` containing only `frontend/` + a marketing README + license, kept in sync
from the private monorepo by a small export script.

先把现有库转私有，再新建一个全新历史的 `penguinai-web` 公开库（只含前端+README+license），
由私有库的导出脚本定期同步。
