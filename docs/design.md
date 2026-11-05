# Design (Dashboard UX)

## Principles
1. **Evidence first.** Every status shows its proof one click away.
2. **Human approves.** Fixes and condensing appear as diffs; nothing merges without a click.
3. **Plain language.** "User B could open User A's note", not "BOLA".
4. **Calm by default.** Show what needs attention (regressions, conflicts); hide the rest.
5. **Show the agents.** Any agent result can be traced step by step.

## Screens
| Screen | What the user sees | Main actions |
|---|---|---|
| Projects | List with latest version, open regressions, size trend | New project, open |
| Import | GitHub URL, ZIP upload or folder | Start import |
| Readiness (Phase 0) | The 15 files (Found / Partial / Missing); claims (Verified / Outdated / Conflicting / Undocumented) | Resolve conflict, generate missing |
| App Map (Phase 1) | Graph: page, API, route, auth check, table, RLS; broken links highlighted | Click a node for code |
| Protections (Phase 2) | Candidate and confirmed rules with test and linked nodes | Confirm, edit, reject, add |
| Findings and Fixes (Phase 3) | Findings by severity with proof; fix diff; gate checklist | Approve, reject |
| Condense (Phase 3) | Before/after lines per change; gate result | Approve, reject |
| History matrix (Phase 4) | Rows = protections, columns = versions, cells PASS / FAIL / ERROR | Click a cell for evidence |
| Regression report | What broke, version, suspect commit and feature, evidence | Mark fixed, dismiss |
| Quality trend | Lines and complexity per version | Compare versions |
| **Agent trace** | Timeline of model calls, tool calls and observations for a run | Expand a step, copy, replay |
| Run log and settings | Status, errors, model choice, limits | Retry, cancel, change model |

## Key components
- **Matrix cell:** colour plus text, never colour alone.
- **Evidence drawer:** request, response, log excerpt, test definition.
- **Diff viewer:** side by side with the gate checklist (build, behaviour, protections, size).
- **Run progress:** step list with live status; clear message when a local model is slow.

## States to design
Empty project, running, failed run, ERROR result ("test could not run, not a regression"), no regressions (positive message), model not running ("start Ollama").

## Tech
React + Vite, TypeScript, Tailwind, Recharts, React Flow (App Map), a diff component (react-diff-viewer).
