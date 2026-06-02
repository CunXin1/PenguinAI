# Deployment Guide

## English

### Local Development (Docker Compose)

#### Prerequisites
- Docker Desktop with NVIDIA Container Toolkit (for GPU worker)
- NVIDIA driver ≥ 525 + CUDA 12.4
- 32 GB RAM recommended (TimescaleDB + ML models)
- RTX 4090 (or any CUDA GPU with ≥ 16 GB VRAM)

#### First-Time Setup

```bash
# 1. Clone repo and enter directory
cd penguinai

# 2. Configure environment
cp .env.example .env
# Edit .env: set DB_PASSWORD, SECRET_KEY, POLYGON_API_KEY, etc.

# 3. Start all services (first run takes a few minutes to pull images)
docker-compose up -d

# 4. Wait for TimescaleDB to initialize (~30 seconds)
docker-compose logs timescaledb | grep "database system is ready"

# 5. Bootstrap ticker universe
python scripts/bootstrap_universe.py

# 6. (Optional) Import your historical 30-min data
# (import script will be written based on your data format)

# 7. Open app
open http://localhost        # Frontend
open http://localhost:8000/docs  # API docs (DEBUG=true required)
```

#### Service Ports

| Service | Port | Description |
|---------|------|-------------|
| nginx | 80 | Main entry point |
| frontend | 3000 | Next.js (internal) |
| api | 8000 | FastAPI (internal) |
| timescaledb | 5432 | PostgreSQL (external) |
| redis | 6379 | Redis (external) |

#### Useful Commands

```bash
make up           # Start all services
make down         # Stop all services
make logs         # Follow all service logs
make backend      # Run FastAPI without Docker (hot reload)
make frontend     # Run Next.js without Docker (hot reload)
make ml-worker    # Run Celery ML worker (requires GPU on host)
make test         # Run test suite
make lint         # Lint backend + frontend
make flower       # Celery monitoring UI at :5555
```

#### Developing Without GPU

If you don't have a GPU locally, you can stub out ML inference for development:

1. Set `GEMMA_API_URL` in `.env` to an external API endpoint
2. Comment out `ml_worker` in `docker-compose.yml`
3. Pre-populate `signal_cache` with test data via SQL

---

### Production Deployment (AWS)

#### Infrastructure Overview

```
Route 53 (DNS)
    │
    ▼
CloudFront (CDN + HTTPS termination)
    │
    ├─── Application Load Balancer
    │         │
    │    ECS Cluster (penguinai-prod)
    │         ├── penguinai-api (Fargate, 2+ tasks)
    │         ├── penguinai-frontend (Fargate, 2+ tasks)
    │         ├── penguinai-ml-worker (EC2 G5 instance with A10G GPU)
    │         ├── penguinai-celery-beat (Fargate, 1 task)
    │         └── penguinai-scraper (Fargate, 1 task)
    │
    ├─── Amazon RDS (TimescaleDB on self-managed EC2 or RDS for PostgreSQL)
    ├─── ElastiCache Redis
    └─── ECR (Docker image registry)
```

#### ECR Repositories

Create these repositories before first deploy:
```bash
aws ecr create-repository --repository-name penguinai-backend
aws ecr create-repository --repository-name penguinai-frontend
aws ecr create-repository --repository-name penguinai-ml
```

#### Required GitHub Secrets

Set these in GitHub Settings → Secrets → Actions:

| Secret | Description |
|--------|-------------|
| `AWS_ACCESS_KEY_ID` | IAM user with ECR + ECS permissions |
| `AWS_SECRET_ACCESS_KEY` | Corresponding secret |
| `AWS_ACCOUNT_ID` | Your 12-digit AWS account ID |
| `NEXT_PUBLIC_API_URL` | Production API URL (e.g. `https://api.penguinai.com/api`) |

#### ECS Task Definition Essentials

For `penguinai-ml-worker` (GPU task):
```json
{
  "requiresCompatibilities": ["EC2"],
  "placementConstraints": [
    { "type": "memberOf", "expression": "attribute:ecs.instance-type =~ g5.*" }
  ],
  "resourceRequirements": [
    { "type": "GPU", "value": "1" }
  ]
}
```

#### Deployment Process

CD pipeline (`cd-aws.yml`) runs automatically on push to `main`:

1. Build Docker images for backend, frontend, ML worker
2. Push to ECR with commit SHA tag
3. Update ECS services with `--force-new-deployment`
4. Wait for services to stabilize

**Manual trigger** (emergency deploy or rollback):
```bash
# Trigger deploy via GitHub Actions
gh workflow run "CD — Deploy to AWS"

# Or rollback to previous image
aws ecs update-service \
  --cluster penguinai-prod \
  --service penguinai-api \
  --task-definition penguinai-api:PREVIOUS_VERSION
```

#### Environment Variables (Production)

Set as ECS Task secrets (pulled from AWS Secrets Manager or Parameter Store):

```bash
# Store secrets in SSM Parameter Store
aws ssm put-parameter --name "/penguinai/prod/SECRET_KEY" --value "..." --type SecureString
aws ssm put-parameter --name "/penguinai/prod/DATABASE_URL" --value "..." --type SecureString
aws ssm put-parameter --name "/penguinai/prod/POLYGON_API_KEY" --value "..." --type SecureString
```

#### GPU Instance Recommendation

| Instance | GPU | VRAM | Use case |
|----------|-----|------|---------|
| `g5.xlarge` | A10G 24GB | 24 GB | Recommended for Gemma 4 |
| `g4dn.xlarge` | T4 16GB | 16 GB | Budget option (slower inference) |
| `p3.2xlarge` | V100 16GB | 16 GB | Good alternative |

#### Health Checks

```bash
# API health
curl https://api.penguinai.com/health

# Check ECS service status
aws ecs describe-services \
  --cluster penguinai-prod \
  --services penguinai-api penguinai-ml-worker

# Check Celery workers
docker-compose exec celery_worker celery -A ml.tasks.celery_app inspect active
```

---

## 中文

### 本地开发环境

#### 首次启动步骤

```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env：设置 DB_PASSWORD、SECRET_KEY、API Key 等

# 2. 启动所有服务
docker-compose up -d

# 3. 等待 TimescaleDB 就绪（约 30 秒）
docker-compose logs timescaledb | grep "database system is ready"

# 4. 初始化股票池
python scripts/bootstrap_universe.py

# 5. 访问应用
# 前端：http://localhost
# API 文档：http://localhost:8000/docs（需设置 DEBUG=true）
```

#### 不同场景的启动方式

| 场景 | 命令 |
|------|------|
| 完整开发环境 | `make up` |
| 只跑后端（热重载） | `make backend` |
| 只跑前端（热重载） | `make frontend` |
| ML Worker（需要 GPU） | `make ml-worker` |
| 查看所有日志 | `make logs` |
| Celery 监控面板 | `make flower`（访问 :5555） |

### AWS 生产部署

CD pipeline（`cd-aws.yml`）在 push 到 `main` 分支时自动触发：
1. 构建三个 Docker 镜像（backend、frontend、ml）
2. 推送到 ECR（带 commit SHA 标签）
3. 更新 ECS 服务（`--force-new-deployment`）
4. 等待所有服务稳定

#### GPU 实例推荐

生产环境 Gemma 4 推理推荐 `g5.xlarge`（A10G 24GB VRAM）。预算有限可使用 `g4dn.xlarge`（T4 16GB），速度会慢约 2-3 倍。
