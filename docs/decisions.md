# Decisions

Record every choice that changes the plan, with the date and the reason. Newest first within each section.

## Made
| Date | Decision | Reason |
|---|---|---|
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
| Platform database: Supabase free tier or local Postgres | Stage 3 |
| Final list and wording of the 15 files | Stage 11 |
| Which apps are the evaluation (golden) apps | Stage 13 |
| Which model sizes the laptop really sustains | Stage 7 |
