# Specs

This directory holds the design history of every feature in the repository. Each feature lives in its own subfolder and contains exactly three markdown files — a feature spec, a design spec, and a test spec. Reading the three files in order gives you the full picture of why a feature exists, how it is built, and how it is verified.

## Subfolder per feature

Every feature gets its own subfolder named after its feature ID:

```
docs/specs/
  feat_conventions_001/
    feat_conventions_001.md     # what and why
    design_conventions_001.md   # how
    test_conventions_001.md     # how do we know it works
  feat_backend_001/             # (added by feat_backend_001)
    ...
```

The subfolder name matches the feature ID exactly (`feat_<domain>_<NNN>`). Inside it, the three files follow the same `<domain>_<NNN>` suffix so they are unambiguous when opened out of context.

## The three-file convention

| File                                  | Purpose                                                         |
|---------------------------------------|-----------------------------------------------------------------|
| `feat_<domain>_<NNN>.md`              | Problem statement, requirements, scope, acceptance criteria.    |
| `design_<domain>_<NNN>.md`            | Approach, files to create/modify, data flow, edge cases, risks. |
| `test_<domain>_<NNN>.md`              | Happy path, error cases, boundary conditions, security notes.   |

Files are authored by **Atlas** during the spec phase and merged via a `spec(<feat_id>)` PR before **Vulcan** begins implementation. Merged specs are treated as historical artifacts: if a spec needs to change later, open a new conventions/spec PR rather than silently rewriting the file.

## Full rules

The full ruleset for feature IDs, branch names, commit prefixes, PR titles, labels, and status lifecycle lives in the repository root [`conventions.md`](../../conventions.md). Consult it when you are unsure whether a name, branch, or label is correct.

## Feature roster

| Feature ID              | Status     | One-line scope                                                              |
|-------------------------|------------|-----------------------------------------------------------------------------|
| `feat_conventions_001`  | In Build   | Conventions, `LICENSE`, top-level `README.md`, and this spec guide.         |
| `feat_backend_001`      | Planned    | FastAPI app skeleton, `uv` project, Postgres + Redis wiring, first endpoint.|
| `feat_frontend_001`     | Planned    | Vite + React + TypeScript app skeleton managed with `bun`.                  |
| `feat_infra_001`        | Planned    | Dockerfiles, `docker-compose.yml`, `.env` templates, local orchestration.   |
| `feat_testing_001`      | Planned    | `test.sh` driver, test conventions, minimal backend + frontend test examples.|
| `feat_backend_002`      | In Build   | Backend rules (`backend/RULES.md`), logging callsite + redaction, items domain move. |
| `feat_auth_001`         | In Build   | Auth foundation: users/roles/identities schema, Redis sessions, `SessionMiddleware`, `/auth/me`, `/auth/logout`. |
| `feat_auth_002`         | Merged     | Email OTP login: `EmailSender` abstraction, `/auth/otp/request` + `/auth/otp/verify`, Resend provider, deployment docs. |
| `feat_frontend_002`     | In Spec    | Login UI: `AuthContext`, `/login` OTP page with disabled Google-coming-soon button, authed dashboard + header strip, Playwright e2e suite. |

Future features append rows to this table as they are planned.
