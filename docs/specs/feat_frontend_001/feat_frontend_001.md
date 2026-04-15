# Feature: Frontend scaffold and hello-world page

## Problem Statement

The repo has a working FastAPI backend (`feat_backend_001`) exposing `GET /api/v1/hello`, but no client. To complete the minimalist full-stack template, we need a small, conventional Vite + React + TypeScript application that:

1. Demonstrates the canonical way to scaffold a frontend in this repo (so future features have a pattern to copy).
2. Calls the backend's hello endpoint and renders the response, proving end-to-end connectivity for whoever clones the template.
3. Is managed entirely with `bun` for installs and scripts (per `conventions.md` §9), while leaving the Vite dev server and bundling on Node where they belong.

Without this, the template has a backend that nothing visibly consumes, and there is no precedent established for how a UI lives next to the backend in this monorepo.

## Requirements

- A `frontend/` directory at the monorepo root, sibling to `backend/`.
- A standard Vite + React + TypeScript scaffold managed with `bun`. The `bun.lockb` lockfile is committed.
- A single page that, on mount, calls `GET /api/v1/hello` and renders the response payload.
- Three rendering states are handled: loading, error, and success.
- The base URL of the backend is configurable via the Vite env var `VITE_API_BASE_URL`, defaulting to `http://localhost:8000` in local development. A `frontend/.env.example` ships this default.
- A small typed API-client module (e.g. `src/api/client.ts`) exports a typed `getHello()` function; the response type lives alongside it. The page imports from this module rather than calling `fetch` inline.
- A short `frontend/README.md` documents `bun install`, `bun run dev`, `bun run build`, and the `VITE_API_BASE_URL` env var.
- A `frontend/.gitignore` covers Node/Vite/Bun artifacts (`node_modules/`, `dist/`, `.env`, etc.) — but the lockfile (`bun.lockb`) is **not** ignored.

## User Stories

- As a developer cloning this template, I want to run `bun install && bun run dev` inside `frontend/` and immediately see a page that talks to my local backend, so I know the full stack is wired up.
- As the author of a future frontend feature, I want a minimal but conventional Vite + React + TypeScript layout to copy from, so I do not have to reinvent project structure or rediscover how `bun` and Vite cooperate.
- As an operator, I want to point the frontend at a non-default backend URL via a single env var, so I can run the UI against staging or a docker-compose stack later without code changes.

## Scope

### In Scope

- Vite + React + TypeScript scaffold under `frontend/`.
- Bun-driven install and script lifecycle (`bun install`, `bun run dev`, `bun run build`, `bun run preview`).
- One page (the default route — no router) that calls the backend's `/api/v1/hello` and renders loading, error, and success states.
- A typed API-client module wrapping `fetch`, with a typed response model that mirrors the backend's `HelloResponse` schema (`message`, `item_name`, `hello_count`).
- `frontend/.env.example` declaring `VITE_API_BASE_URL=http://localhost:8000`.
- `frontend/README.md` covering install, dev, build, env var, and how the dev server reaches the backend.
- `frontend/.gitignore` for the frontend subtree.

### Out of Scope

- Routing libraries (React Router, TanStack Router, etc.) — single page only.
- State management libraries (Redux, Zustand, Jotai, React Query, etc.) — `useState` + `useEffect` is sufficient.
- UI component frameworks or design systems (MUI, Chakra, shadcn, Tailwind, etc.). Default Vite styling is fine; minor inline or CSS-module styling for legibility is acceptable.
- Authentication, sessions, cookies, or auth headers.
- Docker images, `Dockerfile`, or `docker-compose` integration — owned by `feat_infra_001`.
- All forms of frontend testing (unit, component, integration, e2e, Playwright, Vitest). Explicitly deferred; see the test spec.
- Linting/formatting beyond what the Vite TypeScript template ships with by default. Custom ESLint/Prettier configuration is a separate future feature.
- CI/CD or GitHub Actions wiring.
- Backend CORS configuration. The frontend will reach the backend via Vite's dev-server proxy (see design spec), so no backend change is required for `feat_frontend_001`.
- Production hosting / deploy artifacts.

## Acceptance Criteria

- [ ] `frontend/` exists at the repo root, sibling to `backend/`.
- [ ] `frontend/package.json` declares Vite + React + TypeScript dependencies and `dev`, `build`, `preview` scripts.
- [ ] `bun install` (run inside `frontend/`) succeeds against the committed `bun.lockb` with no network surprises.
- [ ] `bun run build` (run inside `frontend/`) completes successfully with zero TypeScript errors.
- [ ] With the backend running locally on `http://localhost:8000`, `bun run dev` serves the UI and the page successfully fetches and renders the `/api/v1/hello` payload (showing at least the `message` field).
- [ ] When the backend is not reachable, the page renders a visible, human-readable error state (not a blank screen, not a raw stack trace).
- [ ] While the request is in flight, the page renders a visible loading state.
- [ ] The API call goes through the typed client module; the page component does not call `fetch` directly.
- [ ] `frontend/.env.example` exists and declares `VITE_API_BASE_URL=http://localhost:8000`.
- [ ] `frontend/README.md` documents install, dev, build, and the env var.
- [ ] `frontend/.gitignore` excludes `node_modules/`, `dist/`, and `.env` (but not `.env.example` or `bun.lockb`).
- [ ] `bun.lockb` is committed.
- [ ] No changes are made outside `frontend/` (no backend edits, no top-level config edits).
