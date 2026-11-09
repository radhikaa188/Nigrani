# Tracker

**How to use:** tick boxes as you finish tasks. Update the status table at the end of every work session. If something breaks, add a row to the Issues log before you try to fix it. Changed your mind about something? Write it in `decisions.md`.

**Status values:** Not started | In progress | Done | Blocked

**Git rule:** one branch per stage (`stage-N-name`). Merge to `main` only when "Done when" passes, then tag `stage-N-done`.

## Progress overview
| # | Stage | Status | Branch / tag | Started | Finished | Notes |
|---|---|---|---|---|---|---|
| 0 | Setup and tracking | Done | main | 2026-11-05 | 2026-11-05 | Setup verified |
| 1 | Prove the idea (CLI only) | Done | stage-1-slice / stage-1-done | 2026-11-05 | 2026-11-05 | Notes app v1-v3; matrix output: PASS, PASS, FAIL (v3) |
| 2 | Sandbox and test templates | Done | stage-2-sandbox / stage-2-done | 2026-11-06 | 2026-11-06 | All 5 templates verified across Notes v1-v3, PostgREST, broken build; zero leftover containers |
| 3 | Backend core | Done | stage-3-backend / stage-3-done | 2026-11-07 | 2026-11-09 | Core DB migrations, self-hosted auth, importers, Redis+RQ queue, worker, projects/versions/protections/runs endpoints, run status polling |
| 4 | Regression engine (core) | Not started | stage-4-regression | | | |
| 5 | Dashboard v1 | Not started | stage-5-dashboard | | | |
| A | **Checkpoint A: core demo** | Not started | v0.1 | | | |
| 6 | Application Model | Not started | stage-6-model | | | |
| 6B | Security Catalog and Tier 1 checks | Not started | stage-6b-catalog | | | |
| 7 | Agent runtime | Not started | stage-7-agents | | | |
| 7B | Skills library | Not started | stage-7b-skills | | | |
| 8 | Protections workflow | Not started | stage-8-protections | | | |
| 9 | Auditor agent | Not started | stage-9-auditor | | | |
| 10 | Fixer agent + gate | Not started | stage-10-fixer | | | |
| B | **Checkpoint B: agents working** | Not started | v0.2 | | | |
| 11 | Phase 0 documents | Not started | stage-11-docs | | | |
| 12 | Condense | Not started | stage-12-condense | | | |
| 12B | Tier 2 checks | Not started | stage-12b-tier2 | | | |
| 13 | Evaluation | Not started | stage-13-eval | | | |
| 14 | Report and polish | Not started | v1.0 | | | |

**Current stage:** 4
**Cut line:** must finish Stages 0 to 10, 6B (at least batches 1 and 2), 7B (first 6 skills) and 13. Then the rest of 6B, 12, 12B, 11. Drop first: Tier 2 checks, agent simplification, bisect, doc drift, MCP, fine-tuning, Strix plugin, GitHub Action, notifications.

---

## Stage 0: Setup and tracking
- [x] Create repo; `main` branch; folder layout from `setup.md`
- [x] Put the docs in `docs/` (the 15 files, `plan.md`, `tracker.md`, `decisions.md`)
- [x] `.gitignore` (`.env`, `node_modules`, `.venv`, build output)
- [x] `docker-compose.yml` with Redis and Postgres
- [x] `.env.example` from `setup.md`
- [x] FastAPI skeleton with `/api/v1/health`
- [x] React + Vite skeleton page
- [ ] One dummy backend test and one dummy frontend test pass
- [x] Root `AGENTS.md` (copy from `repo-root/`), `agents/skills/` folder, Makefile, pre-commit config, CI workflow running lint and tests
- [x] Install Ollama, pull a small coder model, check it answers a short prompt
- [x] Note RAM use and response speed in `decisions.md`
- [ ] Settle the project name

**Done when:** `/health` returns OK, the frontend loads, one test passes, Ollama answers.

## Stage 1: Prove the idea (CLI only)
- [x] Notes app V1: basic notes, owner-only access
- [x] V2: search feature added
- [x] V3: sharing feature that accidentally breaks owner-only access
- [x] Each version saved as a git commit with a tag (v1, v2, v3)
- [x] Hand-written ownership test: User A creates a note, User B requests it, expect denial
- [x] Script runs the test on V1, V2, V3 and stores results (JSON or SQLite is fine)
- [x] Script prints the matrix and names V3 as the first failed version
- [x] Tag `stage-1-done`

**Done when:** output shows PASS, PASS, FAIL and names V3.

## Stage 2: Sandbox and test templates
- [x] Dockerfile for running a Node app
- [x] Postgres + PostgREST containers with an `auth.uid()` helper
- [x] Seed User A, User B, Admin, Anonymous (generated passwords)
- [x] `http_request_as(user, request)` helper
- [x] Template: ownership
- [x] Template: unauthenticated
- [x] Template: role
- [x] Template: RLS
- [x] Template: validation
- [x] Result states PASS / FAIL / ERROR / SKIPPED; build failure gives ERROR
- [x] Limits: timeout, memory, non-root, no network except its own DB, container destroyed after run
- [x] Run all templates on Notes V1 to V3 with evidence stored
- [x] Record run time and RAM

**Done when:** templates run with evidence on Notes, and a deliberately broken build gives `ERROR`, not `FAIL`.

## Stage 3: Backend core
- [x] Decide platform database (Supabase free tier or local Postgres) and log it
- [x] Migrations for core tables (projects, versions, runs, protections, protection_results, regressions); add others when first needed and keep `database.md` in sync
- [x] Login: Self-hosted auth (bcrypt password hashing, JWT_SECRET, register/login endpoints, JWT check, roles)
- [x] Import from folder and GitHub (with stack detection, git commit extraction, and version creation); ZIP to follow
- [x] Redis + RQ queue; worker with concurrency 1
- [x] Endpoints from `api.md`: projects, import, versions, protections, runs
- [x] Run status polling works
- [x] Unit and integration tests

**Done when:** importing an app creates a version and a run you can poll to `done`.

## Stage 4: Regression engine (core)
- [ ] Comparison logic: PASS to FAIL is a regression; FAIL to PASS is fixed; none to any is new; ERROR never a regression
- [ ] Impact selection: run all protections (small apps)
- [ ] GitHub webhook with HMAC check; creates version and queues a monitor run
- [ ] Regression record: first failed version, suspect commit, associated feature, evidence
- [ ] Matrix, regressions and quality-trend endpoints
- [ ] Unit tests for the must-have rules in `testing.md`
- [ ] End to end: push V3, get a regression report

**Done when:** pushing V3 produces a regression report that names V3 and shows the evidence.

## Stage 5: Dashboard v1
- [ ] Projects list and import screen
- [ ] Protections screen (manual add, confirm)
- [ ] History matrix (colour plus text)
- [ ] Regression report and evidence drawer
- [ ] Run progress; empty, error and ERROR states
- [ ] Whole Notes demo runs from the browser

**Done when:** you can run the full demo without touching the terminal.

## Checkpoint A: core demo
- [ ] Merge to `main`, tag `v0.1`
- [ ] Record a short demo video
- [ ] Back up (push to GitHub and copy a zip)
- [ ] Update docs that changed; update this tracker
- [ ] Show the supervisor

## Stage 6: Application Model
- [ ] tree-sitter parser for TS/JS: frontend calls, routes, auth checks, functions
- [ ] SQL migration parser: tables and RLS policies
- [ ] Graph build (networkx); broken links list
- [ ] Quality metrics: cloc, knip, jscpd stored in `quality_metrics`
- [ ] App Map screen (React Flow)
- [ ] Check on Notes and one more app

**Done when:** the Notes graph is correct and viewable, and broken links are listed.

## Stage 6B: Security Catalog and Tier 1 checks
- [ ] Load `security-catalog.md` into `security_checks`
- [ ] Applicability planning (detect uploads, GraphQL, payments, LLM calls); mark N/A and MANUAL
- [ ] `check_results` and `coverage_reports` tables, endpoints, Coverage Report screen
- [ ] Wording rule in code and UI: never say "secure"
- [ ] Batch 1: secrets in repo and bundle, dependencies, security headers, CORS, cookie flags
- [ ] Batch 2: password storage and hashing rules, crypto and random rules, JWT and session rules, debug mode and insecure defaults
- [ ] Batch 3: injection and XSS (static rules plus live probes), CSRF, input validation
- [ ] Batch 4: login rate limit, API checks (mass assignment, excessive data, rate limits), database checks (RLS on all tables, permissive policies, service key in client)
- [ ] For every check: a vulnerable fixture and a safe fixture in `golden/check-fixtures/`
- [ ] Update the status column in `security-catalog.md` after each check

**Done when:** the Coverage Report works, and every implemented check fails its vulnerable fixture and passes its safe one.

## Stage 7: Agent runtime
- [ ] Tool schema (Pydantic) and tool registry with read/write permissions
- [ ] Agent loop with limits (steps, time, model calls) and stop reasons
- [ ] Model adapter interface: `replay` and `ollama`
- [ ] JSON-schema output check; one retry, then fail visibly
- [ ] `agent_steps` logging
- [ ] First tools: `read_file`, `search_code`, `query_app_model`, `run_protection_test`
- [ ] Tool tests without a model; agent tests with recorded replies
- [ ] Basic agent trace screen

**Done when:** a toy agent completes a task using tools and stops safely at its limits.

## Stage 7B: Skills library
- [ ] `load_skill(name)` tool (max two skills per model call)
- [ ] Write the first 6: access-control (sample exists), authentication-and-passwords, crypto-and-hashing, sessions-jwt, injection, xss-and-csrf
- [ ] Write the rest as their checks are built: api-security, database-and-rls, secrets-and-config, headers-cors-transport, dependencies-supply-chain, file-upload-ssrf, logging-and-errors, fix-patterns-react-supabase, condense-safely
- [ ] Keep each to 300 to 600 words in the standard format
- [ ] Recorded-replay test where an agent loads a skill

**Done when:** an agent loads and uses a skill in a recorded test.

## Stage 8: Protections workflow
- [ ] Rule-based candidate protections
- [ ] Model-proposed protections, grounded to real nodes
- [ ] Confirm / edit / reject screen
- [ ] Template binding and a dry run before saving
- [ ] Behaviour snapshots of key endpoints
- [ ] Tests

**Done when:** confirmed protections run as tests on Notes.

## Stage 9: Auditor agent
- [ ] Tools: `http_request_as`, `run_semgrep`, `run_playwright` (if needed)
- [ ] Hypothesis loop: pick a gap, send a real request as another user, record a finding only with proof
- [ ] Three seeded-bug apps
- [ ] Record model replies for tests
- [ ] Measure proof rate

**Done when:** it finds one seeded bug with a valid proof.

## Stage 10: Fixer agent + gate
- [ ] `apply_patch` on a branch only
- [ ] `run_gate`: build, lint, behaviour snapshots, all protections, size check
- [ ] Fixer loop with up to 3 retries using gate feedback
- [ ] Approval flow in the dashboard
- [ ] Fixed vulnerability keeps a reproducing test
- [ ] Measure fix success rate

**Done when:** one seeded bug is found, fixed and verified through the gate.

## Checkpoint B: agents working
- [ ] Merge to `main`, tag `v0.2`
- [ ] Demo video of Auditor and Fixer
- [ ] Back up; update docs and tracker

## Stage 11: Phase 0 documents
- [ ] Inventory of the 15 files (name and content search)
- [ ] Structured cross-check (routes, tables, roles, env variables)
- [ ] Minimal reconstruction of 2 to 3 files
- [ ] Conflict screen; trust labels

**Done when:** it works on the Notes app.

## Stage 12: Condense
- [ ] Dead code removal with knip through the gate
- [ ] Duplicate merge with jscpd through the gate
- [ ] Agent simplification (only if time)
- [ ] Before and after metrics; Condense screen

**Done when:** lines are measurably reduced with zero protection or behaviour breaks.

## Stage 12B: Tier 2 checks
- [ ] File upload, path traversal, SSRF
- [ ] User enumeration, password reset flow, password policy
- [ ] Webhook signature checks, API depth (pagination, methods, shadow endpoints)
- [ ] Fixtures for each; update catalog status and coverage report

**Done when:** each Tier 2 check has fixtures and the coverage report shows it.

## Stage 13: Evaluation
- [ ] Golden apps ready: Notes, Tasks, Orders, Profile, Docs-mismatch, Bloated
- [ ] Answer keys written
- [ ] Run everything; save raw results
- [ ] Model comparison table
- [ ] Baselines: Semgrep, Skylos, optionally Strix
- [ ] Metrics from `prd.md` collected; charts made
- [ ] Limitations written down honestly

**Done when:** every metric in `prd.md` has a number.

## Stage 14: Report and polish
- [ ] Report written
- [ ] README final
- [ ] Final demo video
- [ ] Cleanup; docs match reality
- [ ] Tag `v1.0`

---

## Issues log
| # | Date | Stage | Problem | Status | Fix or workaround |
|---|---|---|---|---|---|
| 1 | | | | | |

## Session log
| Date | Worked on | Done | Next |
|---|---|---|---|
| 2026-11-08 | Stage 3 (Task 25: Direct GitHub Repository Importer) | Built POST /api/v1/projects/{project_id}/import/github; strict URL validation (HTTPS github.com, regex, no credentials/queries); safe depth-1 git clone with timeouts & prompt suppression; stack detection; snapshot retention in managed storage; 15 test scenarios & live GitHub integration verified | Stage 3 (Task 26: Redis + RQ Queue & Worker) |
| 2026-11-08 | Stage 3 (Task 24: Folder Importer & Stack Detection) | Built POST /api/v1/projects/{project_id}/import with folder path; stack detection for node-express with clear 422 for unsupported stacks; git commit hash extraction; path traversal rejection (400); creates/persists Project and Version records in platform DB | Stage 3 (Task 25: Redis + RQ Queue & Worker) |
| 2026-11-08 | Stage 3 (Task 23 REDO: Self-hosted Auth with bcrypt + JWT) | Rebuilt platform auth as self-hosted matching golden/notes-app; added password_hash to users table, implemented /auth/register and /auth/login with bcrypt & platform JWT_SECRET; tested 4 scenarios | Stage 3 (Task 24: Project import) |
| 2026-11-07 | Stage 3 (Task 22: Platform DB migrations & Alembic setup) | Added Alembic + SQLAlchemy + Psycopg; created 6 core platform tables in nigrani-db (port 5433); round-trip test passed | Stage 3 (Task 23: Login & Auth) |
| 2026-11-06 | Stage 2 (Tasks 19-21: RLS, validation, limits & full matrix) | Built rls.py, validation.py, runner.py hardening (memory 512MB, timeout 60s, non-root, zero leftovers); ran full Stage 2 matrix across Notes v1-v3, PostgREST, broken build | Stage 3 (Backend core) |
| 2026-11-06 | Stage 2 (Task 18: Template: role) | Built generic run_role_test template with admin baseline verification; tagged v1-admin-test in Notes app and verified 403 (non-admin) vs 200 (admin) | Stage 2 (Remaining test templates: RLS, validation) |
| 2026-11-06 | Stage 2 (Task 17: Template: unauthenticated) | Built generic run_unauthenticated_test template; verified HTTP 401 on Notes v1-v3 and HTTP 200 [] on PostgREST under anonymous role | Stage 2 (Remaining test templates: role, RLS, validation) |
| 2026-11-06 | Stage 2 (Task 16: Template: ownership) | Built generic run_ownership_test template supporting both 'app' and 'postgrest' targets, PASS/FAIL/ERROR verdicts, and Notes v1/v3 & PostgREST verification | Stage 2 (Remaining test templates: unauthenticated, role, RLS, validation) |
| 2026-11-06 | Stage 2 (Task 15: http_request_as helper) | Built reusable http_request_as helper with identity normalization, structured evidence, token redaction, and PostgREST/app target support | Stage 2 (Task 16: Test templates: ownership, unauthenticated, role, RLS, validation) |
| 2026-11-06 | Stage 2 (Tasks 11, 13, 14: sandbox Dockerfile, PostgREST + auth.uid(), seed_users) | Built sandbox Dockerfile, PostgREST RLS with auth.uid(), and reusable schema-flexible seed_users module | Stage 2 (Task 15: http_request_as helper) |
| 2026-11-05 | Stage 1 (Notes app v1-v3, ownership regression test runner) | Notes app v1, v2, v3 built & tagged; run_ownership_test.py automated matrix detection | Stage 2 (Sandbox and test templates) |

## Parking lot (stretch, not planned)
Agent simplification, bisect across commits, doc drift check, MCP server, notifications, Strix plugin, fine-tuned model, GitHub Action for pull-request scans, Tier 3 checks.
