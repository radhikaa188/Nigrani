# Testing

Two questions: **(1) does the platform work?** **(2) can we prove it for the research claim?**

## 1. Testing the platform
| Level | What | Tools |
|---|---|---|
| Unit | Parsers, comparison logic, gate logic, doc-claim matching | pytest, Vitest |
| **Tool tests** | Every tool tested alone, without a model | pytest |
| **Agent tests** | Agent loop with **recorded model replies**: limits, invalid tool calls, retries, stop rules | pytest, replay adapter |
| Integration | API plus database; worker plus sandbox; webhook to run | pytest, docker compose |
| End to end | Import, confirm protection, push new version, see regression | Playwright |
| Platform security | The platform passes its own ownership, unauthenticated and role tests | Same templates |

### Must-have unit tests
- Only PASS to FAIL creates a regression; ERROR never does.
- The gate rejects a patch if any protection fails, even if lines decreased.
- The gate rejects a patch if the behaviour snapshot differs.
- The agent stops at the step limit and records why.
- A webhook with a bad signature is rejected.
- A tool call with invalid inputs is rejected before running.

## 2. Evaluation apps (the proof)
Keep small AI-generated React + Supabase apps in `golden/`, each with versions and an answer key.

| App | Seeded problem |
|---|---|
| Notes (V1, V2, V3) | V3 sharing feature breaks owner-only access (the report example) |
| Tasks | Admin route loses its role check in a later version |
| Orders | RLS policy dropped by a migration |
| Profile | Previously fixed input validation reappears |
| Docs-mismatch app | PRD claims rules the code does not enforce |
| Bloated app | Lots of dead and duplicated code, behaviour known |

## 3. Metrics
| Metric | How measured |
|---|---|
| Regression recall and false alarms | Seeded regressions found, wrong alarms |
| First-failed-version accuracy | Correct version and commit named |
| Auditor proof rate | Findings with valid proof vs Semgrep alone |
| Fix success rate | Patches that pass the gate, per model |
| Doc mismatch detection | Seeded mismatches found |
| Safe condensing | Lines removed per app; protection or behaviour breaks (target 0) |
| Time and cost | Minutes per run on the 16GB laptop; steps per run |

## 4. Model comparison table (the GenAI result)
Run the same tasks with: small local model, larger local model if it fits, optional hosted model as upper bound, and (stretch) a fine-tuned model. Report fix success rate, Auditor proof rate, time and failures. Weak results from small models are findings, not failures.

## 5. Baselines (related work)
Run **Semgrep**, **Skylos** and optionally **Strix** on the same version sequences. Record whether each flags the Notes V3 break and whether any names V3 as the first failing version. This decides how strongly the research gap can be claimed.

## 6. Rules
- Same input, same verdict; flaky tests are fixed or reported as `ERROR`.
- Never run golden apps outside the sandbox.
- State limits honestly (apps without tests have a weaker behaviour baseline; one stack only).
