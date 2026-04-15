# Feature: Project Conventions, Spec Scaffolding, License, and README

## Problem Statement

This repository is a greenfield template intended to be reused (via GitHub "Use this template") to bootstrap new minimalist web applications. Before any backend, frontend, or infrastructure code is written, the repository needs a shared source of truth for:

- Naming conventions (feature IDs, spec file names, branch names, commit prefixes, PR titles, labels)
- Directory layout for specs and future source folders
- Status conventions used by the Atlas/Vulcan AutoDev workflow
- A permissive open-source license so downstream users know their rights
- A top-level README explaining what the template is, how it is organized, and how future features will be added

Without these, every subsequent feature (backend, frontend, infra, testing) would invent its own conventions ad hoc, leading to drift. This feature establishes those conventions *first* so features 2-5 can reference and comply with them.

This is the bootstrap feature of the AutoDev workflow on this template: it produces the very `conventions.md` that Atlas is instructed to read at the start of every session.

## Requirements

- Create `conventions.md` at the repository root documenting:
  - Feature ID format: `feat_<domain>_<NNN>` with approved initial domains (`conventions`, `backend`, `frontend`, `infra`, `testing`) and how to add new ones
  - Spec file naming: `feat_<domain>_<NNN>.md`, `design_<domain>_<NNN>.md`, `test_<domain>_<NNN>.md` under `docs/specs/<feat_id>/`
  - Branch naming: `spec/<feat_id>` for Atlas, `build/<feat_id>` for Vulcan
  - Commit message prefix: `autodev(<feat_id>): <description>`
  - PR title format: `spec(<feat_id>): <title>` and `build(<feat_id>): <title>`
  - GitHub label conventions: every AutoDev issue/PR gets `autodev` plus `<feat_id>`
  - Status conventions for features (Planned / In Spec / Ready / In Build / Merged)
  - Monorepo directory layout (`backend/`, `frontend/`, `infra/`, `tests/`, `docs/`, `deployment/`)
  - Language/tooling choices locked in by this template (Python via `uv`, JS via `bun`, Postgres, Redis, FastAPI, Vite+React+TS, docker-compose)
- Create `docs/specs/README.md` explaining the spec directory layout and how to read a feature
- Create `LICENSE` at the repository root containing the standard MIT License text, copyright year `2026`, copyright holder `Sri Harsha`
- Replace the current one-line `README.md` with a proper top-level README covering:
  - What the template is and what stack it provides
  - High-level directory layout (marking folders that will be added by later features as "added by feat_backend_001" etc.)
  - How to use the template (GitHub "Use this template" button, then customize)
  - Pointer to `conventions.md` and `docs/specs/`
  - License note pointing to `LICENSE`
- Preserve the existing `docs/specs/` directory (already created by this feature's spec commit) — do not delete it

## User Stories

- As a developer opening this template for the first time, I want a single `conventions.md` so I know the naming and workflow rules before I touch anything.
- As Atlas (planner agent), I want `conventions.md` to exist so I can read it at session start as instructed by my system prompt.
- As Vulcan (builder agent), I want the spec directory layout codified so I know where to find feature/design/test specs for any feature ID.
- As a user of the template, I want a MIT `LICENSE` and a real `README.md` so the repo is immediately usable and legally clear when I click "Use this template".
- As a reviewer of future PRs, I want label and branch conventions documented so I can filter and triage consistently.

## Scope

### In Scope

- `conventions.md` at repo root
- `LICENSE` at repo root (MIT, 2026, Sri Harsha)
- `README.md` at repo root (full rewrite of the current one-line stub)
- `docs/specs/README.md` (spec-directory guide)
- Leaving `docs/specs/feat_conventions_001/` populated with its own three spec files (this PR)

### Out of Scope

- Any source code (no `backend/`, `frontend/`, `infra/` folders created here — each is produced by its own feature)
- Any Dockerfiles or docker-compose setup (owned by `feat_infra_001`)
- Any linting, formatting, or pre-commit configuration (deferred to a future feature per user decision)
- Any test infrastructure or `test.sh` (owned by `feat_testing_001`)
- CODE_OF_CONDUCT, CONTRIBUTING, SECURITY, or other community health files (can be a later feature if desired)
- CI/CD workflows under `.github/workflows/` (out of scope for this feature; may be part of `feat_infra_001` or a later feature)

## Acceptance Criteria

- [ ] `conventions.md` exists at the repo root and documents all items listed under Requirements
- [ ] `LICENSE` exists at the repo root, contains the standard MIT License text, shows `Copyright (c) 2026 Sri Harsha`
- [ ] `README.md` at the repo root is more than one line and covers stack, layout, usage, and license pointer
- [ ] `docs/specs/README.md` exists and explains the spec directory layout
- [ ] `docs/specs/feat_conventions_001/` contains `feat_conventions_001.md`, `design_conventions_001.md`, `test_conventions_001.md`
- [ ] A GitHub issue titled `Implement feat_conventions_001: <short title>` exists with labels `autodev` and `feat_conventions_001`
- [ ] A spec PR titled `spec(feat_conventions_001): <short title>` exists against `main`
- [ ] `conventions.md` explicitly lists the 5 approved initial feature IDs (`feat_conventions_001`, `feat_backend_001`, `feat_frontend_001`, `feat_infra_001`, `feat_testing_001`) and their rough scope so future Atlas sessions have context
