# Design: Login UI — AuthContext, `/login` page, dashboard, and Playwright e2e

## Approach

Layer a thin routing + auth-context shell on top of the existing Vite +
React + TypeScript scaffold. Preserve the same-origin Vite-proxy
architecture verbatim so the `HttpOnly` session cookie set by
`/otp/verify` flows automatically on subsequent `/auth/me` and
`/auth/logout` calls — no `credentials: 'include'`, no absolute URLs.

At a component level:

- `main.tsx` wraps the app in `<BrowserRouter>` and `<AuthProvider>`.
- `App.tsx` is repurposed from a standalone hello page into a **routing
  root** that renders `<Routes>`. Its old hello-page content moves into
  a small `HelloPanel` component and is included inside the new
  `Dashboard` page.
- `AuthContext` is the single source of truth for "am I signed in". It
  bootstraps by calling `GET /api/v1/auth/me` on mount. A 200 stashes
  the response; a 401 is interpreted as "anonymous"; anything else is a
  hard error. During the in-flight bootstrap the app renders a loading
  skeleton — no route redirect yet — to avoid flashing the login page
  for a logged-in user on a fresh tab.
- A `<RequireAuth>` wrapper component gates routes that need a
  principal. When `AuthContext.status === 'anonymous'`, it renders a
  `<Navigate to="/login" replace />`. When `status === 'loading'` it
  defers to the skeleton. When `status === 'authenticated'` it renders
  children.
- `/login` is public. It renders the two-step OTP form plus the
  disabled Google button. After `/auth/otp/verify` returns 200, the
  login page calls `auth.refresh()` (which re-hits `/auth/me`) and then
  `navigate('/', { replace: true })`.
- `/` is authed. It renders a `<Header>` strip plus a `<Dashboard>`
  body.

The auth API surface stays trivial — four functions over `fetch`, same
relative-URL idiom as the existing `getHello()`. Vulcan places them in
a **new sibling file `frontend/src/api/auth.ts`** rather than growing
`client.ts`, because the existing `client.ts` docstring is explicit
that it is the hello-endpoint client; mixing auth into it would muddy
that contract. Both files live in the same `frontend/src/api/`
directory and follow the same code conventions (relative URL, no auth
headers, throw-on-non-2xx with `/auth/me`'s 401 as the one deliberate
exception — see below).

Playwright is wired as a **frontend dev dependency** with its tests
under `frontend/tests/e2e/` and a `bun run test:e2e` script. It drives
the compose-stack-served frontend on port 5173 (which in turn proxies
`/api` to the backend on 8000), which mirrors how a real user uses the
app and is the same boundary the external REST suite exercises. The
spec reads `TEST_OTP_EMAIL` / `TEST_OTP_CODE` from its own process env
and `test.skip`s when either is unset, matching the pattern in
`tests/tests/test_auth.py`.

## Files to Modify

| File | Change Description |
|---|---|
| `frontend/package.json` | Add `react-router-dom@^7` under `dependencies`. Add `@playwright/test@^1` under `devDependencies`. Add a `test:e2e` script (`playwright test`). No runtime-dep bloat beyond these. |
| `frontend/src/main.tsx` | Wrap `<App />` in `<BrowserRouter>` and `<AuthProvider>`. |
| `frontend/src/App.tsx` | Replace the standalone hello-page content with a routing root: `<Routes>` listing `/login` (public) and `/` (gated via `<RequireAuth>` around `<Dashboard>`). The hello-page logic moves into `src/components/HelloPanel.tsx`. |
| `frontend/src/App.css` | Add minimal styles for the login page, header strip, and dashboard layout. Existing `.state`, `.state--loading`, `.state--error`, `.state--success` classes are reused by the hello panel. |
| `frontend/README.md` | Add a **Testing** section describing `bun run test:e2e`, `bunx playwright install`, the `TEST_OTP_*` env-var pair, and an explicit note that Playwright is **not** part of `./test.sh`. Link to the operator note on the fixture. |
| `docs/tracking/features.md` | Append the `feat_frontend_002` row. Backfill Spec PR + Issues after PR and issue creation. |
| `docs/specs/README.md` | Append a row to the feature roster table (`Status: In Spec` initially, promoted via later PRs). |
| `docs/deployment/email-otp-setup.md` *(or a new `docs/deployment/frontend-e2e.md`)* | Add an operator subsection documenting the `TEST_OTP_EMAIL` / `TEST_OTP_CODE` pair as the fixture consumed by the Playwright e2e suite. Vulcan picks one: a subsection in `email-otp-setup.md` is preferred because that doc already introduces the pair. |

## Files to Create

| File | Purpose |
|---|---|
| `frontend/src/api/auth.ts` | Typed client for the auth endpoints. Exports `getMe()`, `logout()`, `requestOtp(email)`, `verifyOtp(email, code)`, and the `Me` type. All relative URLs. `getMe()` returns `Me \| null` (null on 401); the others throw on non-2xx. |
| `frontend/src/auth/AuthContext.tsx` | The context + provider. Holds `{ user, status, refresh, logout }` where `status ∈ {'loading','authenticated','anonymous'}`. `useAuth()` hook exposes it. |
| `frontend/src/auth/RequireAuth.tsx` | Tiny wrapper that reads `useAuth()` and gates its children with either the loading skeleton, a `<Navigate to="/login" replace />`, or the children. |
| `frontend/src/components/Header.tsx` | Persistent header strip for authed pages: email + role chips + logout button. |
| `frontend/src/components/HelloPanel.tsx` | The existing `getHello()` widget extracted from `App.tsx` as a reusable panel rendered inside the dashboard. Behavior is unchanged. |
| `frontend/src/pages/LoginPage.tsx` | The `/login` route. Two-step form + disabled Google button. Owns the local step state, per-field errors, and the post-verify redirect. |
| `frontend/src/pages/Dashboard.tsx` | The `/` route for authed users. Greeting, role list, HelloPanel. |
| `frontend/playwright.config.ts` | Playwright config: `testDir: './tests/e2e'`, `baseURL: http://localhost:5173` (override via env), one Chromium project, `retries: 0` in local runs, `use.trace: 'on-first-retry'`. No `webServer` block — the operator brings the stack up via `make up` before running. |
| `frontend/tests/e2e/login.spec.ts` | The one e2e test. Skips when `TEST_OTP_EMAIL`/`TEST_OTP_CODE` are unset. Navigates to `/`, asserts redirect to `/login`, fills email, submits, fills code, submits, asserts dashboard URL, asserts email + roles in header, clicks logout, asserts back on `/login`. |
| `frontend/tests/e2e/fixtures.ts` | Exports `getOtpFixture()` that reads the two env vars and returns `{email, code} \| null`, mirroring `_otp_fixture_env()` in `tests/tests/test_auth.py`. |
| `frontend/.gitignore` (amend, not create) | Ensure `test-results/`, `playwright-report/`, `playwright/.cache/`, and `tests/e2e/.auth/` are ignored. |

## Data Flow

### Bootstrap on fresh tab / refresh

```mermaid
sequenceDiagram
    participant Browser
    participant AuthProvider
    participant API as /api/v1/auth

    Browser->>AuthProvider: mount
    AuthProvider->>AuthProvider: status = 'loading'
    AuthProvider->>API: GET /me (cookie auto-attached if present)
    alt 200 OK
        API-->>AuthProvider: {user_id, email, display_name, roles}
        AuthProvider->>AuthProvider: status = 'authenticated'; user = payload
    else 401
        API-->>AuthProvider: 401 not_authenticated
        AuthProvider->>AuthProvider: status = 'anonymous'; user = null
    else other
        API-->>AuthProvider: 5xx
        AuthProvider->>AuthProvider: status = 'anonymous' + log; user = null
    end
    AuthProvider-->>Browser: render routes
```

### Login (two-step OTP)

```mermaid
sequenceDiagram
    actor User
    participant LoginPage
    participant AuthProvider
    participant API as /api/v1/auth

    User->>LoginPage: enter email, submit
    LoginPage->>API: POST /otp/request {email}
    alt 204 No Content
        API-->>LoginPage: 204
        LoginPage->>LoginPage: step = 'verify'; clear code input
    else 429
        API-->>LoginPage: 429 {detail, retry_after}
        LoginPage->>User: show rate-limit message with retry_after
    else other
        API-->>LoginPage: error
        LoginPage->>User: show generic "try again"
    end

    User->>LoginPage: enter code, submit
    LoginPage->>API: POST /otp/verify {email, code}
    alt 200 OK
        API-->>LoginPage: 200 + Set-Cookie: session=...
        LoginPage->>AuthProvider: refresh()
        AuthProvider->>API: GET /me
        API-->>AuthProvider: 200 payload
        AuthProvider->>AuthProvider: status = 'authenticated'
        LoginPage->>Browser: navigate('/', {replace: true})
    else 400 invalid_or_expired_code
        API-->>LoginPage: 400
        LoginPage->>User: inline "code didn't work; try again or request a new one"
    end
```

### Logout

```mermaid
sequenceDiagram
    actor User
    participant Header
    participant AuthProvider
    participant API as /api/v1/auth

    User->>Header: click Logout
    Header->>AuthProvider: logout()
    AuthProvider->>API: POST /logout
    API-->>AuthProvider: 204 + cookie cleared
    AuthProvider->>AuthProvider: status = 'anonymous'; user = null
    AuthProvider->>Browser: navigate('/login', {replace: true})
```

### API-surface sketch (`frontend/src/api/auth.ts`)

```ts
export interface Me {
  user_id: number;
  email: string;
  display_name: string | null;
  roles: string[];
}

// Returns null on 401 so the provider can translate "no session" into
// 'anonymous' without treating it as an error. Any other non-2xx is
// an error.
export async function getMe(): Promise<Me | null> { /* ... */ }

export async function logout(): Promise<void> { /* POST /api/v1/auth/logout */ }

export async function requestOtp(email: string): Promise<void> {
  /* POST /api/v1/auth/otp/request; throws on non-204 except 429 which
     maps to a typed RateLimitError the LoginPage catches. */
}

export async function verifyOtp(email: string, code: string): Promise<Me> {
  /* POST /api/v1/auth/otp/verify; returns parsed Me on 200; throws on
     non-200 (the LoginPage maps 400 to the uniform "bad code" message). */
}
```

All four use **relative URLs** (e.g. `/api/v1/auth/me`) and **no**
`credentials` option. The session cookie rides along because the page
origin matches the API origin (same-origin via the Vite proxy in dev,
same nginx origin in `frontend-prod`).

## `AuthContext` contract (verbatim, as confirmed in the kickoff)

- On provider mount: set `status = 'loading'` and call `getMe()`.
- On 200: set `user = payload`, `status = 'authenticated'`.
- On 401 (null return): set `user = null`, `status = 'anonymous'`. Do
  **not** render an error UI; this is the unauthenticated happy path.
  Let `<RequireAuth>` decide whether to redirect.
- On any other failure: log a `console.warn`, set `status = 'anonymous'`
  (conservative — never leave a user stuck in a non-deterministic
  state).
- `refresh()` re-runs `getMe()` and updates state. Used by
  `LoginPage` after verify returns 200, and available for any future
  caller that wants to re-sync.
- `logout()` calls the API then clears in-memory state and navigates
  to `/login`. Because the cookie is `HttpOnly`, JavaScript never
  reads it — the server is the source of truth.

## Routing contract

```
<BrowserRouter>
  <AuthProvider>
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <AuthedLayout>
              <Dashboard />
            </AuthedLayout>
          </RequireAuth>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  </AuthProvider>
</BrowserRouter>
```

`<AuthedLayout>` is a tiny wrapper: `<Header />` on top, `<main>` for
children. Kept in `src/components/` (not `src/pages/`) because it's
structural. `*` catches typos and sends them through the auth gate
— no dead "404" page in this feature.

## Visual design

Intentionally bland, matching the existing dark-on-`#242424` Vite
default look. No design-system dependency. Approximate layout:

```
+---------------------------------------------+
| user@example.com   [user]   [admin]   Logout|   <- <Header>
+---------------------------------------------+
|                                             |
|  Welcome, Ada Lovelace                      |   <- greeting
|                                             |
|  Roles: user, admin                         |   <- role list
|                                             |
|  +---------------------------+              |
|  | hello panel               |              |
|  | message: hello            |              |
|  | item_name: default        |              |
|  | hello_count: 42           |              |
|  +---------------------------+              |
|                                             |
+---------------------------------------------+
```

Login page:

```
+------------- Step 1 --------------+
| Email: [____________________]     |
| [ Send code ]                     |
|                                   |
| Sign in with Google (coming soon) |   <- disabled, tooltip / aria-label
+-----------------------------------+

+------------- Step 2 --------------+
| We sent a code to ada@example.com |
| Code: [______]                    |
| [ Verify ]                        |
| (Back to email)                   |
+-----------------------------------+
```

## Disabled Google button — concrete shape

```tsx
<button
  type="button"
  disabled
  aria-disabled="true"
  title="Google sign-in coming soon"
  className="google-btn google-btn--disabled"
>
  Sign in with Google (coming soon)
</button>
```

The button is an ordinary `<button type="button" disabled>`. Disabled
buttons in HTML do not fire click handlers and do not submit forms.
No `onClick`, no `fetch`, no reference to any backend path. A native
browser tooltip (`title`) plus a visible "(coming soon)" suffix covers
affordance without adding a tooltip library.

## Playwright wiring

- **Runner location.** `frontend/tests/e2e/` keeps the test next to
  the code it exercises. Playwright respects `testDir` in the config
  regardless of package root.
- **Browsers.** Installed on-demand with `bunx playwright install`
  (one-time per machine). Documented in `frontend/README.md`. Not
  committed to the repo; binaries live under Playwright's default
  cache.
- **Target.** `baseURL: http://localhost:5173` (the Vite dev server,
  also what compose publishes). Overridable via `PLAYWRIGHT_BASE_URL`
  env var for operators running the prod-profile frontend on 8080.
- **Fixture detection.** Identical pattern to
  `tests/tests/test_auth.py::_otp_fixture_env`:

  ```ts
  // frontend/tests/e2e/fixtures.ts
  export function getOtpFixture(): { email: string; code: string } | null {
    const email = (process.env.TEST_OTP_EMAIL ?? '').trim();
    const code = (process.env.TEST_OTP_CODE ?? '').trim();
    return email && code ? { email, code } : null;
  }
  ```

  In the spec body: `test.skip(fixture === null, 'TEST_OTP_* not set')`.

- **Why not log scraping.** The fixture pair was *designed* for this:
  when the pair is set and the request email matches, `request_otp`
  overwrites the stored hash with one derived from the configured
  test code (see `backend/app/auth/router.py`, the section marked
  "Test-OTP fixture overwrite"). The e2e test exploits this exactly
  as the REST suite in `tests/tests/test_auth.py` does.
- **`test.sh` boundary.** `test.sh` is unchanged. `bun run test:e2e`
  is a separate invocation. This mirrors how `tests/` is a separate
  subtree invoked through a dedicated driver and does not get pulled
  into frontend-local workflows.

### Operator invocation contract

The documented flow in `frontend/README.md` is:

```bash
# one-time per machine
cd frontend
bun install
bunx playwright install

# set the fixture (edit infra/.env, then bring the stack up)
#   TEST_OTP_EMAIL=e2e@example.com
#   TEST_OTP_CODE=123456
# (Env is consumed by both the backend — via compose — and the
# Playwright runner. Export it in your shell before running the
# test so the runner sees it, too.)
export TEST_OTP_EMAIL=e2e@example.com
export TEST_OTP_CODE=123456

# bring the stack up (from repo root)
make up

# run the e2e suite
cd frontend
bun run test:e2e
```

## Edge Cases & Risks

| Risk | Mitigation |
|---|---|
| Users see the login form flash for an instant before `/auth/me` resolves on refresh. | Render a loading skeleton while `status === 'loading'`. `<RequireAuth>` defers to the skeleton, not to `<Navigate>`, during loading. |
| 401 from `/auth/me` is interpreted as an error, clobbering the UI. | `getMe()` returns `null` on 401 (typed as `Me \| null`). Only non-401 non-2xx throws. |
| `credentials: 'include'` introduced by accident. | Explicit in the design and the test spec. Code review must reject any diff that sets `credentials` on a `fetch` call in this feature. |
| Absolute URL (e.g. `http://localhost:8000/api/...`) sneaks in and breaks the same-origin cookie assumption. | All new callers reuse the `/api/v1/...` relative-URL pattern from `getHello`. The e2e test would fail on the dashboard render because the cookie would not attach. |
| Dashboard renders before `/auth/me` resolves after login, showing a stale loading state. | `LoginPage` calls `auth.refresh()` (awaited) **before** `navigate('/')`, so by the time the dashboard mounts, `status === 'authenticated'` and `user` is populated. |
| Rate-limit response (429) on OTP request is not surfaced to the user. | `requestOtp` parses the 429 body (`{detail, retry_after}`) and throws a typed `RateLimitError(retryAfterSeconds)`. `LoginPage` renders a user-visible "try again in N seconds" message. |
| Playwright binaries are not installed and the first run fails with an opaque error. | `frontend/README.md` documents `bunx playwright install` as a one-time setup step. The `test:e2e` script does **not** auto-install (that would silently download hundreds of MB). |
| Playwright pulls in Node types that conflict with app code. | Playwright tests live under `frontend/tests/e2e/` with their own compile unit (Playwright handles this by default). App TS config (`tsconfig.app.json`) keeps `tests/` excluded. Vulcan verifies `bun run build` still passes. |
| Google-button "coming soon" wording diverges from the final Google-OAuth feature copy. | This is cosmetic. `feat_auth_003` will replace the button wholesale — there is no contract to honor. |
| User refreshes during step 2 (post-email, pre-verify) and loses the email value. | Acceptable. The UX recovers: user clicks "back to email", re-types, re-requests, re-verifies. Persisting partial form state is out of scope. A `/login?email=...` query-param seed is also out of scope. |
| `tests/e2e/` directory confuses developers expecting unit tests. | The README section is explicit: "e2e only; no unit tests in this feature." If a unit-test harness lands later, it goes in `frontend/src/` colocated (the conventional place for Vitest), not in `frontend/tests/`. |
| The Playwright test races against `make up` readiness. | The test does not own readiness — the operator runs `make up` first, which already blocks on backend healthchecks. Playwright config has no `webServer` block, so there is nothing to race. |
| Session cookie's `SameSite=Lax` blocks the e2e test if Playwright somehow visits a cross-site origin before login. | The test only ever visits the same origin (`baseURL`). `SameSite=Lax` permits top-level navigations and same-site subrequests; this is the exact case. |

## Dependencies

- **Runtime (new):** `react-router-dom@^7`.
- **Dev (new):** `@playwright/test@^1`.
- **External tool (one-time, per-machine):** Playwright browsers
  installed via `bunx playwright install`. Not a package dependency
  — a binary download.
- **Unchanged:** the existing Vite + React + TypeScript + `@types/*`
  stack. No new Vite plugins. No new backend deps (backend is not
  touched).

## Deviations

- **Directory name has no slug.** `docs/specs/feat_frontend_002/` and
  the three filename stems use `feat_<domain>_<NNN>` only, matching
  `conventions.md` §2 and every existing sibling directory
  (`feat_auth_001`, `feat_auth_002`, `feat_frontend_001`). The kickoff
  prompt's slug-in-filename template is superseded by `conventions.md`,
  which the user's memory note names as authoritative.
- **Branch name has no slug.** `spec/feat_frontend_002`, per
  `conventions.md` §3. Same reasoning.
- **Operator doc placement is Vulcan's call.** Either a subsection in
  `docs/deployment/email-otp-setup.md` or a new
  `docs/deployment/frontend-e2e.md`. The subsection is preferred
  because the fixture pair is already introduced in that file.
