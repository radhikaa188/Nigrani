# Build Plan

Build something that **works early**, then add on top. Each stage is finished and tested before the next one starts. Progress is tracked in `tracker.md`; changes of mind go in `decisions.md`.

## Stages
| # | Stage | What gets built | Done when | Size |
|---|---|---|---|---|
| 0 | Setup and tracking | Repo, branches, folder layout, docker-compose (Redis, DB), `.env.example`, health endpoint, empty dashboard, root `AGENTS.md`, Makefile, pre-commit, CI | `/health` OK, frontend loads, one dummy test passes | S |
| 1 | **Prove the idea (CLI only)** | Notes app V1, V2, V3 (V3 breaks owner-only access); one hand-written ownership test; results stored; matrix printed | Output shows PASS, PASS, FAIL and names V3 | S |
| 2 | Sandbox and test templates | Docker runner, Postgres + PostgREST, `auth.uid()` helper, seeded users A/B/Admin, 5 templates, `ERROR` handling | Templates run on Notes with evidence; a broken build gives `ERROR`, not `FAIL` | M |
| 3 | Backend core | Migrations, import and versioning, runs, queue + worker (one job at a time), main endpoints | Importing an app creates a version and a run you can poll | M |
| 4 | **Regression engine (core)** | Comparison logic, run-all impact selection, GitHub webhook, regression records, matrix endpoint | A push of V3 produces a regression report with evidence | M |
| 5 | Dashboard v1 | Projects, import, protections, history matrix, regression report, evidence drawer | Whole Notes demo runs from the browser | M |
| A | **Checkpoint A: core demo** | Tag `v0.1`, demo video, backup | Core idea shown end to end | |
| 6 | Application Model | React + Supabase parser, graph, broken links, quality metrics | Notes graph is correct and viewable | M |
| 6B | **Security Catalog and Tier 1 checks** | Catalog in the database, applicability planning, Coverage Report, Tier 1 checks in 4 batches, each with a vulnerable and a safe fixture | Coverage Report works; each implemented check fails its vulnerable fixture and passes its safe one | XL |
| 7 | Agent runtime | Loop, limits, tool registry, adapters (`replay`, `ollama`), `agent_steps`, tool and agent tests | A toy agent finishes a task and stops safely at its limits | M |
| 7B | Skills library | `load_skill` tool; first 6 skills written; the rest as their checks are built | An agent loads and uses a skill in a recorded test | M |
| 8 | Protections workflow | Rule-based candidates, model proposals, confirm screen, dry run, behaviour snapshots | Confirmed protections run as tests | M |
| 9 | Auditor agent | Hypothesis, `http_request_as`, findings only with proof | Finds one seeded bug with valid proof | L |
| 10 | Fixer agent + gate | Patch on a branch, verification gate, up to 3 retries, approval flow | One seeded bug found, fixed and verified | L |
| B | **Checkpoint B: agents working** | Tag `v0.2`, backup | Auditor and Fixer work end to end | |
| 11 | Phase 0 documents | Inventory, structured cross-check, minimal reconstruction, conflict screen | Works on the Notes app | M |
| 12 | Condense | Dead code and duplicates through tools, same gate; agent simplification only if time | Measured line reduction, zero breaks | M |
| 12B | Tier 2 checks | File upload, SSRF, path traversal, user enumeration, password reset, webhooks, API depth | Each has fixtures; coverage report updated | L |
| 13 | Evaluation | Golden apps, model comparison, Semgrep/Skylos/Strix baselines, metrics and charts | A number for every metric in `prd.md` | L |
| 14 | Report and polish | Report, README, demo video, cleanup, tag `v1.0` | Frozen and presentable | M |

## Cut line
- **Must finish:** Stages 0 to 10, 6B (at least batches 1 and 2), 7B (first 6 skills) and 13.
- **Next:** the rest of 6B, then Stage 12, then 12B, then Stage 11 (minimal).
- **Drop first when behind:** Tier 2 checks, agent simplification, bisect, doc drift, MCP, fine-tuning, Strix plugin, GitHub Action, notifications.

## Working rules
1. One stage at a time; the next starts only when "done when" passes.
2. `main` always works. Each stage lives on its own branch (`stage-N-name`); merge when done, then tag `stage-N-done`.
3. If something breaks: stop, return to the last tag, log it in `tracker.md`, retry in a smaller step.
4. Time-box each stage; past 1.5x the estimate, cut scope using the cut line rather than extending silently.
5. Develop agents with recorded model replies; use the live model only to record and for evaluation.
6. After each stage, update the matching doc if reality changed, and record changed choices in `decisions.md`.
7. Freeze features after Stage 12; only evaluation and writing remain.

## Where trouble is expected
- **Stage 2** is the riskiest (building and running arbitrary apps). Stay with apps you control.
- **Stages 9 and 10:** a small local model gives weak results. Measure and report it; don't spend weeks fixing it.
- **Stage 6B** is the largest. Build it in batches and stop adding checks when time is up; the Coverage Report stays honest about what is not covered.
- **Laptop limits:** one job and one sandbox at a time; cap WSL2 memory.
