# Design: Frontend scaffold and hello-world page

## Approach

Stand up a stock Vite + React + TypeScript project in `frontend/`, managed by `bun` for installs and scripts. Keep the structure as close to `bun create vite frontend --template react-ts` output as possible so the scaffold is recognizable to anyone who has used Vite before. Then add three small things on top of that scaffold:

1. A typed API-client module (`src/api/client.ts`) wrapping `fetch`, exporting a typed `getHello()` function and the `HelloResponse` type.
2. A replacement `App.tsx` that mounts, calls `getHello()`, and renders one of three states: loading, error, success.
3. Configuration: `.env.example` declaring `VITE_API_BASE_URL`, and a Vite dev-server proxy entry so calls to `/api/...` in development are forwarded to the backend (sidestepping CORS without any backend change).

The `bun.lockb` lockfile is committed so subsequent `bun install` calls are reproducible. The Vite dev server, esbuild, and the production build still execute on Node — Bun is the package manager and script runner only, per `conventions.md` §9.

Bun version: pin to a specific minor (e.g. `>=1.1.0`) in `package.json#packageManager` if Bun supports it for this template, or document the minimum version in `frontend/README.md`. Vulcan should pick the current stable Bun at implementation time and document the chosen version.

Node engine: the Vite scaffold typically targets Node `>=20.19` for Vite 7 / Node `>=20` for Vite 6. Vulcan should defer to whatever the chosen Vite template requires and reflect the minimum in `frontend/package.json#engines.node` and the README.

## Files to Modify

| File | Change Description |
|---|---|
| (none) | This feature does not modify any existing files. All changes are additive under `frontend/`. |

## Files to Create

| File | Purpose |
|---|---|
| `frontend/package.json` | Project manifest. Declares Vite, React, React-DOM, TypeScript, `@types/react`, `@types/react-dom`, `@vitejs/plugin-react`. Scripts: `dev` (`vite`), `build` (`tsc -b && vite build`), `preview` (`vite preview`). |
| `frontend/bun.lockb` | Bun lockfile produced by `bun install`. Committed for reproducibility. |
| `frontend/tsconfig.json` | TypeScript root config (typically references `tsconfig.app.json` and `tsconfig.node.json` per the Vite template). |
| `frontend/tsconfig.app.json` | App-side TS config (DOM lib, JSX, strict mode on). |
| `frontend/tsconfig.node.json` | Vite-config TS settings (Node env). |
| `frontend/vite.config.ts` | Vite config: `@vitejs/plugin-react`, plus `server.proxy` mapping `/api` -> `${VITE_API_BASE_URL}` so dev-mode calls bypass CORS. |
| `frontend/index.html` | Vite entry HTML; mounts `#root` and loads `/src/main.tsx`. |
| `frontend/src/main.tsx` | React entry. Renders `<App />` into `#root`. Standard Vite scaffold output. |
| `frontend/src/App.tsx` | The hello-world page. Uses `useState` + `useEffect` to call `getHello()` and render loading / error / success. |
| `frontend/src/App.css` | Minimal styling for legibility. Optional but typical in Vite scaffolds. |
| `frontend/src/index.css` | Global styles (default Vite scaffold). |
| `frontend/src/api/client.ts` | Typed API client. Exports `HelloResponse` type and `async function getHello(): Promise<HelloResponse>`. |
| `frontend/src/vite-env.d.ts` | Vite-supplied type shim plus `ImportMetaEnv` augmentation declaring `VITE_API_BASE_URL: string`. |
| `frontend/.env.example` | `VITE_API_BASE_URL=http://localhost:8000`. |
| `frontend/.gitignore` | `node_modules/`, `dist/`, `.env`, `.env.local`, `*.log`, etc. Does NOT ignore `bun.lockb` or `.env.example`. |
| `frontend/README.md` | One-screen doc covering prerequisites (Bun + Node versions), `bun install`, `bun run dev`, `bun run build`, `bun run preview`, and the `VITE_API_BASE_URL` env var. |
| `frontend/public/` (optional) | Static assets directory if the Vite scaffold places anything there (e.g. a favicon). Acceptable to omit if the chosen template inlines the favicon. |

Vulcan may use `bun create vite frontend --template react-ts` (or the equivalent current invocation) to generate the baseline and then layer the api-client module, env-var wiring, and proxy config on top. Generated boilerplate (e.g. the default Vite splash component) should be replaced by the hello page rather than left in place.

## API Client Shape

`frontend/src/api/client.ts` exports:

```ts
export interface HelloResponse {
  message: string;
  item_name: string;
  hello_count: number;
}

export async function getHello(): Promise<HelloResponse>;
```

Implementation contract:

- The base URL is read from `import.meta.env.VITE_API_BASE_URL`. If unset, fall back to an empty string so that the path `/api/v1/hello` resolves against the current origin (which works under the Vite dev proxy without any env file).
- The request URL is `${baseUrl}/api/v1/hello`.
- A non-2xx response throws an `Error` whose message includes the HTTP status. The page surfaces this in the error state.
- A network failure (fetch rejection) propagates as an `Error` with a useful message; the page surfaces it likewise.
- The function does not retry, does not cache, does not set auth headers. Keep it boring.

The `HelloResponse` type intentionally mirrors the backend's `app.schemas.HelloResponse` (`message: str`, `item_name: str`, `hello_count: int`). If the backend contract drifts, this file is the single point of update on the frontend.

## Page Behavior

`frontend/src/App.tsx`:

- On mount (in a `useEffect`), call `getHello()`.
- Track three pieces of state: `data: HelloResponse | null`, `error: string | null`, `loading: boolean`.
- Render exactly one of:
  - Loading: a visible "Loading..." indicator.
  - Error: a visible message such as "Failed to load: \<error message\>" — never a blank screen, never a raw stack trace beyond the error's `message` string.
  - Success: render at minimum `data.message`. Rendering the additional fields (`item_name`, `hello_count`) is encouraged so the user can confirm Postgres + Redis are also live.
- No automatic refetch, polling, or refresh button is required. Page reload is sufficient for a re-fetch.

## Env Var Handling

- Vite exposes only env vars prefixed with `VITE_` to client code via `import.meta.env`.
- `VITE_API_BASE_URL` is the single env var this feature defines.
- `frontend/.env.example` ships `VITE_API_BASE_URL=http://localhost:8000` so a developer can `cp .env.example .env` and immediately have a working setup.
- `frontend/src/vite-env.d.ts` augments `ImportMetaEnv` with `readonly VITE_API_BASE_URL: string` so TypeScript users get autocomplete and type-checking on the var.
- Document in the README that env vars are baked in at build time, not read at runtime — a production build needs the env var present during `bun run build`, not when the static bundle is served.

## CORS / Dev Server Strategy

The backend (`feat_backend_001`) does not currently install `CORSMiddleware`. Rather than modify the backend (out of scope for this feature), the Vite dev server proxies API calls to it:

```ts
// vite.config.ts
server: {
  proxy: {
    '/api': {
      target: process.env.VITE_API_BASE_URL ?? 'http://localhost:8000',
      changeOrigin: true,
    },
  },
},
```

With the proxy in place, the frontend can issue same-origin requests to `/api/v1/hello` from `http://localhost:5173` and the dev server forwards to `http://localhost:8000`. No browser CORS preflight occurs.

For production-style serving via `bun run preview`, the same proxy applies. For a fully built static bundle served from elsewhere (a future concern, not this feature's), the operator either fronts everything behind a single reverse proxy or the backend gains CORS — both options are deferred.

## Build + Dev Workflow

| Command (run inside `frontend/`) | Purpose |
|---|---|
| `bun install` | Installs dependencies into `node_modules/` using `bun.lockb`. |
| `bun run dev` | Starts the Vite dev server (default port 5173) with HMR and the `/api` proxy. |
| `bun run build` | Type-checks (`tsc -b`) and produces a production bundle in `dist/`. |
| `bun run preview` | Serves the built `dist/` over a local static server for sanity checks. |

Vulcan should verify, before committing, that `bun install` from a clean `node_modules/` succeeds and that `bun run build` produces `dist/` with zero TypeScript errors. (Manual verification only — no automated tests are added, per the test spec.)

## Data Flow

1. User loads `http://localhost:5173/` in the browser.
2. React mounts `<App />`. `useState` initializes `loading=true`, `data=null`, `error=null`. The page renders the loading state.
3. `useEffect` fires once; it invokes `getHello()` from `src/api/client.ts`.
4. `getHello()` issues `fetch('/api/v1/hello')` (relative path; same-origin under the Vite dev proxy).
5. The Vite dev server receives the request, matches the `/api` proxy rule, and forwards to `http://localhost:8000/api/v1/hello`.
6. FastAPI executes the hello handler (round-tripping Postgres and Redis) and returns the JSON `HelloResponse`.
7. `getHello()` resolves with the typed response. `App` updates state to `loading=false`, `data=<response>`, and re-renders the success view.
8. If step 4–7 fail at any point, `getHello()` throws; `App` updates to `loading=false`, `error=<message>`, and re-renders the error view.

## Edge Cases & Risks

| Risk | Mitigation |
|---|---|
| Backend not running when the user opens the page. | Page renders a clear error state with the underlying fetch/network error message. |
| Backend returns 503 (e.g. seed item missing — see `backend/app/api/v1/hello.py`). | API client throws on non-2xx; page renders the status code in the error message so the user knows what to fix. |
| Backend response shape drifts from `HelloResponse`. | Type lives in one file (`src/api/client.ts`); update there. No runtime schema validation is added (out of scope; can be revisited if drift becomes painful). |
| User forgets to copy `.env.example` to `.env`. | Defaults are designed so this works anyway: the API client falls back to a relative URL, and the Vite proxy default-targets `http://localhost:8000`. The README still recommends copying the file for clarity. |
| Browser CORS blocks the request. | Avoided by routing through the Vite dev-server proxy in development. Production CORS is explicitly deferred. |
| Port collision: backend already on 8000, Vite default 5173. | Both default ports are unchanged from upstream defaults; if the user has a conflict, Vite auto-increments to 5174 and the proxy still works. Backend port collision is outside the frontend's concern. |
| `bun.lockb` is a binary file — non-Bun users (e.g. someone running `npm install` by mistake) will get a different resolution. | Convention is documented in `conventions.md` §9 (Bun is the chosen package manager) and reiterated in `frontend/README.md`. We do not add a `package-lock.json` or `yarn.lock`. |
| Bun and Node version drift across contributors' machines. | Document a minimum Bun version and a minimum Node version in `frontend/README.md` and (where supported) in `package.json#engines`. |
| Future Docker build (`feat_infra_001`) needs the same `VITE_API_BASE_URL` machinery. | Env-var contract is intentionally one variable, prefixed `VITE_`, so the Docker build stage can pass it via `--build-arg` / `ENV` without redesign. |

## Dependencies

- **Runtime (bundled):** `react`, `react-dom`.
- **Build / dev:** `vite`, `@vitejs/plugin-react`, `typescript`, `@types/react`, `@types/react-dom`. Exact versions are picked by Vulcan from the current stable `bun create vite --template react-ts` output and pinned via `bun.lockb`.
- **Tooling on the host machine:** `bun` (package manager + script runner) and `node` (Vite dev server + bundler runtime). Versions documented in `frontend/README.md`.
- **External services consumed at runtime:** the backend from `feat_backend_001` (specifically `GET /api/v1/hello`, plus its dependencies on Postgres and Redis to serve a 200).
- No new top-level repo dependencies. No backend changes.
