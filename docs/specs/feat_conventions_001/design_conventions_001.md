# Design: Project Conventions, Spec Scaffolding, License, and README

## Approach

This is a documentation-only feature. No source code, no build tooling, no runtime artifacts. Vulcan creates four markdown files and one `LICENSE` file at fixed, well-known paths. Content is static and self-contained — no templating, no code generation.

The feature is intentionally sequenced first so that `conventions.md` exists before any subsequent feature (`feat_backend_001`, `feat_frontend_001`, `feat_infra_001`, `feat_testing_001`) is planned or built. Atlas reads `conventions.md` at the start of every session per its system prompt; this feature produces that file.

The top-level `README.md` is rewritten from its current one-line stub. Later features (`feat_backend_001`, etc.) will extend it with setup/run instructions for the components they add; this feature only establishes the skeleton and the "what is this template" framing.

## Files to Modify

| File | Change Description |
|---|---|
| `README.md` | Replace the existing one-line `# minimalist-app` stub with a full top-level README covering stack, layout, usage, license pointer. Mark folders that later features will add (e.g., "`backend/` — added by `feat_backend_001`"). |

## Files to Create

| File | Purpose |
|---|---|
| `conventions.md` | Single source of truth for naming, paths, branch/commit/PR/label conventions, status vocabulary, directory layout, and the locked-in tech stack. Read by Atlas at the start of every session. |
| `LICENSE` | Standard MIT License text. Copyright line: `Copyright (c) 2026 Sri Harsha`. |
| `docs/specs/README.md` | Explains the `docs/specs/` directory layout (one subfolder per feature, three spec files per feature, naming conventions) and how to read a feature end-to-end. |
| `docs/specs/feat_conventions_001/feat_conventions_001.md` | This feature's feature spec (created by Atlas on the spec branch; listed here for completeness). |
| `docs/specs/feat_conventions_001/design_conventions_001.md` | This design document (created by Atlas on the spec branch). |
| `docs/specs/feat_conventions_001/test_conventions_001.md` | This feature's test spec (created by Atlas on the spec branch). |

Note: the three files under `docs/specs/feat_conventions_001/` are authored by Atlas during spec creation and are already present when Vulcan begins. Vulcan does not create them; Vulcan's job for this feature is to create `conventions.md`, `LICENSE`, `docs/specs/README.md`, and rewrite `README.md`.

## Data Flow

There is no runtime data flow — this feature produces static documentation. The *workflow* flow is:

1. Atlas creates the three spec files under `docs/specs/feat_conventions_001/` on branch `spec/feat_conventions_001`, opens a spec PR, creates a GitHub issue with labels `autodev` + `feat_conventions_001`.
2. Human merges the spec PR into `main`.
3. Vulcan picks up the issue, branches `build/feat_conventions_001` from fresh `main`, creates `conventions.md`, `LICENSE`, `docs/specs/README.md`, rewrites `README.md`, commits, pushes, opens a build PR.
4. Human reviews and merges the build PR. From this point forward, every Atlas session reads `conventions.md` before proposing new work.

## Content Outlines

Vulcan should follow these outlines when authoring the files.

### `conventions.md` outline

1. Introduction — one paragraph on what this document is and who reads it (humans + Atlas + Vulcan).
2. Feature IDs — format `feat_<domain>_<NNN>`; approved initial domains: `conventions`, `backend`, `frontend`, `infra`, `testing`; rule for adding new domains (human approval required); `NNN` is zero-padded and monotonically increasing per domain.
3. Spec files — path `docs/specs/<feat_id>/`, three files: `feat_<domain>_<NNN>.md`, `design_<domain>_<NNN>.md`, `test_<domain>_<NNN>.md`.
4. Branches — `spec/<feat_id>` for Atlas, `build/<feat_id>` for Vulcan, always branched from fresh `main`.
5. Commits — prefix `autodev(<feat_id>): <description>`, imperative mood, lowercase description.
6. PR titles — `spec(<feat_id>): <short title>` and `build(<feat_id>): <short title>`; one PR per branch; always target `main`.
7. Labels — every AutoDev issue/PR gets `autodev` plus the per-feature label `<feat_id>`; Atlas creates the per-feature label if it does not exist.
8. Status vocabulary — Planned / In Spec / Ready / In Build / Merged (and what each means).
9. Directory layout — table showing `backend/`, `frontend/`, `infra/`, `tests/`, `docs/`, `deployment/`, noting which feature adds each.
10. Locked tech stack — Python via `uv`, JS package manager `bun` (package manager + script runner only; Vite handles dev server and bundling on Node), Postgres, Redis, FastAPI, Vite + React + TypeScript, docker-compose for local orchestration, Docker for images.
11. Initial feature roster — the five approved feature IDs with one-line scope each.
12. "Deferred" list — linting/code quality, CI/CD, community health files; noted as future features so no one is tempted to fold them into an existing feature.

### `LICENSE` content

Standard MIT License text, verbatim from https://opensource.org/license/mit. Copyright line exactly: `Copyright (c) 2026 Sri Harsha`.

### `README.md` outline

1. Title and one-paragraph description: "A minimalist web application template with FastAPI backend, React+TypeScript frontend, Postgres, and Redis, orchestrated via docker-compose."
2. "Use this template" section pointing to the GitHub button.
3. Tech stack bullet list (FastAPI, uv, SQLAlchemy, Alembic, Postgres, Redis, structlog, Vite, React, TypeScript, Bun, docker-compose).
4. Directory layout block (showing planned structure, with notes that `backend/`, `frontend/`, `infra/`, `tests/`, `deployment/` are added by later features).
5. Getting started (placeholder section; later features will fill in `make up` / `bun run dev` once those exist — for now, note "setup instructions will be added when the backend/frontend/infra features land").
6. Workflow pointer — "This template uses the AutoDev workflow (Atlas + Vulcan). See `conventions.md` and `docs/specs/`."
7. License — one-liner pointing at `LICENSE`.

### `docs/specs/README.md` outline

1. One-paragraph description of what lives in this directory.
2. Subfolder-per-feature rule with example `feat_conventions_001/`.
3. The three-file convention.
4. Pointer back to root `conventions.md` for full rules.
5. A table listing all features in this repo (initially just `feat_conventions_001`); future features append rows.

## Edge Cases & Risks

| Risk | Mitigation |
|---|---|
| Vulcan might re-create the spec files in `docs/specs/feat_conventions_001/` even though Atlas already committed them | Design spec explicitly lists those three spec files as "already present — Vulcan does not create them". Test spec asserts their existing content is unchanged. |
| Future features might drift from the conventions established here | `conventions.md` is read by Atlas at session start per its system prompt; spec PRs that violate it will be caught in human review. |
| MIT license boilerplate is frequently mangled (wrong year, missing permission notice) | Test spec requires exact header `Copyright (c) 2026 Sri Harsha` and presence of the phrase `THE SOFTWARE IS PROVIDED "AS IS"` to confirm the warranty clause. |
| README might over-promise features that don't exist yet (backend, frontend, compose) | Design spec says the README explicitly labels later-feature folders as "added by feat_xxx_NNN", and the Getting Started section is a placeholder. |
| Linting/code-quality concerns creep into this feature | Out-of-scope list in feature spec explicitly defers them. |
| Developer adds a new domain (e.g., `feat_auth_001`) without approval | `conventions.md` states new domains require human approval; Atlas's workflow already requires human confirmation of feature IDs. |

## Dependencies

- GitHub CLI (`gh`) — already used by Atlas for issue/label/PR creation; no new dependency for the build side.
- No runtime dependencies, no packages, no services.

## Out-of-Band Notes for Vulcan

- Do not add a `.gitignore` in this feature — the repo already has none, and each later feature will contribute ignores specific to its area (e.g., `feat_backend_001` adds Python ignores). A top-level `.gitignore` with common entries can be a separate future feature if desired.
- Do not create empty placeholder folders (`backend/`, `frontend/`, etc.) in this feature. Empty folders require `.gitkeep` tricks and muddy later features' diffs.
- Do not pin versions of `uv`, `bun`, Python, Node, Postgres, or Redis in `conventions.md`. Version pinning is the domain of the feature that introduces each tool.
