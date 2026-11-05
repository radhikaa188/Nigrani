# Authentication and Authorization

Two separate things: **(A)** logging into the platform, **(B)** the fake users the platform creates to test the target app.

## A. Platform login
- Supabase Auth (email and password, plus GitHub login).
- Dashboard holds the session; every API call sends the JWT as `Authorization: Bearer`.
- Backend verifies the token on every request.

| Role | Can do |
|---|---|
| owner | Everything on their own projects: import, confirm protections, approve fixes, delete |
| viewer | Read results only (supervisors, reviewers) |

Rules:
- Users see only projects they own or are invited to (enforced in the API **and** by row-level security).
- Approving a fix, optimization or protection requires `owner`.
- GitHub tokens are stored encrypted and never returned by the API.
- Webhooks are verified with the project's `webhook_secret` (HMAC) and rejected otherwise.
- Ollama listens on `127.0.0.1` only and is never exposed.
- The platform must pass its own ownership, unauthenticated and role tests (see testing.md).

## B. Test users inside the sandbox
| Identity | Purpose |
|---|---|
| User A | Owns test data |
| User B | Normal user who must not see User A's data |
| Admin | Role tests (admin-only routes) |
| Anonymous | No token, for unauthenticated tests |

Rules: accounts exist only in the throwaway test database; passwords are generated per run; credentials never leave the container; the `http_request_as` tool is the only way agents act as these users.

## Test templates that use these identities
- **Ownership:** A creates a resource, B requests it, expect denial.
- **Unauthenticated:** Anonymous requests a protected route, expect 401.
- **Role:** B requests an admin route, expect 403.
- **RLS:** query as B directly against the database, expect zero rows of A's data.
- **Validation:** malformed or malicious input, expect rejection.
