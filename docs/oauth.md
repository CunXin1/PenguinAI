# OAuth & Email — Setup Guide

## English

> All the code is written (Google + Apple sign-in, email verification + password reset).
> This document lists only the parts **only you can do**: register with the providers and fill in `.env`.
> Once filled, the flow works end to end. `.env.example` has brief inline notes; this is the full version.

Code locations (no changes needed, for reference):
- Backend OAuth: `backend/app/core/oauth.py` + `backend/app/api/routes/auth.py`
- Backend email: `backend/app/core/email.py`
- Frontend button / callback: `frontend/src/app/auth/login/page.tsx` + `frontend/src/app/auth/callback/page.tsx`

### 0. Shared basics (both providers)

```dotenv
# Public origin of THIS backend — used to build the OAuth redirect_uri; must match the provider console exactly
OAUTH_REDIRECT_BASE=http://localhost:8000
# Frontend origin — where users land after sign-in; verification/reset email links also point here
FRONTEND_BASE_URL=http://localhost:3000
```

> The callback is always `{OAUTH_REDIRECT_BASE}/api/auth/oauth/{provider}/callback`.
> The defaults above are fine for local dev; for production use your real domains.

Database: the `users` table already has `oauth_provider` / `oauth_sub` columns — `make db-init` is enough.

### 1. Google sign-in (works on localhost, fastest)

What to register on Google:
1. Open <https://console.cloud.google.com> → pick or create a project.
2. APIs & Services → OAuth consent screen: User Type External → fill App name, support email, developer email → save. Keep Publishing status as Testing during dev, and add your own Google email under Test users (otherwise other accounts are blocked).
3. APIs & Services → Credentials → Create Credentials → OAuth client ID → Web application. Add Authorized redirect URI (exactly):
   ```
   http://localhost:8000/api/auth/oauth/google/callback
   ```
   (Add `https://<your-backend-domain>/api/auth/oauth/google/callback` for production.) Copy the Client ID and Client secret.

Fill `.env`:
```dotenv
GOOGLE_CLIENT_ID=xxxxxxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-xxxxxxxx
```

Verify: restart the backend → click Continue with Google on the login page → authorize → redirected to `/auth/callback` → signed in. (The endpoint returns 503 when no credentials are set — that is expected.)

- [ ] Create the OAuth consent screen + add a test user
- [ ] Create a Web OAuth client + register the redirect URI
- [ ] Put `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` in `.env`

### 2. Apple sign-in (needs a paid account; button currently hidden)

> Note: Apple requires the Apple Developer Program ($99/yr) and does NOT accept `http://localhost` —
> local testing needs an HTTPS domain or a tunnel (e.g. ngrok). You can skip this; Google is enough to launch.
> The frontend button stays hidden until the credentials are set.

What to register on Apple (developer.apple.com):
1. Certificates, Identifiers & Profiles → Identifiers → App ID: create an App ID with Sign In with Apple enabled.
2. Create a Services ID (its identifier, e.g. `com.penguinai.web`, is `APPLE_CLIENT_ID`): configure Sign In with Apple → Web Authentication:
   - Domain: your frontend/backend domain (no protocol)
   - Return URLs: `https://<your-backend-domain>/api/auth/oauth/apple/callback`
3. Keys → new Key with Sign In with Apple → download the `.p8` private key (one-time). Note the Key ID.
4. Your Team ID (10 chars) is shown top-right.

Fill `.env`:
```dotenv
APPLE_CLIENT_ID=com.penguinai.web      # the Services ID
APPLE_TEAM_ID=ABCDE12345               # 10-char Team ID
APPLE_KEY_ID=XYZ1234567                # Key ID of the .p8
# Paste the .p8 body as one line, with \n between the PEM lines:
APPLE_PRIVATE_KEY=-----BEGIN PRIVATE KEY-----\nMIG-...\n-----END PRIVATE KEY-----\n
# Show the Apple button (hidden by default):
NEXT_PUBLIC_APPLE_OAUTH_ENABLED=true
```

> You do not fill the client secret — the backend mints it at runtime from the `.p8` (ES256 JWT, see `core/oauth.py`).

- [ ] Paid Apple Developer Program
- [ ] App ID with Sign In with Apple enabled
- [ ] Services ID (= `APPLE_CLIENT_ID`) + Return URL (HTTPS)
- [ ] Sign-in Key (`.p8` + `APPLE_KEY_ID`), note `APPLE_TEAM_ID`
- [ ] Put the four `APPLE_*` in `.env`, set `NEXT_PUBLIC_APPLE_OAUTH_ENABLED=true`
- [ ] Use an HTTPS tunnel (ngrok) locally, and sync the tunnel domain to `OAUTH_REDIRECT_BASE` and the Apple Return URL

### 3. Email (registration verification + password reset)

The code is wired: register / resend-verification / forgot-password all send mail.
Default **console** mode does not send real mail — it logs the link to the backend log, so local testing needs no config.

To actually send (production):
```dotenv
EMAIL_BACKEND=smtp
EMAIL_FROM=PenguinAI <no-reply@yourdomain.com>
SMTP_HOST=smtp.yourprovider.com
SMTP_PORT=587
SMTP_USER=your_smtp_user
SMTP_PASSWORD=your_smtp_password
SMTP_STARTTLS=true        # for 587; for 465 set false and SMTP_SSL=true
SMTP_SSL=false
```
Common choices: Gmail (app password), SendGrid, AWS SES, Postmark, Resend (SMTP).

- [ ] Pick an SMTP service, get host/user/password
- [ ] Set `EMAIL_BACKEND=smtp` + the `SMTP_*` + `EMAIL_FROM`
- [ ] (Production) configure SPF / DKIM for the sending domain

### 4. Fastest local verification (no cost)

1. Keep `EMAIL_BACKEND=console` and fill the two Google vars.
2. `make db-init` (first time) → start backend + frontend.
3. Email path: register an account → open the verification link from the backend log → `/auth/verify-email` completes verification.
4. Google path: click Continue with Google → authorize → signed in automatically.

### 5. Production checklist

- [ ] Switch `OAUTH_REDIRECT_BASE` / `FRONTEND_BASE_URL` to real HTTPS domains
- [ ] Register a production redirect / return URL in the Google / Apple console
- [ ] Move the Google consent screen from Testing to In production (review)
- [ ] `EMAIL_BACKEND=smtp` with SPF/DKIM ready
- [ ] Strong random `SECRET_KEY` (JWTs depend on it)

---

## 中文

> 代码已全部写好(Google + Apple 登录、邮箱验证 / 密码重置邮件)。
> 这份文档列的是「只有你能做」的部分:去服务商注册拿凭据 + 填进 `.env`。
> 填完即可端到端跑通。`.env.example` 里有对应字段的简要注释,本文是完整版。

代码位置(无需改动,供参考):
- 后端 OAuth:`backend/app/core/oauth.py` + `backend/app/api/routes/auth.py`
- 后端邮件:`backend/app/core/email.py`
- 前端按钮 / 回调:`frontend/src/app/auth/login/page.tsx` + `frontend/src/app/auth/callback/page.tsx`

### 0. 共用基础(两个 provider 都要)

```dotenv
# 后端公网地址 —— 用来拼 OAuth 回调地址,必须和服务商后台登记的完全一致
OAUTH_REDIRECT_BASE=http://localhost:8000
# 前端地址 —— 登录成功后跳回这里,验证/重置邮件链接也指向这里
FRONTEND_BASE_URL=http://localhost:3000
```

> 回调地址固定按 `{OAUTH_REDIRECT_BASE}/api/auth/oauth/{provider}/callback` 生成。
> 本地开发就用上面的默认值;上线换成真实域名(如 `https://api.penguinai.com` / `https://penguinai.com`)。

数据库:`users` 表已含 `oauth_provider` / `oauth_sub` 列,`make db-init` 即可(无需额外操作)。

### 1. Google 登录(支持 localhost,最快)

你要去 Google 注册的东西:
1. 打开 <https://console.cloud.google.com> → 选/建一个项目。
2. 左侧 **APIs & Services → OAuth consent screen**:User Type 选 **External** → 填 App name、support email、developer email → 保存。开发阶段 Publishing status 保持 **Testing** 即可;在 **Test users** 里加上你自己的 Google 邮箱(否则别人登录会被拦)。
3. **APIs & Services → Credentials → Create Credentials → OAuth client ID** → 类型 **Web application**。Authorized redirect URI 添加(一字不差):
   ```
   http://localhost:8000/api/auth/oauth/google/callback
   ```
   (上线再加一条 `https://<你的后端域名>/api/auth/oauth/google/callback`。)创建后拿到 **Client ID** 和 **Client secret**。

填进 `.env`:
```dotenv
GOOGLE_CLIENT_ID=xxxxxxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-xxxxxxxx
```

验收:重启后端 → 登录页点 **Continue with Google** → 授权 → 跳回 `/auth/callback` → 自动登录。(没填凭据时该接口返回 503,属正常。)

- [ ] 建 OAuth consent screen + 加 test user
- [ ] 建 Web OAuth client + 登记 redirect URI
- [ ] `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` 写进 `.env`

### 2. Apple 登录(需付费账号,前端按钮当前已隐藏)

> 注意:Apple 必须有 **Apple Developer Program($99/年)**,且 **不接受 `http://localhost`**——
> 本地测试要用 HTTPS 域名或 ngrok 之类隧道。没账号可以先跳过,Google 足够上线。
> 前端按钮已用开关隐藏,凭据齐了再打开。

你要去 Apple 注册的东西(developer.apple.com):
1. **Certificates, Identifiers & Profiles → Identifiers → App ID**:建一个 App ID,勾选 **Sign In with Apple**。
2. 再建一个 **Services ID**(类型选 Services IDs),它的 identifier(如 `com.penguinai.web`)就是 `APPLE_CLIENT_ID`:配置 Sign In with Apple → Web Authentication:
   - Domain:你的前端/后端域名(不含协议)
   - **Return URLs** 添加:`https://<你的后端域名>/api/auth/oauth/apple/callback`
3. **Keys → 新建 Key**,勾选 Sign In with Apple → 下载 `.p8` 私钥(只能下一次)。记下 **Key ID**。
4. 右上角能看到你的 **Team ID**(10 位)。

填进 `.env`:
```dotenv
APPLE_CLIENT_ID=com.penguinai.web      # 上面的 Services ID
APPLE_TEAM_ID=ABCDE12345               # 10 位 Team ID
APPLE_KEY_ID=XYZ1234567                # .p8 对应的 Key ID
# .p8 文件内容贴成一行,换行用 \n 代替:
APPLE_PRIVATE_KEY=-----BEGIN PRIVATE KEY-----\nMIG-...\n-----END PRIVATE KEY-----\n
# 前端显示 Apple 按钮的开关(默认 false 隐藏):
NEXT_PUBLIC_APPLE_OAUTH_ENABLED=true
```

> client secret 不用手填——后端用 `.p8` 在运行时自动签发(ES256 JWT,见 `core/oauth.py`)。

- [ ] 付费 Apple Developer Program
- [ ] App ID 开启 Sign In with Apple
- [ ] Services ID(= `APPLE_CLIENT_ID`)+ 配 Return URL(HTTPS)
- [ ] Sign-in Key(`.p8` + `APPLE_KEY_ID`),记下 `APPLE_TEAM_ID`
- [ ] 4 个 `APPLE_*` 写进 `.env`,把 `NEXT_PUBLIC_APPLE_OAUTH_ENABLED=true`
- [ ] 本地用 HTTPS 隧道(ngrok),并把隧道域名同步到 `OAUTH_REDIRECT_BASE` 和 Apple Return URL

### 3. 邮件(注册验证 + 密码重置)

代码已接好:`register` / `resend-verification` / `forgot-password` 都会发邮件。
**默认 `console` 模式**——不发真邮件,把链接打到后端日志,本地无需任何配置即可测。

真发邮件(上线):
```dotenv
EMAIL_BACKEND=smtp
EMAIL_FROM=PenguinAI <no-reply@yourdomain.com>
SMTP_HOST=smtp.yourprovider.com
SMTP_PORT=587
SMTP_USER=your_smtp_user
SMTP_PASSWORD=your_smtp_password
SMTP_STARTTLS=true        # 587 用 STARTTLS;若用 465 则设 false 且 SMTP_SSL=true
SMTP_SSL=false
```
常见选择:Gmail(应用专用密码)、SendGrid、AWS SES、Postmark、Resend(SMTP)。

- [ ] 选一个 SMTP 服务,拿到主机/账号/密码
- [ ] 设 `EMAIL_BACKEND=smtp` + 填 `SMTP_*` + `EMAIL_FROM`
- [ ] (上线)发件域名配好 SPF / DKIM,降低进垃圾箱概率

### 4. 本地最快验证(不花一分钱)

1. `.env` 保持 `EMAIL_BACKEND=console`,填好 Google 两个变量。
2. `make db-init`(首次)→ 起后端 + 前端。
3. **邮件链路**:注册一个账号 → 看后端日志里的验证链接 → 浏览器打开 → 跳 `/auth/verify-email` 完成验证。
4. **Google 链路**:登录页点 Continue with Google → 授权 → 自动登录跳回。

### 5. 上线 checklist

- [ ] `OAUTH_REDIRECT_BASE` / `FRONTEND_BASE_URL` 换成真实 HTTPS 域名
- [ ] Google / Apple 后台再登记一条生产环境的 redirect / return URL
- [ ] Google consent screen 从 Testing 切到 **In production**(走 Google 审核)
- [ ] `EMAIL_BACKEND=smtp` 且发件域名 SPF/DKIM 就绪
- [ ] `SECRET_KEY` 用强随机值(签发的 JWT 依赖它)
