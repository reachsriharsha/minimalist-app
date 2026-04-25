# frontend

Vite + React + TypeScript client for `minimalist-app`. This package is the web
UI that calls the FastAPI backend (`../backend`) and renders the response.

Per `conventions.md` section 9 the project is managed with **Bun** for installs
and scripts; the dev server and bundler still run on **Node** via Vite.

## Prerequisites

| Tool | Minimum version | Notes |
|---|---|---|
| [Bun](https://bun.sh) | 1.1.0 (tested on 1.3.x) | Package manager + script runner. Pinned via `package.json#packageManager`. |
| [Node.js](https://nodejs.org) | 20.19.0 | Vite 6 dev server and bundler. |

The committed `bun.lock` (text-format lockfile, default since Bun 1.2)
guarantees reproducible installs across contributors. Do **not** create a
`package-lock.json` or `yarn.lock` here.

## Getting started

```bash
cd frontend
cp .env.example .env        # optional; defaults also work
bun install
bun run dev
```

Then open <http://localhost:5173/> in a browser. The page will call
`GET /api/v1/hello` on the backend and render the payload.

To see the full end-to-end success state you need the backend running on
`http://localhost:8000` (see `../backend/README.md`). If the backend is not
reachable the page renders a visible error message -- it will not crash or
render a blank screen.

## Scripts

| Command | Purpose |
|---|---|
| `bun install` | Install dependencies into `node_modules/` using the committed lockfile. |
| `bun run dev` | Start the Vite dev server (default port 5173) with HMR and the `/api` proxy. |
| `bun run build` | Type-check (`tsc -b`) and produce a production bundle in `dist/`. |
| `bun run preview` | Serve the built `dist/` locally for sanity checks. |
| `bun run test:e2e` | Run the Playwright e2e suite (`login.spec.ts` + `profile.spec.ts`) against the compose stack (requires `make up` first; see [Testing](#testing)). |

A thin `start.sh` wrapper mirrors `backend/start.sh` and dispatches to the same
commands, so local and (later) containerized entrypoints stay aligned:

```bash
./start.sh              # dev server (default)
./start.sh build        # production build
./start.sh preview      # serve the built bundle
./start.sh install      # bun install against the committed lockfile
INSTALL=1 ./start.sh    # run bun install before dev/build/preview
```

`HOST`, `PORT`, and `VITE_API_BASE_URL` are honored as environment variables.

## Environment variables

The project uses exactly one env var:

| Variable | Default | Purpose |
|---|---|---|
| `VITE_API_BASE_URL` | `http://localhost:8000` (via `.env.example` / the Vite dev proxy fallback) | Base URL of the backend API. |

Notes:

- Vite only exposes env vars prefixed with `VITE_` to client code via
  `import.meta.env`. Variables are **baked in at build time**, not read at
  runtime -- a production `bun run build` needs the env var present during
  the build, not when the static bundle is served.
- In development the Vite dev server proxies requests to `/api/*` to
  `VITE_API_BASE_URL`, so the browser speaks to the same origin as the dev
  server and no CORS preflight is required.
- Do **not** put secrets in any `VITE_*` variable -- they are inlined into the
  client bundle and visible to anyone who loads the page.

## Project layout

```
frontend/
  index.html                 # Vite entry HTML
  package.json               # Scripts + dependencies
  bun.lock                   # Committed lockfile (Bun >=1.2 text format)
  start.sh                   # Entrypoint wrapper mirroring backend/start.sh
  tsconfig.json              # References the two configs below
  tsconfig.app.json          # App-side TS config (strict mode on)
  tsconfig.node.json         # TS config for vite.config.ts itself
  vite.config.ts             # Vite + React plugin + /api proxy
  playwright.config.ts       # Playwright e2e config (feat_frontend_002)
  .env.example               # VITE_API_BASE_URL default
  .gitignore                 # Ignores node_modules/, dist/, .env, test-results/, playwright-report/
  src/
    main.tsx                 # React entry point (BrowserRouter + AuthProvider)
    App.tsx                  # Routing root (/login public, / authed)
    App.css
    index.css
    vite-env.d.ts            # ImportMetaEnv augmentation for VITE_API_BASE_URL
    api/
      client.ts              # Typed getHello() + HelloResponse type
      auth.ts                # getMe(), logout(), requestOtp(), verifyOtp() + Me type
    auth/
      AuthContext.tsx        # {user, status, refresh, logout} provider + useAuth()
      RequireAuth.tsx        # Route gate (loading / redirect / render)
    components/
      AuthedLayout.tsx       # Header + <main> wrapper for authed routes
      Header.tsx              # Email + role chips + logout button
      HelloPanel.tsx         # Extracted hello widget (rendered in Dashboard)
    pages/
      LoginPage.tsx          # /login — two-step OTP form
      Dashboard.tsx          # / — greeting + roles + HelloPanel
      ProfilePage.tsx        # /profile — email-only page (feat_frontend_003)
  tests/
    e2e/
      fixtures.ts            # getOtpFixture() — reads TEST_OTP_EMAIL/CODE
      login.spec.ts          # End-to-end login flow + relative-URL invariant
      profile.spec.ts        # /profile route + header Profile button (feat_frontend_003)
```

## Testing

### End-to-end (Playwright)

`feat_frontend_002` introduced the Playwright e2e suite that drives a real
browser against the compose stack; `feat_frontend_003` extends it with a
profile-page spec. The suite currently runs `login.spec.ts` and
`profile.spec.ts`. It is **not** part of `./test.sh` — it runs via a separate
`bun run test:e2e` invocation, mirroring how the external REST suite under
`tests/` is invoked.

One-time setup per machine:

```bash
cd frontend
bun install
bunx playwright install chromium
```

Set the test OTP fixture (consumed both by the backend when `ENV=test` and by
the Playwright runner itself). Edit `infra/.env`:

```ini
ENV=test
TEST_OTP_EMAIL=e2e@example.com
TEST_OTP_CODE=424242
```

Then start the stack and run the suite:

```bash
# from repo root
make up

# in another shell, export the same pair so the runner sees them too
export TEST_OTP_EMAIL=e2e@example.com
export TEST_OTP_CODE=424242

cd frontend
bun run test:e2e
```

When either env var is unset, the suite prints a clean skip and exits 0 —
mirroring the behavior of `tests/tests/test_auth.py`. See
[`docs/deployment/email-otp-setup.md#e2e-smoke-test`](../docs/deployment/email-otp-setup.md#e2e-smoke-test)
for the full operator flow including prod-profile overrides.

> Playwright is intentionally a **dev dependency only** in `package.json`. The
> production bundle has no knowledge of the test runner or its browsers.
