# Project Conventions

This document is the single source of truth for naming, paths, and workflow conventions in this repository. It is read by humans when navigating the repo and by the **Atlas** (planner) and **Vulcan** (builder) agents at the start of every session. If you are adding a new feature, branch, commit, PR, or label, it must conform to the rules here. If a rule needs to change, update this file in a dedicated PR before applying the new rule elsewhere.

## 1. Feature IDs

Every unit of work is identified by a **Feature ID** of the form:

```
feat_<domain>_<NNN>
```

- `<domain>` is a short lowercase token naming the area of the codebase the feature touches.
- `<NNN>` is a three-digit, zero-padded, monotonically increasing counter **per domain** (so `feat_backend_001`, `feat_backend_002`, ...). Counters do not reset across domains and do not share a pool.

### Approved initial domains

| Domain        | Scope                                                                    |
|---------------|--------------------------------------------------------------------------|
| `conventions` | Repo-wide conventions, licensing, top-level docs, spec scaffolding.      |
| `backend`     | Python service (FastAPI), database models, migrations, server code.     |
| `frontend`    | Web UI (Vite + React + TypeScript).                                      |
| `infra`       | Docker images, `docker-compose`, local orchestration, environment files. |
| `testing`     | Test harness (`test.sh`), test tooling, cross-cutting test utilities.    |

### Adding a new domain

Adding a new domain (e.g., `auth`, `mobile`, `cli`) requires **explicit human approval**. Atlas must propose the new domain in a planning session and wait for the human to confirm before using it in a feature ID. Once approved, the domain is added to the table above in a `feat_conventions_NNN` follow-up PR.

## 2. Spec files

Every feature has exactly three spec files, all under a per-feature directory:

```
docs/specs/<feat_id>/
  feat_<domain>_<NNN>.md     # Feature spec: problem, requirements, scope, acceptance criteria
  design_<domain>_<NNN>.md   # Design spec: approach, files to create/modify, data flow, risks
  test_<domain>_<NNN>.md     # Test spec:   happy path, error cases, boundary conditions, security
```

The feature spec answers "what and why," the design spec answers "how," and the test spec answers "how do we know it works."

A guide to reading specs end-to-end lives in [`docs/specs/README.md`](docs/specs/README.md).

## 3. Branches

All work happens on short-lived branches cut from fresh `main`:

| Branch            | Owner  | Purpose                                                     |
|-------------------|--------|-------------------------------------------------------------|
| `spec/<feat_id>`  | Atlas  | Holds the three spec files and the GitHub issue reference. |
| `build/<feat_id>` | Vulcan | Holds the implementation: source code, tests, doc updates. |

- Always branch from an up-to-date `main` (`git checkout main && git pull --ff-only && git checkout -b <branch>`).
- One branch per feature per agent. Do not reuse a spec branch for implementation; cut a new `build/<feat_id>` from fresh `main` after the spec PR is merged.
- Branches are deleted after their PR is merged.

## 4. Commits

Every commit message uses the prefix:

```
autodev(<feat_id>): <description>
```

- `<description>` is a short imperative phrase in lowercase (e.g., `add conventions, license, and readme`).
- Keep commits focused; prefer several small commits over one large one when the changes are logically separate.
- Do not include `Co-Authored-By` lines unless the human explicitly asks for them.

## 5. Pull requests

Exactly one PR per branch, always targeting `main`:

| PR kind         | Title format                        | Branch             |
|-----------------|-------------------------------------|--------------------|
| Spec PR         | `spec(<feat_id>): <short title>`    | `spec/<feat_id>`   |
| Build PR        | `build(<feat_id>): <short title>`   | `build/<feat_id>`  |

PR bodies should:

- Link the GitHub issue with `Closes #<n>`.
- Reference the three spec files by path.
- Summarize the diff at a level a reviewer can skim.

## 6. Labels

Every AutoDev issue and PR receives **two labels**:

- `autodev` — marks the item as owned by the AutoDev workflow.
- `<feat_id>` — the per-feature label (e.g., `feat_conventions_001`).

The `autodev` label is created once (manually or by the first Atlas run). The per-feature label is created by Atlas the first time it is needed; subsequent issues/PRs for the same feature reuse it. Colors are not significant but should be distinct enough to skim in the GitHub UI.

## 7. Status vocabulary

Features move through a small, strict lifecycle. The current status of every feature lives in `docs/tracking/features.md` (created when tracking is needed) or in the GitHub issue labels.

| Status     | Meaning                                                                             |
|------------|-------------------------------------------------------------------------------------|
| `Planned`  | Feature ID is reserved; no specs yet. Listed in the roster for visibility.          |
| `In Spec`  | Atlas is writing (or revising) the three spec files; spec PR may be open.           |
| `Ready`    | Spec PR merged to `main`; specs are final; Vulcan can pick it up.                   |
| `In Build` | Vulcan is implementing; build branch exists; build PR may be open.                  |
| `Merged`   | Build PR merged to `main`; feature is live.                                         |

A feature only advances; it does not skip states. If a spec needs to change after `Ready`, open a new `spec/<feat_id>_revN` branch or a new conventions-style fix PR — do not silently edit merged specs.

## 8. Directory layout

The target monorepo layout is:

| Path           | Contents                                                              | Introduced by        |
|----------------|-----------------------------------------------------------------------|----------------------|
| `backend/`     | FastAPI service, models, migrations, Python packages.                 | `feat_backend_001`   |
| `frontend/`    | Vite + React + TypeScript web app.                                    | `feat_frontend_001`  |
| `infra/`       | Dockerfiles, `docker-compose.yml`, env templates, local orchestration.| `feat_infra_001`     |
| `tests/`       | Cross-cutting tests and the `test.sh` driver.                          | `feat_testing_001`   |
| `docs/`        | Specs (`docs/specs/`), tracking, ADRs, narrative docs.                | `feat_conventions_001` (this feature) |
| `deployment/`  | Production deployment artifacts (Helm charts, Terraform, etc.).        | a later infra feature |

Empty placeholder folders are **not** committed by this feature; each folder is created when the feature that owns it lands.

## 9. Locked tech stack

The following choices are fixed for this template. A change to any of them requires a `feat_conventions_NNN` PR that updates this file first.

| Area                         | Choice                                                        |
|------------------------------|---------------------------------------------------------------|
| Backend language             | Python                                                        |
| Python package/project tool  | `uv`                                                          |
| Backend web framework        | FastAPI                                                       |
| Relational database          | Postgres                                                      |
| Cache / key-value store      | Redis                                                         |
| Frontend build tool          | Vite                                                          |
| Frontend framework           | React                                                         |
| Frontend language            | TypeScript                                                    |
| JS package manager / runner  | `bun` (package manager + script runner; Vite handles the dev server and bundling on Node) |
| Local orchestration          | `docker-compose`                                              |
| Container runtime / images   | Docker                                                        |

Specific versions of `uv`, `bun`, Python, Node, Postgres, and Redis are **not** pinned here — each is pinned by the feature that introduces the corresponding tool.

## 10. Initial feature roster

The five bootstrap features of this template:

| Feature ID              | Scope (one line)                                                            |
|-------------------------|-----------------------------------------------------------------------------|
| `feat_conventions_001`  | This file, `LICENSE`, top-level `README.md`, `docs/specs/README.md`.        |
| `feat_backend_001`      | FastAPI app skeleton, `uv` project, Postgres + Redis wiring, first endpoint.|
| `feat_frontend_001`     | Vite + React + TypeScript app skeleton managed with `bun`.                  |
| `feat_infra_001`        | Dockerfiles, `docker-compose.yml`, `.env` templates, local orchestration.   |
| `feat_testing_001`      | `test.sh` driver, test conventions, minimal backend+frontend test examples. |

## 11. Deferred (intentionally out of scope for now)

These are **not** folded into the five bootstrap features. They may land as future `feat_conventions_NNN` or domain-specific features.

- Linting and formatting configuration (e.g., `ruff`, `eslint`, `prettier`).
- Pre-commit hooks (`.pre-commit-config.yaml`).
- CI/CD workflows (`.github/workflows/`).
- Community-health files (`CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`, `SECURITY.md`).
- Top-level `.gitignore` with common entries (each domain feature contributes ignores for its area).
- Dependabot or Renovate configuration.

Anyone tempted to bolt one of these onto an in-flight feature: don't. Propose a new feature instead.
