# Skills library

Short knowledge files that agents load when they need expert guidance on one topic. They give small local models the security knowledge they lack.

Skills are **our own text**, written and reviewed by us, so they are trusted instructions. Code and documents from imported apps are never skills; they are data.

## Rules
- One topic per file, 300 to 600 words (small models have short memory).
- Plain language, same section layout every time (below).
- Linked to catalog checks by ID.
- Versioned in git; update the skill when a check changes.
- Loaded with `load_skill(name)`; load at most two per model call.
- Strix's `skills/` folder is useful to see which topics to cover. Do not copy its text, and check its license first.

## Format
```
# Skill: <name>
Covers: <catalog check IDs>
## When to use
## What to check
## How to detect (static patterns and live probes)
## How to prove (what request, what response)
## How to fix (React + Supabase patterns)
## Common mistakes and false positives
```

## Planned skills
| Skill | Covers | Status |
|---|---|---|
| access-control | AC | Sample written |
| authentication-and-passwords | AU, PW | Planned |
| crypto-and-hashing | PW | Planned |
| sessions-jwt | SJ | Planned |
| injection | IN | Planned |
| xss-and-csrf | XS | Planned |
| api-security | API | Planned |
| database-and-rls | DB | Planned |
| secrets-and-config | SC, XS-04 | Planned |
| headers-cors-transport | HD | Planned |
| dependencies-supply-chain | DP | Planned |
| file-upload-ssrf | FU | Planned |
| logging-and-errors | ER | Planned |
| fix-patterns-react-supabase | all fixes | Planned |
| condense-safely | Optimizer | Planned |

First six to write (Stage 7B): access-control, authentication-and-passwords, crypto-and-hashing, sessions-jwt, injection, xss-and-csrf.
