# Security Catalog

The master list of every security check the platform knows. It drives the **Security Coverage Report**.

**The platform never says an app is "completely secure."** No tool can prove that. It says exactly what was checked, what passed, what failed, and what was not checked.

## How to read
- **Method:** S = static rule (Semgrep/AST), L = live test in the sandbox, D = dependency or secret tool, C = config check, M = manual review item.
- **Tier:** 1 = target for the MVP, built in batches (see `tracker.md`, Stage 6B). 2 = after Tier 1 works (Stage 12B). 3 = limited or manual; kept so the report is honest about gaps.
- **Status:** Planned / Implemented / Manual. Update this column as checks are built.
- **Applies when:** some checks apply only if a feature exists (uploads, GraphQL, payments, LLM features). Otherwise the result is N/A.
- Every **Implemented** check needs a vulnerable fixture and a safe fixture (see `testing.md`).
- CWE and OWASP references are from memory. Verify them against the official lists before quoting them in the report.

## Result states per check
`PASS`, `FAIL`, `ERROR` (could not run), `SKIPPED` (not run in this scan mode), `N/A` (feature absent), `MANUAL` (needs a human).

## Coverage Report (example)
```
Scan mode: standard    Version: V3
Applicable checks: 52   Passed: 41   Failed: 5   Error: 1   Manual: 5
Not implemented yet (Tier 2 and 3): 48
Failed: AC-02 (IDOR on /notes/:id), HD-02 (no CSP), ...
This report lists what was checked. It does not mean the app is free of vulnerabilities.
```

## Scan modes
| Mode | Runs | Needs model | Use |
|---|---|---|---|
| quick | S, D, C methods only | No | Fast first look; low RAM |
| standard (default) | quick + L methods + Auditor with a step limit | Yes | Normal scan |
| deep | All tiers, bigger Auditor budget | Yes | Final scan before evaluation |

## Catalog

### AC: Access control
| ID | Check | Method | Tier | Reference |
|---|---|---|---|---|
| AC-01 | Protected routes require authentication | L, S | 1 | CWE-306, API2 |
| AC-02 | Object-level access: user B cannot read or change user A's data (IDOR/BOLA) | L | 1 | CWE-639, API1 |
| AC-03 | Function-level access: normal user cannot reach admin functions | L | 1 | CWE-862, API5 |
| AC-04 | Property-level access: users cannot read or set protected fields (for example `role`, `is_admin`) | L | 1 | CWE-915, API3 |
| AC-05 | Authorization enforced on the server, not only hidden in the UI | S, L | 1 | CWE-602 |
| AC-06 | Direct database or REST access does not bypass app rules | L | 1 | CWE-284 |
| AC-07 | Privilege escalation through parameter tampering | L | 2 | CWE-269 |
| AC-08 | No open redirects | S, L | 2 | CWE-601 |

### AU: Authentication
| ID | Check | Method | Tier | Reference |
|---|---|---|---|---|
| AU-01 | Login brute-force protection (rate limit or lockout) | L | 1 | CWE-307 |
| AU-02 | No user enumeration through login or reset responses | L | 2 | CWE-204 |
| AU-03 | Password reset tokens expire, are single-use and unguessable | S, L | 2 | CWE-640 |
| AU-04 | Password policy enforced on the server | S, L | 2 | CWE-521 |
| AU-05 | Account takeover paths (email change, verification) | M | 3 | |
| AU-06 | No default or test credentials in code | S | 1 | CWE-798 |
| AU-07 | MFA available for admin accounts | M | 3 | |

### PW: Passwords and cryptography
| ID | Check | Method | Tier | Reference |
|---|---|---|---|---|
| PW-01 | Passwords are never stored in plain text | S, L | 1 | CWE-312 |
| PW-02 | Password hashing uses bcrypt, scrypt or argon2, not MD5, SHA-1 or plain SHA-256 | S | 1 | CWE-916, CWE-327 |
| PW-03 | Hashes are salted | S | 1 | CWE-759 |
| PW-04 | Secure random numbers for tokens and IDs (no `Math.random`) | S | 1 | CWE-338 |
| PW-05 | No hardcoded keys, IVs or secrets | S, D | 1 | CWE-321, CWE-798 |
| PW-06 | No broken algorithms or modes (DES, RC4, ECB) | S | 1 | CWE-327 |
| PW-07 | Sensitive data encrypted at rest where needed | M | 2 | CWE-311 |
| PW-08 | TLS used for sensitive traffic | C, L | 1 | CWE-319 |

### SJ: Sessions, JWT and cookies
| ID | Check | Method | Tier | Reference |
|---|---|---|---|---|
| SJ-01 | JWT signature verified; `alg: none` rejected | S, L | 1 | CWE-347 |
| SJ-02 | No weak or default JWT secret | S, D | 1 | CWE-798 |
| SJ-03 | Token expiry and refresh handled | S, L | 1 | CWE-613 |
| SJ-04 | Sensitive tokens stored safely on the client | S | 2 | CWE-922 |
| SJ-05 | Cookie flags: Secure, HttpOnly, SameSite | L, S | 1 | CWE-614, CWE-1004, CWE-1275 |
| SJ-06 | Logout invalidates the session | L | 2 | CWE-613 |
| SJ-07 | No session fixation | L | 2 | CWE-384 |

### IN: Injection and input handling
| ID | Check | Method | Tier | Reference |
|---|---|---|---|---|
| IN-01 | No SQL injection (string-built queries) | S, L | 1 | CWE-89 |
| IN-02 | No NoSQL injection | S, L | 2 | CWE-943 |
| IN-03 | No OS command injection | S | 1 | CWE-78 |
| IN-04 | No code injection (`eval`, `Function`) | S | 1 | CWE-94 |
| IN-05 | No server-side template injection | S | 2 | CWE-1336 |
| IN-06 | Safe XML parsing (no XXE) | S | 2 | CWE-611 |
| IN-07 | No unsafe deserialization | S | 2 | CWE-502 |
| IN-08 | No prototype pollution | S | 2 | CWE-1321 |
| IN-09 | Server-side input validation present | S, L | 1 | CWE-20 |
| IN-10 | No log injection | S | 3 | CWE-117 |

### XS: Frontend
| ID | Check | Method | Tier | Reference |
|---|---|---|---|---|
| XS-01 | No XSS (`dangerouslySetInnerHTML`, `innerHTML`, unsanitized output) | S, L | 1 | CWE-79 |
| XS-02 | CSRF protection on state-changing requests | L, S | 1 | CWE-352 |
| XS-03 | Clickjacking protection (frame-ancestors or X-Frame-Options) | L | 1 | CWE-1021 |
| XS-04 | No secrets or service keys in the frontend bundle | D, S | 1 | CWE-798 |
| XS-05 | Third-party scripts loaded with integrity checks | S | 2 | CWE-829 |
| XS-06 | No sensitive data in URLs or client logs | S | 2 | CWE-200 |
| XS-07 | Source maps not exposed in production | C, L | 2 | CWE-540 |

### DB: Database (Supabase and Postgres)
| ID | Check | Method | Tier | Reference |
|---|---|---|---|---|
| DB-01 | RLS enabled on every table holding user data | S, L | 1 | CWE-284 |
| DB-02 | Policies not overly permissive (for example `using (true)`) | S | 1 | CWE-284 |
| DB-03 | RLS enforced for select, insert, update and delete | L | 1 | CWE-862 |
| DB-04 | Service-role or admin database key not used in client code | S, D | 1 | CWE-250 |
| DB-05 | Least-privilege database roles | C | 2 | CWE-250 |
| DB-06 | No sensitive columns exposed through the API (`select *`) | S, L | 2 | CWE-200 |
| DB-07 | Safe database functions (`security definer` with fixed `search_path`) | S | 2 | CWE-89 |
| DB-08 | Storage buckets and files not public unless intended | S, L | 2 | CWE-552 |
| DB-09 | No real secrets in seed data or backups | S | 3 | CWE-798 |

### SC: Secrets and configuration
| ID | Check | Method | Tier | Reference |
|---|---|---|---|---|
| SC-01 | No secrets in the repo or git history | D | 1 | CWE-798 |
| SC-02 | `.env` not committed and listed in `.gitignore` | S | 1 | CWE-540 |
| SC-03 | Debug mode and verbose errors off in production config | C, S | 1 | CWE-489 |
| SC-04 | No example or default credentials in config | S | 1 | CWE-798 |
| SC-05 | No insecure defaults (CORS `*`, open ports) | C | 1 | CWE-1188 |
| SC-06 | Dev and prod keys separated | M | 3 | |

### HD: Headers, CORS and transport
| ID | Check | Method | Tier | Reference |
|---|---|---|---|---|
| HD-01 | CORS: no `*` with credentials; explicit origins | L | 1 | CWE-942 |
| HD-02 | Content-Security-Policy present | L | 1 | CWE-693 |
| HD-03 | HSTS, X-Content-Type-Options and Referrer-Policy present | L | 1 | CWE-693 |
| HD-04 | HTTPS redirect and no mixed content | L, C | 1 | CWE-319 |
| HD-05 | No server or version leak in headers | L | 2 | CWE-200 |
| HD-06 | Sensitive responses not cached | L | 2 | CWE-525 |

### DP: Dependencies and supply chain
| ID | Check | Method | Tier | Reference |
|---|---|---|---|---|
| DP-01 | No known vulnerable dependencies | D | 1 | CWE-1395 |
| DP-02 | Lockfile present and consistent | S | 1 | |
| DP-03 | No unmaintained or deprecated packages | D | 2 | CWE-1104 |
| DP-04 | No typosquatted or suspicious packages | D | 2 | |
| DP-05 | Risky install scripts reviewed | S | 3 | |

### API: API security
| ID | Check | Method | Tier | Reference |
|---|---|---|---|---|
| API-01 | No mass assignment | L, S | 1 | CWE-915, API3 |
| API-02 | No excessive data in responses | L | 1 | CWE-200, API3 |
| API-03 | Rate limiting on sensitive endpoints | L | 1 | CWE-770, API4 |
| API-04 | No undocumented or forgotten endpoints | S, L | 2 | API9 |
| API-05 | Pagination and size limits | L | 2 | CWE-770 |
| API-06 | Unexpected HTTP methods rejected | L | 2 | |
| API-07 | Third-party API responses validated | S | 3 | API10 |
| API-08 | GraphQL: introspection and query depth limits (only if GraphQL) | L | 3 | |

### FU: Files, SSRF and paths
| ID | Check | Method | Tier | Reference |
|---|---|---|---|---|
| FU-01 | File uploads restricted by type, size and path (only if uploads exist) | S, L | 2 | CWE-434 |
| FU-02 | No path traversal | S, L | 2 | CWE-22 |
| FU-03 | No SSRF (server fetching user-supplied URLs) | S, L | 2 | CWE-918, API7 |

### ER: Errors and logging
| ID | Check | Method | Tier | Reference |
|---|---|---|---|---|
| ER-01 | No stack traces or internal errors returned to clients | L | 1 | CWE-209 |
| ER-02 | No sensitive data written to logs | S | 2 | CWE-532 |
| ER-03 | Security events logged (failed logins, access denied) | S | 3 | CWE-778 |
| ER-04 | Error paths do not leave partial or inconsistent state | M | 3 | |

### BL: Business logic
| ID | Check | Method | Tier | Reference |
|---|---|---|---|---|
| BL-01 | Race conditions on balances, stock and limits | L (limited) | 3 | CWE-362 |
| BL-02 | Price or quantity tampering | L (limited) | 3 | |
| BL-03 | Workflow bypass (skipped steps, reused coupons) | M | 3 | |
| BL-04 | Webhook signatures verified (payments and similar) | S, L | 2 | CWE-345 |

### IF: Infrastructure
| ID | Check | Method | Tier | Reference |
|---|---|---|---|---|
| IF-01 | Dockerfile hardening (non-root, pinned base image, no secrets) | C | 3 | CWE-250 |
| IF-02 | CI workflows do not leak secrets | C | 3 | |
| IF-03 | No exposed admin or debug ports | C | 3 | CWE-1188 |
| IF-04 | Cloud and storage configuration | M | 3 | |

### AI: AI features inside the imported app
| ID | Check | Method | Tier | Reference |
|---|---|---|---|---|
| AI-01 | Prompt injection cannot reach tools or private data | S, M | 3 | OWASP LLM Top 10 (prompt injection) |
| AI-02 | LLM API keys not exposed in the frontend | D, S | 1 | CWE-798 |
| AI-03 | Model output not rendered unsanitized | S | 2 | OWASP LLM Top 10 (output handling) |
| AI-04 | AI agents in the app do not have excessive permissions | M | 3 | OWASP LLM Top 10 (excessive agency) |

## Sources to build this from
OWASP Top 10, OWASP API Security Top 10, OWASP ASVS (a checklist standard) and the CWE list. Use the current editions, and cite the edition in the report.
