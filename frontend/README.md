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
  .env.example               # VITE_API_BASE_URL default
  .gitignore                 # Ignores node_modules/, dist/, .env (not .env.example, not bun.lockb)
  src/
    main.tsx                 # React entry point
    App.tsx                  # Hello page (loading / error / success)
    App.css
    index.css
    vite-env.d.ts            # ImportMetaEnv augmentation for VITE_API_BASE_URL
    api/
      client.ts              # Typed getHello() + HelloResponse type
```
