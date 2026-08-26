# STAYKARO AI CALLER

Multi-tenant AI voice calling platform — production-grade system designed for 24/7 operation.

## Architecture

```
Caller
  ↓
Exotel / Twilio
  ↓
Voice Gateway (Pipecat)
  ↓
Deepgram STT → Tenant-safe RAG → Groq LLM → OpenAI Fallback → Streaming TTS
  ↓
Caller
```

### Backend Stack

| Component       | Technology     |
|-----------------|----------------|
| API Framework   | FastAPI        |
| Database        | PostgreSQL + pgvector |
| Cache/State     | Redis          |
| Voice Pipeline  | Pipecat        |
| LLM            | Groq (OpenAI fallback) |
| STT            | Deepgram       |
| Containerization| Docker Compose |
| Reverse Proxy   | Nginx          |
| CI/CD          | GitHub Actions |

### Frontend

- Admin Dashboard (Next.js)
- Client Dashboard (Next.js)

## Repository Structure

```
staykaro-ai-caller/
├── apps/                          # Frontend applications
│   ├── admin-dashboard/
│   └── client-dashboard/
├── services/                      # Backend services
│   ├── api/                       # FastAPI (Nishkala)
│   ├── voice-gateway/             # Pipecat (Shivashree)
│   ├── worker/                    # Async jobs (Nishkala)
│   └── integration-service/       # Automations (Nihal)
├── packages/                      # Shared libraries
│   ├── database/
│   ├── auth/
│   ├── tenant/
│   ├── providers/
│   ├── billing/
│   └── observability/
├── infrastructure/                # Deployment & ops
│   ├── docker/
│   ├── nginx/
│   └── monitoring/
├── .github/workflows/             # CI/CD pipelines
├── docker-compose.yml             # Container orchestration
├── .env.example                   # Environment template
└── README.md
```

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) (24+)
- [Docker Compose](https://docs.docker.com/compose/install/) (v2+)
- Make a copy of `.env.example` → `.env` and fill in your values

## Quick Start

```bash
# 1. Clone and configure
git clone <repo-url>
cd staykaro-ai-caller
cp .env.example .env
# Edit .env with your API keys

# 2. Start infrastructure services (PostgreSQL + Redis)
docker compose up -d postgres redis

# 3. Verify they're healthy
docker compose ps

# 4. See logs
docker compose logs -f postgres redis

# 5. Stop everything
docker compose down

# 6. Stop and remove volumes (WARNING: destroys data)
docker compose down -v
```

## Docker Commands Reference

### Service Management

```bash
# Start all available services (app services require Dockerfiles first)
docker compose --profile all up -d

# Start only infrastructure (database + cache)
docker compose up -d postgres redis

# Start a specific service
docker compose up -d <service-name>

# Stop all services (preserves volumes)
docker compose down

# Stop and remove all volumes (destroys persistent data)
docker compose down -v

# Restart a service
docker compose restart <service-name>
```

### Monitoring & Debugging

```bash
# List running services
docker compose ps

# View logs (tail)
docker compose logs -f <service-name>

# View logs (last 100 lines)
docker compose logs --tail=100 <service-name>

# Execute a command inside a running container
docker compose exec <service-name> <command>

# Example: connect to PostgreSQL
docker compose exec postgres psql -U staykaro_user -d staykaro

# Example: connect to Redis
docker compose exec redis redis-cli

# Check resource usage
docker stats
```

### Health Checks

```bash
# Check all service health statuses
docker compose ps

# Query PostgreSQL health directly
docker compose exec postgres pg_isready -U staykaro_user

# Ping Redis
docker compose exec redis redis-cli ping
```

### Cleanup

```bash
# Full cleanup (containers, networks, volumes, images)
docker compose down -v --rmi local

# Prune unused Docker resources
docker system prune
```

## Environment Variables

See `.env.example` for the full list of required variables.

**Critical variables you must set before running:**
- `POSTGRES_PASSWORD` — change from default
- `APP_DB_PASSWORD` — password for the restricted `staykaro_app` role the API
  actually serves traffic as. **Must differ from `POSTGRES_PASSWORD`** —
  `staykaro_user` is a Postgres superuser (an unavoidable side effect of how
  `POSTGRES_USER` bootstraps) and always bypasses Row-Level Security, so NK-07
  tenant isolation provides no real protection unless the API runs as
  `staykaro_app` instead. See `services/api/alembic/versions/df467b3bdd3f_*.py`.
- `DEEPGRAM_API_KEY` — for speech-to-text
- `GROQ_API_KEY` — for LLM
- `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` — for telephony

## Team

| Role | Engineer | Focus |
|------|----------|-------|
| Voice & AI | Shivashree | Voice Gateway, Pipecat, STT/TTS |
| Backend & Data | Nishkala | FastAPI, PostgreSQL, Redis, RAG |
| Frontend & DevOps | Nihal | Docker, Nginx, CI/CD, Dashboards |

## Phase 0 — Engineering Foundation

| Ticket | Owner | Description | Status |
|--------|-------|-------------|--------|
| NH-01 | Nihal | Docker Compose skeleton | ✅ Complete |
| NH-02 | Nihal | Dockerfiles per service | ✅ Complete |
| NH-03 | Nihal | Nginx reverse proxy | ✅ Complete |
| NH-04 | Nihal | GitHub Actions CI/CD | ✅ Complete |
| NH-05 | Nihal | VPS deployment foundation | ✅ Complete |
| NK-01 | Nishkala | FastAPI skeleton/config | ✅ Complete |
| NK-02 | Nishkala | PostgreSQL schema/migrations | ✅ Complete — Alembic, not create_all |
| NK-03 | Nishkala | Redis call sessions | ✅ Complete |
| NK-04 | Nishkala | Health/readiness endpoints | ✅ Complete |
| SH-03 | Shivashree | Voice Gateway/Pipecat | ✅ Complete — empty-call lifecycle; STT/LLM/TTS (SH-04/06/08) not started |

CP1 (stack + health + empty call lifecycle) is met. Phase 4 (multi-tenancy) is
partially in place ahead of schedule: NK-05 (real DB-backed auth) and NK-07
(PostgreSQL Row-Level Security, `staykaro_app` role — see
`services/api/alembic/versions/df467b3bdd3f_*.py`) are done and tested
end-to-end; NK-06 (full RBAC) and NK-08 (formal pen-test suite beyond
`tests/test_tenant_isolation.py`) are still open.

## Security

- NEVER commit `.env` to version control
- NEVER hardcode passwords or API keys
- PostgreSQL exposed only on `127.0.0.1` (localhost-only)
- Redis exposed only on `127.0.0.1` (localhost-only)
- All secrets managed via environment variables
- Application secrets require explicit rotation before production
