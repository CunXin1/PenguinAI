# 上线/联调前 — 你需要做的事(操作清单)

> 代码已全部写好(登录、注册、邮箱/用户名登录、邮件验证+重置、Google/Apple OAuth)。
> 这份文档只列 **「只有你能做」** 的部分:跑命令 + 去服务商拿凭据 + 填 `.env`。
> Google/Apple 的逐步注册细节见 **[oauth.md](./oauth.md)**;本文是总的「做什么、按什么顺序」。

---

## 最小可跑通(只做这两步)

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

---

## 1. 登录 + 数据库

- [ ] `make db-init` —— 给 `users` 表加 `username` 列(幂等)。
  - 已存在的老账号 `username` 为空:仍可用**邮箱**登录,个人页回退显示邮箱前缀;新注册强制填用户名。
  - 需要给老账号补用户名?跟我说,给你写个 backfill 脚本。
- [ ]（上线才需要）设强随机 `SECRET_KEY`(JWT 签名靠它,不设则每次重启所有登录失效):
  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(64))"
  ```
  ```dotenv
  SECRET_KEY=<上面生成的串>
  ```

**验证**:起后端+前端 → 注册(需填用户名)→ 用**邮箱或用户名**都能登录 → 个人页/导航显示用户名。

---

## 2. 邮件(注册验证 + 密码重置)

- 现在就是 **console 模式**:不发真邮件,把链接打到**后端日志**。本地测**啥都不用做**——注册后去日志复制验证链接打开即可。
- [ ]（上线)真的发邮件:选一个 SMTP 服务填进 `.env`:
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
- [ ]（上线)给发件域名配 SPF / DKIM,降低进垃圾箱概率。

---

## 3. OAuth

### Google —— 现在就能通(支持 localhost)
详细步骤见 [oauth.md §1](./oauth.md)。要点:
- [ ] Google Cloud Console → **OAuth consent screen**(External,把自己邮箱加进 Test users)。
- [ ] **Credentials → OAuth client ID → Web**,Authorized redirect URI 一字不差:
  ```
  http://localhost:8000/api/auth/oauth/google/callback
  ```
- [ ] 填 `.env`:`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`。
- 验证:登录页点 **Continue with Google** → 授权 → 自动登录跳回。

### Apple —— 暂时不用管(按钮已隐藏)
需要付费 Apple Developer($99/年)+ HTTPS 域名(不收 localhost)。详见 [oauth.md §2](./oauth.md)。准备好后:
- [ ] 填 4 个 `APPLE_*`(Services ID / Team ID / Key ID / .p8 私钥)。
- [ ] 设 `NEXT_PUBLIC_APPLE_OAUTH_ENABLED=true` 让按钮显示。

### 两个 provider 共用
```dotenv
OAUTH_REDIRECT_BASE=http://localhost:8000   # 后端公网地址,本地用默认
FRONTEND_BASE_URL=http://localhost:3000     # 前端地址,登录后跳回+邮件链接都用它
```

---

## 4. 上线前 checklist

- [ ] `OAUTH_REDIRECT_BASE` / `FRONTEND_BASE_URL` 换成真实 HTTPS 域名。
- [ ] Google / Apple 后台再登记一条**生产环境**的 redirect / return URL。
- [ ] Google consent screen 从 Testing 切到 **In production**(走审核)。
- [ ] `EMAIL_BACKEND=smtp` + 发件域名 SPF/DKIM 就绪。
- [ ] `SECRET_KEY` 用强随机值。
- [ ]（可选)给老用户 backfill `username`。

---

## 需要填的 `.env` 一览(本地最小集)

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
