# Product Requirements Document (PRD)

**Project:** Agent-Based Continuous Security Platform for AI-Generated Full-Stack Apps (B.Tech final-year major project)
**Status:** Draft v0.2 | **Owner:** RadhikaAg

## 1. Problem
AI coding tools (Lovable, Bolt, Replit, Cursor, v0) generate full-stack apps fast, but:
1. **Security gaps and broken connections.** Frontend, backend, API and database are not always wired correctly (missing auth checks, missing RLS, calls to routes that don't exist).
2. **Security regressions.** Every new AI edit can break a protection that worked, or bring back a fixed vulnerability. Scanning only the latest version never shows *when* or *why* it broke.
3. **Bloated code.** AI writes thousands of lines that could be hundreds. Nobody reads them, so nobody reviews them.

## 2. Goal
Use **our own agents** to **secure** an AI-generated app, **condense** it, and **keep watching every new version**, so any broken protection is caught and traced to the change that caused it.

## 3. Research claim
> A tool-using agent system, built from scratch, that finds, fixes and condenses AI-generated apps, where every agent action is **verified by executable tests**, backed by a **persistent protection memory across versions**, running on a **self-hosted open-weight model** on a student laptop.

**Related work and how we differ:** Semgrep, CodeQL and Skylos scan code; Strix runs AI pentest agents against a live app. We found no evidence that they keep a developer-confirmed protection baseline, re-test it every version, and name the first failing version and commit. This must be confirmed by the head-to-head experiment in testing.md, not assumed.

## 4. Users
- **Primary:** solo developers, students and small teams building with AI tools.
- **Secondary:** supervisors and reviewers evaluating the project.

## 5. Scope
**In scope (MVP):**
- Import from GitHub repo, ZIP or local folder.
- First supported stack: **React (Vite) + Supabase (Postgres + RLS)**, typical Lovable output.
- Phases 0 to 4 (see architecture.md), with the **Auditor** and **Fixer** agents as the minimum agent set.
- Dashboard for findings, protections, agent traces and version history.

**Out of scope:**
- Other stacks (later), mobile apps.
- Training or hosting our own model at scale; model fine-tuning is a stretch.
- Prompt-injection or model-level attacks on AI tools.
- Production monitoring, WAF, pentesting live production.
- Auto-merging any change without developer approval.

## 6. User stories
- I import my app and see which of the 15 documents exist, which are missing and which disagree with the code.
- I confirm or reject the security rules the platform proposes.
- I get fixes and condensed code as reviewable branches, never silent changes.
- When my AI tool pushes a commit, I am told if any protection went from PASS to FAIL, and which change caused it.
- I can open an agent's trace and see every step it took.

## 7. Functional requirements
| ID | Requirement |
|---|---|
| FR-1 | Import an app and store it as Version 1. |
| FR-2 | Phase 0: inventory the 15 files; reconstruct missing; cross-check existing; list conflicts. |
| FR-3 | Build an Application Model (page, API, route, auth check, table, RLS policy) and quality metrics. |
| FR-4 | Propose candidate protections; developer confirms, edits or rejects. |
| FR-5 | Turn each confirmed protection into an executable test from a fixed template. |
| FR-6 | Run security analysis in a sandbox (static, API, runtime, RLS, dependency/config). |
| FR-7 | Auditor agent finds access-control and wiring bugs with a real proof per finding. |
| FR-8 | Fixer agent proposes patches on a branch; accepted only after the verification gate passes. |
| FR-9 | Condense code (dead code, duplicates, optional agent simplification) behind the same gate. |
| FR-10 | On every new version re-test new code, previously fixed vulnerabilities and previously working protections. |
| FR-11 | Detect PASS to FAIL regressions; identify the first failed version and the associated commit. |
| FR-12 | Track code-size and quality drift per version. |
| FR-13 | Store history and every agent step; show them in the dashboard. |
| FR-14 | Model-agnostic: swap the model through an adapter (Ollama default). |

## 8. Non-functional requirements
- **Runs on a 16GB laptop** (Lenovo IdeaPad Slim 3 class, CPU only): one job and one sandbox at a time.
- **Sandbox safety:** imported code is untrusted and runs only in isolated containers.
- **Reproducibility:** PASS/FAIL comes from tests, never from a model.
- **Explainability:** every finding, regression and optimization has evidence and an agent trace.
- **Bounded agents:** step, time and cost limits on every run.

## 9. Success metrics (targets, to be validated)
- Seeded regressions detected (recall) and false alarms (precision).
- First-failed-version accuracy.
- Findings proven by the Auditor vs findings from Semgrep alone.
- Fix success rate (patch passes the gate) per model.
- Lines reduced with **zero** protection or behaviour breaks.
- Time per run on the target laptop.

## 10. Assumptions and constraints
- The platform sees only **source code and git history**, not the original prompts.
- A developer is available to confirm protections.
- The app can be built and run in Docker with a seeded test database.
- Small local models are weaker than hosted ones; results will be reported honestly.

## 11. Risks
| Risk | Mitigation |
|---|---|
| Small local model gives poor fixes | Gate rejects bad output; narrow tasks; compare models in evaluation |
| 16GB RAM is tight | One job at a time, 3B default model, WSL2 memory cap, recorded replies |
| Auto-building arbitrary apps fails | One stack, apps we control, ERROR state |
| Refactoring breaks security | Verification gate; protections are the safety net |
| Scope too large | MVP cut line in plan.md |
| Existing tools already cover part of it | Related-work experiment; position as complement |

## 12. Open questions
- Final list and wording of the 15 files.
- Which apps will be used for evaluation.
- Which model sizes the laptop can really sustain.
