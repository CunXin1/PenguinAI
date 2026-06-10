# Pre-launch Setup — What You Need To Do

## English

> All the code is written (login, registration, email/username login, email verification + reset, Google/Apple OAuth).
> This document lists only the parts **only you can do**: run commands, register with providers, fill `.env`.
> For the step-by-step Google/Apple registration, see **[oauth.md](./oauth.md)**; this file is the "what to do, in what order".

### Minimum to get it running (just two steps)

```bash
# 1) Apply the DB schema (adds users.username; idempotent, re-runnable)
make db-init
```
```dotenv
# 2) Fill the two Google vars in .env (Google login works then; localhost is fine)
GOOGLE_CLIENT_ID=xxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-xxxx
```
After these two steps: **email+password login, username login, Google login, and email verification (console mode)** all work.
Everything else (Apple, real email delivery, strong SECRET_KEY) is for the production stage.

### 1. Login + database

- [ ] `make db-init` — adds the `username` column to `users` (idempotent).
  - Existing old accounts have a null `username`: they can still log in by **email**, and the profile falls back to the email prefix; new sign-ups must provide a username.
  - Need to backfill usernames for old accounts? Ask me and I will write a backfill script.
- [ ] (Production only) set a strong random `SECRET_KEY` (JWT signing depends on it; if unset, every restart invalidates all logins):
  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(64))"
  ```
  ```dotenv
  SECRET_KEY=<the generated string>
  ```

Verify: start backend + frontend → register (username required) → log in with **email or username** → profile/navbar show the username.

### 2. Email (registration verification + password reset)

- It is in **console** mode now: no real mail, the link is logged to the **backend log**. Local testing needs **nothing** — register, then copy the verification link from the log.
- [ ] (Production) to actually send mail, pick an SMTP service and fill `.env`:
  ```dotenv
  EMAIL_BACKEND=smtp
  EMAIL_FROM=PenguinAI <no-reply@yourdomain.com>
  SMTP_HOST=smtp.yourprovider.com    # Gmail / SendGrid / AWS SES / Resend
  SMTP_PORT=587
  SMTP_USER=...
  SMTP_PASSWORD=...                   # Gmail: use an app password, not the login password
  SMTP_STARTTLS=true                  # for 587; for 465 set false + SMTP_SSL=true
  SMTP_SSL=false
  ```
- [ ] (Production) configure SPF / DKIM for the sending domain.

### 3. OAuth

Google — works now (localhost supported). Full steps in [oauth.md](./oauth.md) section 1. Key points:
- [ ] Google Cloud Console → OAuth consent screen (External, add your own email under Test users).
- [ ] Credentials → OAuth client ID → Web. Authorized redirect URI, exactly:
  ```
  http://localhost:8000/api/auth/oauth/google/callback
  ```
- [ ] Fill `.env`: `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`.
- Verify: click Continue with Google → authorize → signed in.

Apple — skip for now (button hidden). Needs a paid Apple Developer account ($99/yr) + an HTTPS domain (no localhost). See [oauth.md](./oauth.md) section 2. When ready:
- [ ] Fill the four `APPLE_*` (Services ID / Team ID / Key ID / .p8 key).
- [ ] Set `NEXT_PUBLIC_APPLE_OAUTH_ENABLED=true` to show the button.

Shared by both providers:
```dotenv
OAUTH_REDIRECT_BASE=http://localhost:8000   # backend origin; default is fine locally
FRONTEND_BASE_URL=http://localhost:3000     # frontend origin; used for post-login redirect + email links
```

### 4. Production checklist

- [ ] Switch `OAUTH_REDIRECT_BASE` / `FRONTEND_BASE_URL` to real HTTPS domains.
- [ ] Register a production redirect / return URL in the Google / Apple console.
- [ ] Move the Google consent screen from Testing to In production (review).
- [ ] `EMAIL_BACKEND=smtp` with SPF/DKIM ready.
- [ ] Strong random `SECRET_KEY`.
- [ ] (Optional) backfill `username` for old users.

### `.env` to fill (minimum local set)

```dotenv
# Required (local)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
OAUTH_REDIRECT_BASE=http://localhost:8000
FRONTEND_BASE_URL=http://localhost:3000
EMAIL_BACKEND=console          # console = read the link from the log locally

# Fill at production time
# SECRET_KEY=
# EMAIL_BACKEND=smtp + SMTP_* + EMAIL_FROM
# APPLE_CLIENT_ID / APPLE_TEAM_ID / APPLE_KEY_ID / APPLE_PRIVATE_KEY + NEXT_PUBLIC_APPLE_OAUTH_ENABLED=true
```

> All fields are also in `.env.example` (with comments). No code changes are needed on your side.

---

## 中文

> 代码已全部写好(登录、注册、邮箱/用户名登录、邮件验证+重置、Google/Apple OAuth)。
> 这份文档只列 **「只有你能做」** 的部分:跑命令 + 去服务商拿凭据 + 填 `.env`。
> Google/Apple 的逐步注册细节见 **[oauth.md](./oauth.md)**;本文是总的「做什么、按什么顺序」。

### 最小可跑通(只做这两步)

```bash
# 1) 应用数据库 schema(新增了 users.username 列,幂等,可重复跑)
make db-init
```
```dotenv
# 2) .env 里填 Google 两个变量(Google 登录就通了;支持 localhost)
GOOGLE_CLIENT_ID=xxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-xxxx
```
做完这两步:**邮箱密码登录 + 用户名登录 + Google 登录 + 邮件验证(console 模式)** 全部可用。
其余(Apple、真实发邮件、强 SECRET_KEY)都是上线阶段的事。

### 1. 登录 + 数据库

- [ ] `make db-init` —— 给 `users` 表加 `username` 列(幂等)。
  - 已存在的老账号 `username` 为空:仍可用**邮箱**登录,个人页回退显示邮箱前缀;新注册强制填用户名。
  - 需要给老账号补用户名?跟我说,给你写个 backfill 脚本。
- [ ](上线才需要)设强随机 `SECRET_KEY`(JWT 签名靠它,不设则每次重启所有登录失效):
  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(64))"
  ```
  ```dotenv
  SECRET_KEY=<上面生成的串>
  ```

验证:起后端+前端 → 注册(需填用户名)→ 用**邮箱或用户名**都能登录 → 个人页/导航显示用户名。

### 2. 邮件(注册验证 + 密码重置)

- 现在就是 **console 模式**:不发真邮件,把链接打到**后端日志**。本地测**啥都不用做**——注册后去日志复制验证链接打开即可。
- [ ](上线)真的发邮件:选一个 SMTP 服务填进 `.env`:
  ```dotenv
  EMAIL_BACKEND=smtp
  EMAIL_FROM=PenguinAI <no-reply@yourdomain.com>
  SMTP_HOST=smtp.yourprovider.com    # Gmail / SendGrid / AWS SES / Resend 均可
  SMTP_PORT=587
  SMTP_USER=...
  SMTP_PASSWORD=...                   # Gmail 用「应用专用密码」,不是登录密码
  SMTP_STARTTLS=true                  # 587 用这个;若用 465 则 false + SMTP_SSL=true
  SMTP_SSL=false
  ```
- [ ](上线)给发件域名配 SPF / DKIM,降低进垃圾箱概率。

### 3. OAuth

Google —— 现在就能通(支持 localhost)。详细步骤见 [oauth.md](./oauth.md) 第 1 节。要点:
- [ ] Google Cloud Console → **OAuth consent screen**(External,把自己邮箱加进 Test users)。
- [ ] **Credentials → OAuth client ID → Web**,Authorized redirect URI 一字不差:
  ```
  http://localhost:8000/api/auth/oauth/google/callback
  ```
- [ ] 填 `.env`:`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`。
- 验证:登录页点 **Continue with Google** → 授权 → 自动登录跳回。

Apple —— 暂时不用管(按钮已隐藏)。需要付费 Apple Developer($99/年)+ HTTPS 域名(不收 localhost)。详见 [oauth.md](./oauth.md) 第 2 节。准备好后:
- [ ] 填 4 个 `APPLE_*`(Services ID / Team ID / Key ID / .p8 私钥)。
- [ ] 设 `NEXT_PUBLIC_APPLE_OAUTH_ENABLED=true` 让按钮显示。

两个 provider 共用:
```dotenv
OAUTH_REDIRECT_BASE=http://localhost:8000   # 后端公网地址,本地用默认
FRONTEND_BASE_URL=http://localhost:3000     # 前端地址,登录后跳回+邮件链接都用它
```

### 4. 上线前 checklist

- [ ] `OAUTH_REDIRECT_BASE` / `FRONTEND_BASE_URL` 换成真实 HTTPS 域名。
- [ ] Google / Apple 后台再登记一条**生产环境**的 redirect / return URL。
- [ ] Google consent screen 从 Testing 切到 **In production**(走审核)。
- [ ] `EMAIL_BACKEND=smtp` + 发件域名 SPF/DKIM 就绪。
- [ ] `SECRET_KEY` 用强随机值。
- [ ](可选)给老用户 backfill `username`。

### 需要填的 `.env` 一览(本地最小集)

```dotenv
# 必填(本地)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
OAUTH_REDIRECT_BASE=http://localhost:8000
FRONTEND_BASE_URL=http://localhost:3000
EMAIL_BACKEND=console          # 本地用 console 看日志即可

# 上线再填
# SECRET_KEY=
# EMAIL_BACKEND=smtp + SMTP_* + EMAIL_FROM
# APPLE_CLIENT_ID / APPLE_TEAM_ID / APPLE_KEY_ID / APPLE_PRIVATE_KEY + NEXT_PUBLIC_APPLE_OAUTH_ENABLED=true
```

> 所有字段在 `.env.example` 里也有(带注释)。代码层面无需任何改动。
