# OAuth & 邮件 — 上线前 TODO 清单

> 代码已全部写好(Google + Apple 登录、邮箱验证 / 密码重置邮件)。
> **这份文档列的是「只有你能做」的部分**:去服务商注册拿凭据 + 填进 `.env`。
> 填完即可端到端跑通。`.env.example` 里有对应字段的简要注释,本文是完整版。

代码位置(无需改动,供参考):
- 后端 OAuth:`backend/app/core/oauth.py` + `backend/app/api/routes/auth.py`
- 后端邮件:`backend/app/core/email.py`
- 前端按钮 / 回调:`frontend/src/app/auth/login/page.tsx` + `frontend/src/app/auth/callback/page.tsx`

---

## 0. 共用基础(两个 provider 都要)

```dotenv
# 后端公网地址 —— 用来拼 OAuth 回调地址,必须和服务商后台登记的完全一致
OAUTH_REDIRECT_BASE=http://localhost:8000
# 前端地址 —— 登录成功后跳回这里,验证/重置邮件链接也指向这里
FRONTEND_BASE_URL=http://localhost:3000
```

> 回调地址固定按 `{OAUTH_REDIRECT_BASE}/api/auth/oauth/{provider}/callback` 生成。
> 本地开发就用上面的默认值;上线换成真实域名(如 `https://api.penguinai.com` / `https://penguinai.com`)。

数据库:`users` 表已含 `oauth_provider` / `oauth_sub` 列,`make db-init` 即可(无需额外操作)。

---

## 1. Google 登录(支持 localhost,最快)

### 你要去 Google 注册的东西
1. 打开 <https://console.cloud.google.com> → 选/建一个项目。
2. 左侧 **APIs & Services → OAuth consent screen**:
   - User Type 选 **External** → 填 App name、support email、developer email → 保存。
   - 开发阶段 Publishing status 保持 **Testing** 即可;在 **Test users** 里加上你自己的 Google 邮箱(否则别人登录会被拦)。
3. **APIs & Services → Credentials → Create Credentials → OAuth client ID**:
   - Application type:**Web application**
   - **Authorized redirect URIs** 添加(一字不差):
     ```
     http://localhost:8000/api/auth/oauth/google/callback
     ```
     （上线再加一条 `https://<你的后端域名>/api/auth/oauth/google/callback`）
   - 创建后拿到 **Client ID** 和 **Client secret**。

### 填进 `.env`
```dotenv
GOOGLE_CLIENT_ID=xxxxxxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-xxxxxxxx
```

### 验收
重启后端 → 登录页点 **Continue with Google** → Google 授权 → 跳回 `/auth/callback` → 自动登录。
（没填凭据时该接口返回 503,属正常。）

- [ ] 建 OAuth consent screen + 加 test user
- [ ] 建 Web OAuth client + 登记 redirect URI
- [ ] `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` 写进 `.env`

---

## 2. Apple 登录(需付费账号,前端按钮当前已隐藏)

> ⚠️ Apple 必须有 **Apple Developer Program($99/年)**,且 **不接受 `http://localhost`**——
> 本地测试要用 HTTPS 域名或 ngrok 之类隧道。没账号可以先跳过,Google 足够上线。
> 前端按钮已用开关隐藏,凭据齐了再打开。

### 你要去 Apple 注册的东西(developer.apple.com)
1. **Certificates, Identifiers & Profiles → Identifiers → App ID**:建一个 App ID,勾选 **Sign In with Apple**。
2. 再建一个 **Services ID**(类型选 Services IDs),它的 identifier(如 `com.penguinai.web`)就是 `APPLE_CLIENT_ID`:
   - 配置 Sign In with Apple → Web Authentication:
     - Domain:你的前端/后端域名(不含协议)
     - **Return URLs** 添加:`https://<你的后端域名>/api/auth/oauth/apple/callback`
3. **Keys → 新建 Key**,勾选 Sign In with Apple → 下载 `.p8` 私钥(只能下一次)。记下 **Key ID**。
4. 右上角能看到你的 **Team ID**(10 位)。

### 填进 `.env`
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

---

## 3. 邮件(注册验证 + 密码重置)

代码已接好:`register` / `resend-verification` / `forgot-password` 都会发邮件。
**默认 `console` 模式**——不发真邮件,把链接打到后端日志,本地无需任何配置即可测。

### 真发邮件(上线)
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

---

## 4. 本地最快验证(不花一分钱)

1. `.env` 保持 `EMAIL_BACKEND=console`,填好 Google 两个变量。
2. `make db-init`(首次)→ 起后端 + 前端。
3. **邮件链路**:注册一个账号 → 看后端日志里的验证链接 → 浏览器打开 → 跳 `/auth/verify-email` 完成验证。
4. **Google 链路**:登录页点 Continue with Google → 授权 → 自动登录跳回。

---

## 5. 上线 checklist

- [ ] `OAUTH_REDIRECT_BASE` / `FRONTEND_BASE_URL` 换成真实 HTTPS 域名
- [ ] Google / Apple 后台再登记一条生产环境的 redirect / return URL
- [ ] Google consent screen 从 Testing 切到 **In production**(走 Google 审核)
- [ ] `EMAIL_BACKEND=smtp` 且发件域名 SPF/DKIM 就绪
- [ ] `SECRET_KEY` 用强随机值(签发的 JWT 依赖它)
