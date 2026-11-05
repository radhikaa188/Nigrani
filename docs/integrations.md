# Integrations

| Integration | Used for | How | Phase |
|---|---|---|---|
| GitHub | Clone repos, diffs, fix branches or PRs, push events | GitHub App (preferred) or token; webhook to `/webhooks/github` | 0 to 4 |
| Supabase | Platform database and auth | Supabase client; free tier keeps laptop RAM low | All |
| **Ollama** | Local model (default brain) | HTTP at `127.0.0.1:11434`, JSON-schema output | 0, 2, 3, 4 |
| Hosted model (optional) | Development speed and comparison row only | Second adapter; key in env; spend cap | Dev, evaluation |
| Semgrep | Static code patterns | CLI in worker; custom rules for auth, RLS, secrets | 3 |
| tree-sitter | Routes, calls, auth checks, functions | TypeScript/JavaScript grammars | 1 |
| Playwright | Runtime tests as different users | Headless Chromium in the sandbox host | 3, 4 |
| httpx | Direct API tests with missing or other credentials | Python client in the test engine | 3, 4 |
| Docker | Sandbox | Docker SDK from worker | 3, 4 |
| Postgres + PostgREST | Sandbox database and REST layer for Supabase-style apps | Containers with a small `auth.uid()` helper; lighter than the full local Supabase stack | 3, 4 |
| Redis + RQ | Job queue | Local container | All |
| npm audit, Gitleaks | Dependencies and secrets | CLI in worker | 3 |
| knip, jscpd, cloc, ESLint | Unused code, duplicates, size, lint | CLI in worker | 1, 3 |
| Strix (optional) | Extra AI pentest findings | Run as a separate scanner; import findings with `source = strix` | 3 (stretch) |
| pgvector (later) | Memory search | Postgres extension | 2, 3 |
| Notifications (stretch) | Regression alerts | Email or Slack webhook | 4 |

## GitHub webhook handling
1. Verify the HMAC signature with the project's secret.
2. Ignore untracked branches.
3. Create the next version with the pushed commit(s).
4. Queue a monitor run and return `202` immediately.
5. If several commits arrived together, store all; bisect later if a regression appears.

## Model adapter contract
`ask_model(messages, schema) -> dict`. Adapters: `ollama`, `hosted`, `replay` (recorded replies for tests). Chosen via `/settings/model`.

## Secrets
Keys live in environment variables only. Never committed, logged or sent to a model.

## Failure behaviour
- GitHub or model unavailable: run marked failed with a clear reason; retry with backoff; never produce a fake PASS.
- Ollama not running: dashboard shows "start Ollama"; non-model steps still work.
