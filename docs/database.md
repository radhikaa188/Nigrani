# Database

PostgreSQL (Supabase free tier or local Postgres). IDs are UUIDs; all tables have `created_at`. Large blobs (snapshots, logs) live on disk or object storage; the database stores references.

## Relationships
```
users 1-N projects 1-N versions 1-N runs 1-N agent_steps
versions 1-N documents 1-N doc_claims
projects 1-N protections 1-N protection_results (per version/run)
runs 1-N findings 1-N fixes
runs 1-N optimizations
versions 1-1 quality_metrics, 1-1 app_models
projects 1-N regressions
kb_chunks (memory, shared or per project)
```

## Tables
**users**: id, email, role (`owner`/`viewer`).

**projects**: id, owner_id, name, source_type (`github`/`zip`/`folder`), source_ref, stack, default_branch, webhook_secret.

**versions**: id, project_id, number, commit_hash, parent_version_id, trigger (`import`/`webhook`/`manual`), snapshot_ref.

**runs**: id, version_id, type (`baseline`/`monitor`/`fix`/`condense`), status (`queued`/`running`/`done`/`failed`), model (name and adapter), started_at, finished_at, error.

**agent_steps**: id, run_id, agent (`mapper`/`auditor`/`fixer`/`optimizer`/`sentinel`/`orchestrator`), step_no, kind (`model_call`/`tool_call`/`observation`), name, input (JSONB), output (JSONB), duration_ms, tokens_in, tokens_out, status. This is the replayable agent trace.

**app_models**: id, version_id, graph (JSONB nodes and edges: page, api_call, route, auth_check, table, rls_policy, function), broken_links (JSONB).

**documents**: id, version_id, name (one of the 15), status (`found`/`partial`/`missing`), origin (`existing`/`reconstructed`), trust (`unverified`/`verified`/`confirmed`), content_ref.

**doc_claims**: id, document_id, claim_text, code_ref, status (`verified`/`outdated`/`conflicting`/`undocumented`), resolution (`code_right`/`doc_right`/null).

**protections**: id, project_id, code (P-01...), description, related_node_ids (JSONB), test_template (`ownership`/`unauthenticated`/`role`/`rls`/`validation`), test_params (JSONB), state (`candidate`/`confirmed`/`rejected`), source (`rule`/`model`/`developer`), confirmed_by, confirmed_at.

**protection_results**: id, protection_id, version_id, run_id, status (`PASS`/`FAIL`/`ERROR`/`SKIPPED`), evidence (JSONB: request, response, log excerpt), duration_ms. Unique on (protection_id, run_id).

**findings**: id, run_id, version_id, source (`auditor`/`semgrep`/`dependency`/`secret`/`strix`/`protection_test`), title, severity, component, evidence (JSONB), repro_test_ref, state (`open`/`fixed`/`accepted_risk`).

**fixes**: id, finding_id, branch, patch_ref, attempts, gate_result (JSONB), state (`proposed`/`accepted`/`rejected`), approved_by.

**optimizations**: id, run_id, kind (`dead_code`/`duplicate`/`agent_simplify`), files (JSONB), lines_before, lines_after, gate_result (JSONB), state, commit_hash.

**quality_metrics**: id, version_id, total_lines, duplicate_blocks, dead_code_items, avg_complexity, largest_file_lines, per_file (JSONB).

**regressions**: id, project_id, protection_id, previous_version_id, current_version_id, first_failed_version_id, suspect_commit, associated_feature, evidence (JSONB), state (`open`/`fixed`/`dismissed`).

**kb_chunks** (agent memory): id, project_id (nullable), source (`owasp`/`cwe`/`supabase_rls`/`past_fix`/`note`), text, tags, embedding (vector, optional later).

## Rules
- A regression is created only when the previous result is `PASS` and the current is `FAIL`. `ERROR` never creates one.
- Fixed vulnerabilities keep `repro_test_ref` so they are re-tested every version.
- Versions are immutable; new work creates a new version.
- Row-level security on every table; users see only their own projects.

## Indexes
`versions(project_id, number)`, `protection_results(protection_id, version_id)`, `findings(run_id)`, `regressions(project_id, state)`, `agent_steps(run_id, step_no)`.
