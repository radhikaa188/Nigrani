# AGENTS.md (place at the repo root)

Rules for AI coding tools (Antigravity, Gemini CLI, Cursor, Claude Code) working on this repo.

## Before you start
1. Read `docs/plan.md` and `docs/tracker.md`. Work only on the **current stage**.
2. Read the docs that stage needs: `architecture.md`, `database.md`, `api.md`, and `security-catalog.md` for checks.
3. If a task is outside the current stage, stop and say so.

## How to work
- Return **complete replacement files**, not fragments.
- Run the tests before saying you are done; show the result.
- Make small commits: one task, one commit. One branch per stage (`stage-N-name`).
- Add or update a test with every behaviour change.
- Update the matching doc and `docs/tracker.md` when you finish a task. Record changed choices in `docs/decisions.md`.
- No new dependency without a one-line reason.
- Keep code small and readable. This project criticizes bloated AI code, so do not produce any.

## Hard rules
- Never run imported or generated apps outside the sandbox.
- **PASS/FAIL comes from tests only**, never from a model.
- A test that cannot run is `ERROR`, never a regression.
- Nothing merges without developer approval; never change the verification gate without updating `architecture.md`.
- Never commit secrets or `.env`.
- Never say an app is "secure". Reports state what was checked and the result.
