# Debugging

## First steps for any failure
1. Open the run: which step failed?
2. Open the **agent trace** (`/runs/{id}/steps`) and read the last model call and tool call.
3. Check `runs.error` and the worker log for that `run_id`.
4. Reproduce locally with the same version snapshot in the sandbox, using the replay adapter if the model was involved.
5. Decide: is it the **platform**, the **target app**, the **model**, or the **environment**?

## Common problems
| Symptom | Likely cause | What to do |
|---|---|---|
| Run stuck in `queued` | Worker or Redis not running | Start worker; check Redis |
| Run stuck in `running` | Sandbox hung or model very slow | Check container and Ollama logs; enforce time limits |
| Every test `ERROR` | App did not build or start | Read build log; check stack detection and env vars |
| Test flips PASS/FAIL | Flaky runtime test or seed race | Re-run 3 times; wait on events; reseed per run |
| Playwright cannot log in | Seeded users missing or auth flow changed | Verify seeding; update login helper |
| RLS test returns rows it should not | Real vulnerability, or the test used the service key | Confirm the test uses the user's JWT |
| False regression | Test depends on changed UI text or route | Check evidence; use stable identifiers |
| Regression names wrong commit | Several commits in one push | Run bisect |
| **Agent loops forever** | No stop rule or limit | Check step, time and call limits; read the trace for repeated tool calls |
| **Invalid tool call JSON** | Model too small or prompt too long | Shorten prompt; check schema; one retry then fail visibly |
| **Model invents a file or route** | Hallucination | Grounding check drops it; inspect the input context |
| **Ollama connection refused** | Ollama not running | Start Ollama; check the address `127.0.0.1:11434` |
| **Out of memory or laptop freezes** | Model, Docker and Chromium together | Use the 3B model; stop other apps; cap WSL2 memory; one sandbox at a time |
| **Very slow answers** | CPU-only model | Smaller model, shorter prompts, fewer calls; use recorded replies when developing |
| Fix accepted but app broken | Behaviour snapshot too weak | Add a snapshot or smoke flow for that area |
| Webhook returns 401 | Signature mismatch | Check secret and raw-body handling |
| Webhook never arrives | Bad URL or no tunnel | Use ngrok or Cloudflare tunnel in development; check GitHub delivery log |
| Doc verifier says "conflicting" everywhere | Free-text matching too fuzzy | Compare structured items first; model for prose only |

## Logging conventions
- Every line carries `project_id`, `version_id`, `run_id`, `agent`, `step`.
- Store test evidence (request, response, excerpt), truncate large bodies.
- Log every model call with tokens and duration; never log secrets.

## Debug switches
- `DEBUG_KEEP_CONTAINER=1`: keep the sandbox for inspection.
- `DEBUG_RUN_ALL=1`: skip impact analysis, run every protection.
- `MODEL_ADAPTER=replay`: reuse recorded replies, no model needed.

## When it is the target app, not the platform
Do not "fix" the platform to hide it. Record `ERROR` with the reason so results stay honest.
