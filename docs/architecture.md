# Architecture

## 1. Big picture
```
React Dashboard <-> FastAPI <-> PostgreSQL / Supabase
                       |
                  Redis + RQ --> Worker (one job at a time)
                                    |
      +-----------+-----------+-----+------+--------------+
   Importer   Parser/Model   Agent Runtime   Test Engine   Quality tools
   (git,zip)  (tree-sitter)  (loop, tools,   (httpx,       (cloc, knip,
                              memory)         Playwright)   jscpd)
                                |                  |
                          Model Adapter --> Ollama  Docker Sandbox
                                                    (app + Postgres + PostgREST)
                                |
                        Verification Gate
```

## 2. Components
| Component | Job | Stack | Connected to |
|---|---|---|---|
| Dashboard | Import, confirm, approve, view history and agent traces | React, Vite, TypeScript, Tailwind, React Flow, Recharts | Backend (REST) |
| Backend API | Entry point; creates runs; receives webhooks; serves results | Python, FastAPI, Pydantic | Dashboard, DB, Queue |
| Queue | Holds long jobs | Redis + RQ | Backend, Worker |
| Worker | Runs one job at a time (saves RAM) | Python | Everything below |
| Importer | Gets code as Version N | git / GitPython, zipfile | Worker, DB |
| Parser and App Model | Builds page to API to route to auth to table to RLS map; lists broken links | tree-sitter (TS/JS), SQL parsing, networkx | Worker, agents, DB |
| Quality analyzer | Lines, unused code, duplicates, complexity | cloc, knip, jscpd | Worker, DB |
| Sandbox | Runs untrusted app safely with seeded users | Docker, Node image, Postgres + PostgREST, small `auth.uid()` helper | Test engine, gate |
| Test engine | Runs protection tests | httpx, Playwright (headless Chromium), pytest | Sandbox, DB |
| Agent runtime | The agents' loop, limits, orchestration, logging | Own Python code, Pydantic tool schemas | Model adapter, tool registry, memory |
| Tool registry | Actions agents can take | Wrappers (Semgrep, git, httpx, Playwright) + custom tools | Agents, sandbox |
| Model adapter | One function `ask_model(messages)`; JSON-schema output | Python; Ollama on localhost:11434 (default); optional hosted adapter | Agent runtime |
| Memory | Protection history, past fixes, security notes | Postgres tables; pgvector later | Agents |
| Verification gate | Accept or reject every fix or condense | tsc/eslint/npm build, deepdiff, own code | Agents, test engine |
| Database | All state | Supabase free tier or local Postgres | Everything |
| GitHub link | Tells us about new pushes | Webhooks, server-generated secrets (`secrets.token_hex(32)`), HMAC check, PyGithub, tunnel in development | Backend |
| Logging | Replay any run | structlog, JSON, stored as `agent_steps` | All |

## 3. Data flow by phase
**Phase 0, project readiness.** Worker searches the folder for the 15 files. Missing: parser extracts facts (routes, tables, roles) and the model writes a draft marked unverified. Present: code compares structured parts (routes, tables, env); the model judges free-text claims. Conflicts go to the developer.

**Phase 1, understand.** Parser builds the Application Model; quality analyzer saves "before" numbers; the Mapper agent resolves links static analysis cannot.

**Phase 2, protections.** Code rules propose candidates (table with `user_id` and no RLS gives owner-only access). The model adds rules from the docs; each must point to real nodes. Developer confirms. Each protection gets a fixed test template, a dry run, and behaviour snapshots are saved.

**Phase 3, secure and condense.**
1. Sandbox builds and starts the app with seeded users.
2. Scans and protection tests produce findings.
3. **Auditor** forms a hypothesis, sends a real request as another user, saves a finding only with proof.
4. **Fixer** patches on a branch, runs the gate, retries (max 3).
5. **Optimizer** runs knip and jscpd first, then simplifies single units; same gate.
6. Developer approves; result saved as **Baseline V1**.

**Phase 4, monitor (core).**
1. Project import auto-generates a server-side `webhook_secret` (never client-provided; retrievable via `GET` or rotated via `POST .../regenerate`). Incoming GitHub push webhooks verify the HMAC-SHA256 signature against that secret, create Version N+1, and queue a run.
2. Diff plus the Application Model selects affected protections (small apps: run all).
3. Sandbox runs: new-code checks, old fixed-vulnerability tests, old protection tests; plus quality drift.
4. SQL comparison with the previous result: PASS to FAIL is a regression.
5. Several commits in one push: **Sentinel** bisects to the first failing commit.
6. Evidence, commit and feature stored; shown in the history matrix.

## 4. Agent runtime (own code)
- **Loop:** read task, ask model, parse tool call, validate, run in sandbox, observe, repeat.
- **Limits:** max steps, max time, max model calls per run.
- **Permissions:** each agent gets only the tools it needs.
- **Checker:** tests and the gate verify the result; the agent never grades itself.
- Details in agents.md.

## 5. Verification gate
A change is accepted only if **all** are true: build and lint pass; behaviour snapshots match; every confirmed protection still PASSES; for condensing, lines or complexity decreased. Otherwise it is rolled back and logged.

## 6. Result states
`PASS`, `FAIL`, `ERROR` (could not run), `SKIPPED`. **ERROR is never a regression.**

## 7. Laptop limits (16GB, CPU only)
- One worker, concurrency 1; one sandbox at a time.
- Default model about 3B (4-bit); try about 7B for fixes only. vLLM is skipped (needs a GPU).
- Short prompts; model called only for protections, Auditor, Fixer, Optimizer and doc work.
- Plain Postgres + PostgREST in the sandbox instead of the full local Supabase stack.
- Agents are tested with recorded model replies.

## 8. Safety of the platform itself
Imported apps are untrusted code. Sandbox: no host mounts except the copied code, no network except its own test database, CPU/memory/time limits, non-root, destroyed after each run, no host secrets. Ollama listens on 127.0.0.1 only.

## 9. Key decisions
| Decision | Choice | Reason |
|---|---|---|
| Agents | Own runtime, no frameworks | Practical and demonstrates real skill |
| Brain | Ollama, open-weight model; adapter keeps it swappable | No per-call cost; fits the project goal |
| First stack | React + Supabase | Typical Lovable output; keeps scope feasible |
| PASS/FAIL | Tests only | Repeatable and defensible |
| Fixes and condensing | Branch plus approval | Never silent edits |
| Queue | Redis + RQ | Simple, small RAM |
