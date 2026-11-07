# Decisions

Record every choice that changes the plan, with the date and the reason. Newest first within each section.

## Made
| Date | Decision | Reason |
|---|---|---|
| 2026-11-07 | Platform database: local Docker Postgres on port 5433 with Alembic migrations | Runs locally with zero cloud dependence or cost; mapped to port 5433 to prevent port collisions on systems with native Postgres on 5432; schema versioned with Alembic and SQLAlchemy 2.0 |
| 2026-11-06 | Sandbox runner hard limits & guarantees | Enforces 512MB memory limit, 60s configurable timeout with container kill, non-root user (node uid 1000), internal network isolation, and try/finally auto-destruction with zero leftover containers |
| 2026-11-06 | Validation template side-effect verdict model | Distinguishes safe input rejection (400/422/sanitized 201) as PASS, unhandled server crashes (500) as ERROR, and destructive state mutation as FAIL |
| 2026-11-06 | RLS template thin wrapper around ownership logic | Reuses proven differential target logic with unfiltered queries (GET /table_name) to verify auth.uid() row isolation across PostgREST tables |
| 2026-11-06 | Role template with admin confirmation pre-check | Executes an authorized admin request (expecting 200) before testing non-admin denial (expecting 403/404) to prevent false passes on broken or unexposed routes |
| 2026-11-06 | Unauthenticated template: PostgREST anonymous PASS condition | In sandbox setup (PGRST_DB_ANON_ROLE='anon'), unauthenticated requests execute under 'anon' role; RLS filtering returns HTTP 200 with empty list [], or 401/403 if ungranted |
| 2026-11-06 | Dual-target ownership template with differential verdict logic | Evaluates PASS/FAIL across both full REST backends (denial codes) and PostgREST gateways (empty RLS query returns) with ERROR safety on creation/connection faults |
| 2026-11-06 | http_request_as helper with structured evidence and strict token redaction | Uniform API for test templates across Node apps and PostgREST with identity normalization, error handling, and zero token leaks in evidence |
| 2026-11-06 | Schema-flexible SandboxUserSeeder module | Allows seeding User A, User B, Admin, Anonymous across arbitrary imported app schemas with automatic ephemeral cleanup |
| 2026-11-06 | PostgREST 12.2.0 + Postgres 15.8 with auth.uid() function for Supabase sandbox | Replicates Supabase RLS and JWT handling without the memory overhead of the full local Supabase stack |
| 2026-11-06 | Pinned node:20.18.0-alpine3.20 base image for sandbox Node apps | Minimal Alpine footprint, reproducible build, built-in non-root node user (uid 1000) |
| 2026-11-05 | Worktree-based test runner for version matrices | Avoids dirty in-place checkouts and preserves clean workspace state across tag evaluations |
| 2026-11-05 | Ollama qwen2.5-coder:3b measured: ~2.2s response time warm, ~137MB RAM idle working set | Validates local CPU execution speed on 16GB laptop |
| 2026-11-03 | Build our own agent runtime; no agent frameworks | Practical, and shows real skill |
| 2026-11-03 | Brain: open-weight model through Ollama behind a swappable adapter; hosted model optional, for development and comparison only | No per-call cost; fits the project goal |
| 2026-11-03 | Default model about 3B (4-bit); try about 7B for fixes only; vLLM skipped | 16GB laptop, CPU only |
| 2026-11-03 | First supported stack: React + Supabase | Typical Lovable output; keeps scope feasible |
| 2026-11-03 | Sandbox DB: plain Postgres + PostgREST with an `auth.uid()` helper, not the full local Supabase stack | RAM |
| 2026-11-03 | PASS/FAIL decided by tests only; test that cannot run is `ERROR`, never a regression | Repeatable and honest |
| 2026-11-03 | Strix is an optional scanner and a comparison baseline, not something we rebuild | Do not compete on pentesting |
| 2026-11-03 | Build order follows `plan.md` stages (core demo first, then agents) | Early proof of the main idea |

## Open
| Question | Needed by |
|---|---|
| Project name (Nigrani preferred; check PyPI, npm, GitHub, domain) | Stage 0 |
| Final list and wording of the 15 files | Stage 11 |
| Which apps are the evaluation (golden) apps | Stage 13 |
| Which model sizes the laptop really sustains | Stage 7 |
