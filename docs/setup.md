# Setup (Lenovo IdeaPad Slim 3, 16GB RAM, CPU only)

## Prerequisites
| Tool | Version / note |
|---|---|
| Python | 3.11 or newer |
| Node.js | 20 or newer |
| Docker Desktop | Running (uses WSL2 on Windows) |
| Git | Any recent |
| Redis | Via Docker |
| Ollama | Latest; runs on the host |
| Supabase | Free-tier project, or local Postgres 15+ in Docker |

## Memory budget (rough, to be measured)
| Item | RAM |
|---|---|
| Ollama + about 3B model (4-bit) | about 2.5 to 3 GB (about 7B needs 5 to 6 GB) |
| Docker / WSL2 | about 2 GB |
| Sandbox app + Postgres | about 1 GB |
| Chromium (Playwright) | about 0.5 GB |
| FastAPI, worker, Redis | about 0.7 GB |
| OS, browser, editor | about 4 GB |

Rules: one worker, one sandbox, default to the small model, close heavy apps while testing, and cap WSL2.

`%UserProfile%\.wslconfig`:
```
[wsl2]
memory=4GB
processors=4
```

## Suggested repo layout
```
/
  backend/        FastAPI app, workers, parsers, test templates
  agents/         agent runtime, tool registry, model adapters, memory
  frontend/       React + Vite dashboard
  sandbox/        Dockerfiles and runner scripts
  golden/         Evaluation apps with seeded regressions
  recordings/     Recorded model replies for tests
  docs/           The 15 project files, plus tracker.md and decisions.md
  docker-compose.yml
  .env.example
```

## Steps
1. **Clone the repo.**
2. **Backend and agents**
   ```
   cd backend
   python -m venv .venv
   .venv\Scripts\activate        (Windows)  /  source .venv/bin/activate  (Linux, macOS)
   pip install -r requirements.txt
   pip install semgrep
   playwright install chromium
   ```
3. **Frontend**
   ```
   cd frontend
   npm install
   ```
4. **Services:** `docker compose up -d redis` (and `db` if using local Postgres).
5. **Model:** install Ollama, then pull a small coder model. Pick a current tag from the Ollama library, for example:
   ```
   ollama pull qwen2.5-coder:3b
   ```
   Try a larger one (about 7B) later only for fix tasks.
6. **Environment:** copy `.env.example` to `.env` and fill the values below.
7. **Database:** run migrations (schema in database.md).
8. **Run**
   ```
   uvicorn app.main:app --reload     # terminal 1
   rq worker                         # terminal 2
   npm run dev                       # terminal 3 (frontend)
   ```
9. **Check:** `GET /api/v1/health` returns OK; the dashboard loads.

## Environment variables
| Variable | Purpose |
|---|---|
| DATABASE_URL | Platform database |
| SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_JWT_SECRET | Platform auth |
| REDIS_URL | Job queue |
| MODEL_ADAPTER | `ollama` (default), `hosted` or `replay` |
| OLLAMA_URL, OLLAMA_MODEL | Local model address and name |
| HOSTED_API_KEY, HOSTED_MODEL | Optional hosted adapter |
| MODEL_RUN_BUDGET | Max model calls or cost per run |
| AGENT_MAX_STEPS, AGENT_TIMEOUT_SECONDS | Agent limits |
| GITHUB_APP_ID, GITHUB_PRIVATE_KEY or GITHUB_TOKEN | GitHub access |
| GITHUB_WEBHOOK_SECRET | Verify webhooks |
| SANDBOX_TIMEOUT_SECONDS, SANDBOX_MEMORY_MB, SANDBOX_CPUS | Sandbox limits |

Never commit `.env`.

## Verify the setup
1. Health endpoint works.
2. A worker picks up a test job.
3. Sandbox starts and destroys a container.
4. The Notes app from `golden/` builds in the sandbox.
5. `ollama run` answers a short prompt, and the adapter returns valid JSON.

## First task
plan.md: **Stage 0**, then **Stage 1** (prove the idea with the Notes app). Track progress in `tracker.md`.
