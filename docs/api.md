# Backend API

Base path `/api/v1`. JSON in and out. Auth: bearer token (see auth.md). Long jobs return `202` with a `run_id`; poll `GET /runs/{run_id}`.

Errors: `{ "error": { "code": "...", "message": "..." } }`. Pagination: `?limit=&cursor=`.

## Projects and versions
| Method | Path | Purpose |
|---|---|---|
| POST | /projects | Create project |
| GET | /projects | List mine |
| GET | /projects/{id} | Summary |
| POST | /projects/{id}/import | Import code, create Version 1, auto-generate and return server-side `webhook_secret` (start baseline run) |
| GET | /projects/{id}/versions | List versions |
| GET | /versions/{id} | Detail with metrics |
| GET | /versions/{id}/model | Application Model graph |

## Phase 0 documents
| Method | Path | Purpose |
|---|---|---|
| GET | /versions/{id}/documents | The 15 files with status and trust |
| GET | /documents/{id} | Content and claims |
| PATCH | /doc-claims/{id} | Resolve (`code_right` / `doc_right`) |
| POST | /versions/{id}/documents/reconstruct | Generate missing files (202) |

## Protections
| Method | Path | Purpose |
|---|---|---|
| GET | /projects/{id}/protections | List (filter by state) |
| POST | /projects/{id}/protections | Add manually |
| PATCH | /protections/{id} | Confirm, edit or reject |
| GET | /protections/{id}/history | Result per version |

## Runs, agents, findings, fixes
| Method | Path | Purpose |
|---|---|---|
| POST | /versions/{id}/runs | Start a run (`baseline`, `monitor`, `fix`, `condense`) (202) |
| GET | /runs/{id} | Status and summary |
| GET | /runs/{id}/steps | Agent trace (model calls, tool calls, observations) |
| POST | /runs/{id}/cancel | Stop a run |
| GET | /runs/{id}/findings | Findings with evidence |
| POST | /findings/{id}/fix | Ask the Fixer for a patch (202) |
| POST | /fixes/{id}/approve | Approve (opens branch or PR) |
| POST | /fixes/{id}/reject | Reject |
| GET | /runs/{id}/optimizations | Proposed condensing with diffs |
| POST | /optimizations/{id}/approve | Approve |

## Regressions and history
| Method | Path | Purpose |
|---|---|---|
| GET | /projects/{id}/matrix | Protection x version grid |
| GET | /projects/{id}/regressions | List |
| GET | /regressions/{id} | Full report with evidence |
| PATCH | /regressions/{id} | Mark fixed or dismissed |
| GET | /projects/{id}/quality-trend | Lines and complexity per version |

## Settings and webhooks
| Method | Path | Purpose |
|---|---|---|
| GET/PUT | /settings/model | Model adapter (`ollama` or `hosted`) and model name |
| GET | /projects/{id}/webhook-secret | Retrieve this project's existing server-generated `webhook_secret` (read-only; secrets are strictly server-generated, never client-provided) |
| POST | /projects/{id}/webhook-secret/regenerate | Rotate and return a new server-generated `webhook_secret` (no request body), invalidating the previous secret |
| POST | /webhooks/github | Push event: verify HMAC-SHA256 signature against the server-generated `webhook_secret`, create version, queue monitor run, return 202 |

## Example: regression report
```json
{
  "id": "reg_01",
  "protection": { "code": "P-01", "description": "Owner-only access to notes" },
  "previous_version": "V2", "current_version": "V3",
  "previous_status": "PASS", "current_status": "FAIL",
  "first_failed_version": "V3",
  "suspect_commit": "a1b2c3d",
  "associated_feature": "Sharing feature",
  "evidence": { "request": "GET /notes/42 as User B", "response_status": 200 }
}
```
