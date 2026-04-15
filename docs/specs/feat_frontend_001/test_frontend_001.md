# Test Spec: Frontend scaffold and hello-world page

## Testing Posture for This Feature

**This feature ships with no automated tests.** That is a deliberate choice, not an oversight:

- The user has explicitly rejected adding any flavor of frontend test (unit, component, integration, end-to-end, snapshot, Vitest, Playwright, Cypress, Testing Library) to `feat_frontend_001`. Adding any of these would expand scope and lock the template into a test toolchain before the testing feature is designed.
- The cross-cutting test harness for this template is owned by `feat_testing_001` and is, per the user's pre-approved plan, **REST-only against the running stack**. It exercises the backend's HTTP contract (including `GET /api/v1/hello`) directly. Because the frontend's only contract with the rest of the system is "call `/api/v1/hello` and render the response," the REST-level coverage in `feat_testing_001` is what indirectly guards the contract this frontend depends on.
- No frontend-side test framework, runner, or fixture infrastructure is introduced by this feature. Adding one later is a separate, explicit feature decision (likely a `feat_testing_NNN` or a `feat_frontend_NNN` follow-up) and would update `conventions.md` §9 if the choice locks in a tool.

Therefore the sections below describe **manual verification steps** that Vulcan (and a human reviewer) should execute before declaring `feat_frontend_001` done. They are not automated test cases. Vulcan must not invent component tests, install Vitest, add a `tests/` directory under `frontend/`, or wire Playwright. If any of those appear in the build PR, the PR should be rejected.

## What `feat_testing_001` Will Cover (For Reference)

When `feat_testing_001` lands, its REST suite is expected to assert at minimum:

- `GET /api/v1/hello` returns HTTP 200 with a JSON body matching the `HelloResponse` shape (`message`, `item_name`, `hello_count`).
- `hello_count` is a non-negative integer and increments across successive calls (Redis round-trip works).
- `item_name` is the seeded value (Postgres round-trip works).
- The error envelope shape (`{"error": {"code", "message", "request_id"}}`) is returned for failure modes.

Those assertions are the ground truth that the frontend's typed `HelloResponse` and its rendering logic depend on. If any of them break, the frontend's success view will misrender, and the REST suite will catch the regression at the source.

## Manual Verification Checklist (For Vulcan and Reviewer)

### Happy Path

| # | Step | Expected Outcome |
|---|---|---|
| 1 | From repo root: `cd frontend && bun install`. | Completes without errors; `node_modules/` populated; no lockfile churn (i.e. `bun.lockb` does not change after install). |
| 2 | Start the backend per `backend/README.md` so `http://localhost:8000/api/v1/hello` returns 200. Then in a second terminal: `cd frontend && bun run dev`. | Vite dev server starts (default `http://localhost:5173`) with no errors. |
| 3 | Open `http://localhost:5173/` in a browser. | Page first shows the loading state, then transitions to the success view, displaying at least the backend's `message` field. |
| 4 | Reload the page several times. | Each reload re-fetches; if `hello_count` is rendered, it increments by 1 each time. |
| 5 | From repo root: `cd frontend && bun run build`. | Build completes with zero TypeScript errors and produces `frontend/dist/`. |
| 6 | `cd frontend && bun run preview`. | Preview server serves the built bundle; opening it in a browser shows the same hello page behavior as step 3 (assuming the proxy/env target is reachable). |

### Error / Degraded Cases

| # | Step | Expected Outcome |
|---|---|---|
| 1 | Stop the backend, then load `http://localhost:5173/`. | Page renders a visible, human-readable error state (e.g. "Failed to load: ..."). No blank screen, no uncaught exception in the browser console beyond the expected fetch failure. |
| 2 | Restart the backend in a state where the seed row is missing (the `/api/v1/hello` handler returns HTTP 503 — see `backend/app/api/v1/hello.py`). | Page renders the error state; the rendered message includes enough information (e.g. the HTTP status) for a developer to know what to fix. |
| 3 | Set `VITE_API_BASE_URL` to a clearly wrong value (e.g. `http://localhost:9999`) and run `bun run dev`. | The Vite proxy fails to forward; the page renders the error state without crashing. |
| 4 | Delete `frontend/.env` (if present), keep `.env.example`, and run `bun run dev`. | App still works against the default proxy target (`http://localhost:8000`) because the API client uses a relative URL and the proxy default-targets the backend. |

### Boundary / Convention Checks

| # | Check | Expected |
|---|---|---|
| 1 | `frontend/bun.lockb` is committed in the build PR. | Present in `git status`; not gitignored. |
| 2 | `frontend/.gitignore` excludes `node_modules/`, `dist/`, and `.env`. | These paths do not appear in `git status` after a fresh `bun install` and `bun run build`. |
| 3 | `frontend/.env` is NOT committed; `frontend/.env.example` IS committed. | `git ls-files frontend/.env` is empty; `git ls-files frontend/.env.example` lists the file. |
| 4 | The page component (`src/App.tsx`) does not call `fetch` directly. | `grep -n "fetch(" frontend/src/App.tsx` returns no matches; all HTTP goes through `src/api/client.ts`. |
| 5 | `HelloResponse` is defined exactly once. | `grep -rn "interface HelloResponse\|type HelloResponse" frontend/src` returns one definition, in `src/api/client.ts`. |
| 6 | No backend files are touched by this feature's PR. | `git diff --name-only origin/main...HEAD` shows changes only under `frontend/`. |
| 7 | No test framework is added. | `frontend/package.json` does not depend on `vitest`, `@testing-library/*`, `playwright`, `cypress`, `jest`, `mocha`, etc. No `tests/` or `__tests__/` directory exists under `frontend/`. |
| 8 | TypeScript strict mode is on. | `frontend/tsconfig.app.json` (or equivalent) has `"strict": true`. |

### Security Considerations

This feature has a small attack surface — it is a single GET against an endpoint that takes no input — so the security checklist is short:

- **No secrets in env files.** `frontend/.env.example` contains only the public backend base URL. `.env` (if a developer creates one) is gitignored. Document in the README that anything truly secret must NOT live in a `VITE_*` variable, since `VITE_*` vars are inlined into the client bundle and visible to anyone who loads the page.
- **Render all backend strings as plain text.** The success view renders `data.message` (and optionally `data.item_name`, `data.hello_count`) using React's default text-node rendering, which HTML-escapes the content. The error view renders the `Error.message` string the same way. Vulcan must not introduce any raw-HTML-injection escape hatch (such as React's `dangerously*` props) in either render path; if rich rendering is ever needed later, route untrusted strings through a vetted sanitizer library first.
- **No auth headers, no cookies, no credentials.** The fetch call uses default credentials mode (`same-origin`), which under the Vite proxy means no cookies are forwarded cross-origin and no `Authorization` header is added. This is correct for the current scope.
- **Error rendering does not leak stack traces.** The error view shows the `Error.message` string only, not the full `Error.stack`. This avoids inadvertently surfacing implementation paths to a viewer.
- **Dependency surface is minimal.** Only the Vite + React baseline (plus `@types/*`). Vulcan should not add transient dependencies beyond what `bun create vite --template react-ts` ships.
