# Features

Priority: **MVP** = must have, **SHOULD** = after the core works, **STRETCH** = only if time allows.

| ID | Feature | Priority | Done when |
|---|---|---|---|
| F-01 | Import app (GitHub / ZIP / folder) as Version 1 | MVP | App stored with commit hash and file tree |
| F-02 | Phase 0 inventory of the 15 files | SHOULD | Each file marked Found / Partial / Missing |
| F-03 | Reconstruct missing docs from code | SHOULD | Drafts marked "AI-reconstructed, unverified" |
| F-04 | Verify existing docs against code | SHOULD | Claims marked Verified / Outdated / Conflicting / Undocumented |
| F-05 | Application Model (page, API, route, auth, table, RLS) | MVP | Graph stored; broken links listed |
| F-06 | Candidate protections + developer confirmation | MVP | Confirmed protections stored with a test template |
| F-07 | Executable protection tests (ownership, unauthenticated, role, RLS, validation) | MVP | Each returns PASS / FAIL / ERROR with evidence |
| F-08 | Sandbox runner (Docker, Postgres + PostgREST, seeded users) | MVP | App builds and runs; tests execute isolated |
| F-09 | Own agent runtime (loop, limits, logging) | MVP | An agent completes a task using tools and stops safely |
| F-10 | Tool registry (typed, sandboxed, least privilege) | MVP | Tools callable and unit-tested without a model |
| F-11 | Model adapter (Ollama default, optional hosted) | MVP | Model switched by one setting |
| F-12 | Auditor agent (hypothesis, real request, proof) | MVP | Finding saved only with proof |
| F-13 | Fixer agent + verification gate | MVP | Patch accepted only if the gate passes (max 3 tries) |
| F-14 | Security scans (Semgrep, npm audit, secret scan) | SHOULD | Findings merged with severity and evidence |
| F-15 | GitHub webhook creates new version | MVP | Push triggers a run |
| F-16 | Change and impact analysis | MVP | Affected protections selected (or run all) |
| F-17 | Regression detection (PASS to FAIL), first failed version | MVP | Report names version, commit, evidence |
| F-18 | Bisect across multiple commits (Sentinel) | SHOULD | Exact first failing commit found |
| F-19 | Condense: dead code and duplicates | SHOULD | Lines removed, gate passes |
| F-20 | Condense: agent simplification of single units | STRETCH | Smaller code, gate passes |
| F-21 | Memory: protection history, past fixes, security notes | SHOULD | Agents retrieve relevant entries |
| F-22 | Dashboard: matrix, regression reports, diffs, agent trace | MVP | All viewable |
| F-23 | Quality trend per version | SHOULD | Lines and complexity chart |
| F-24 | Strix as optional extra scanner | STRETCH | Its findings enter the same list |
| F-25 | Doc drift check per version | STRETCH | Outdated docs flagged |
| F-26 | MCP server | STRETCH | See mcp.md |
| F-27 | Fine-tuned small model for one narrow job | STRETCH | Measured gain over the base model |

## Rules for every feature
- PASS/FAIL comes from a test, never from a model.
- Nothing merges without developer approval.
- Every result stores its evidence and agent trace.
