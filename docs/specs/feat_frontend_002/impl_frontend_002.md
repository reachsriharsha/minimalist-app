# Implementation Notes — `feat_frontend_002`

## What landed

The login UI over the already-shipping OTP backend. Seven new source
files plus two rewritten ones under `frontend/src/`, a Playwright e2e
harness under `frontend/tests/e2e/`, and two doc updates (frontend
README, email-otp operator guide). **No backend files were touched.**

### Source-tree additions

```
frontend/src/
  api/auth.ts                       (NEW)  getMe, logout, requestOtp, verifyOtp
  auth/AuthContext.tsx               (NEW)  provider + useAuth()
  auth/RequireAuth.tsx               (NEW)  route gate
  components/AuthedLayout.tsx        (NEW)  Header + <main>
  components/Header.tsx              (NEW)  email + roles + logout
  components/HelloPanel.tsx          (NEW)  extracted hello widget
  pages/LoginPage.tsx                (NEW)  two-step OTP form
  pages/Dashboard.tsx                (NEW)  greeting + roles + HelloPanel
  App.tsx                            (REWRITE) routing root
  main.tsx                           (MODIFY)  BrowserRouter + AuthProvider
  App.css                            (MODIFY)  ~140 new lines of layout CSS

frontend/
  playwright.config.ts               (NEW)
  tests/e2e/fixtures.ts              (NEW)
  tests/e2e/login.spec.ts            (NEW)
  package.json                       (MODIFY) +react-router-dom, +@playwright/test
  README.md                          (MODIFY) Testing section
  .gitignore                         (MODIFY) test-results/, playwright-report/
```

### Dependencies

| Package              | Kind     | Version    |
|----------------------|----------|------------|
| `react-router-dom`   | dep      | `^7.0.0`   |
| `@playwright/test`   | devDep   | `^1.49.0`  |

No other runtime deps were added. No state-management or component
libraries were pulled in — the feature uses plain `useState` / `useEffect`
plus the one `AuthContext`.

## AuthContext contract (as implemented)

Three states: `loading | authenticated | anonymous`.

- **Mount** → `status='loading'` + call `getMe()`.
- **200** → `status='authenticated'`, `user=payload`.
- **401** → `status='anonymous'`, `user=null`. *Not* an error. `getMe()`
  returns `null` in this case; only non-401 non-2xx throws.
- **Anything else** (network error, 5xx) → `console.warn` + fall back
  to `anonymous`. The UI never gets stuck in `loading`.
- `refresh()` re-runs the bootstrap. Used by `LoginPage` after verify.
- `logout()` calls the API then clears local state + `navigate('/login')`.
  Defensive: if the API call throws, we still clear state — a stale
  cookie is less bad than a wedged UI.

## Routing contract

```
<BrowserRouter>
  <AuthProvider>
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={
        <RequireAuth>
          <AuthedLayout>
            <Dashboard />
          </AuthedLayout>
        </RequireAuth>
      } />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  </AuthProvider>
</BrowserRouter>
```

`<RequireAuth>` renders a loading skeleton during bootstrap, then either
a `<Navigate to="/login" replace />` (anonymous) or children
(authenticated). This avoids the "flash of login UI" on refresh for
authed users.

## Google button

Plain `<button type="button" disabled aria-disabled="true"
title="Google sign-in coming soon">Sign in with Google (coming soon)</button>`.
No `onClick`, no `fetch`, no reference to any backend path. The Playwright
suite clicks it with `force: true` and asserts zero `/api/v1/*` calls
fire. `feat_auth_003` will replace the element wholesale.

## Same-origin invariant

All four auth calls (`getMe`, `logout`, `requestOtp`, `verifyOtp`) use
relative URLs (`/api/v1/auth/...`) and pass **no** `credentials` option
to `fetch`. The `HttpOnly; SameSite=Lax` session cookie rides along on
same-origin requests by default; the Vite dev proxy (and the nginx
origin in the prod profile) keep the page and API origins identical.

The Playwright suite's "relative-URL invariant" assertion (Happy Path
#11) records every `/api/v1/*` request URL during the full run and
asserts each one's origin equals the page origin. An absolute-URL
regression like `http://localhost:8000/api/...` would fail this check.

## Playwright wiring

- **Config:** `frontend/playwright.config.ts`. Single `chromium` project,
  `fullyParallel: false`, `workers: 1`, `baseURL` from
  `PLAYWRIGHT_BASE_URL` env var (default `http://localhost:5173`). No
  `webServer` block — the operator runs `make up` first.
- **Fixture:** `frontend/tests/e2e/fixtures.ts` exports `getOtpFixture()`
  mirroring `_otp_fixture_env()` in `tests/tests/test_auth.py`. Empty env
  → `null` → `test.skip` with exit 0.
- **Coverage** (11 happy-path test cases from the test spec, plus
  one malformed-email case):
  - Landing redirect, login page elements, Google button inertness,
    OTP request 204, wrong-code inline error, OTP verify 200,
    dashboard + header render, refresh-preserves-auth, logout,
    post-logout redirect, relative-URL invariant, OTP-code not
    logged to browser console.
  - `test.skip('OTP rate limit hit; retry later')` when the backend
    returns 429 on `/otp/request` (mirrors
    `tests/tests/test_auth.py`'s retry behavior).
- **Install:** `bunx playwright install chromium` — one-time per
  machine, documented in both `frontend/README.md` and
  `docs/deployment/email-otp-setup.md#e2e-smoke-test`.
- **Runner boundary:** `./test.sh` is unchanged. Playwright runs only
  via `bun run test:e2e` from `frontend/`.

## Tracker

Row for `feat_frontend_002` moved from `Ready` → `In Build` at the
start of this build in both `docs/tracking/features.md` and
`docs/specs/README.md`. The `Status` column will flip to `Merged` and
the `Impl PRs` column will be backfilled with the build PR number by
Vulcan in follow-up commits on this branch (per `conventions.md` §7
lifecycle).

## Verification

- `bun run build` — **pass**, zero TS errors, 51 modules transformed.
- `./test.sh` — **pass**, 9 passed / 2 skipped. No regression; the
  test driver runs unchanged.
- `bun run test:e2e` with fixture set, against a live `make up` stack
  — **pass**, 2/2 tests green in ~4.6 seconds on the author's machine.
- `bun run test:e2e` with fixture unset — **clean skip**, exit 0.
- `git grep credentials: frontend/src/` — returns only the doc-comment
  mention inside `api/auth.ts` explaining why the option is *not* used.
- `git grep http://localhost frontend/src/` — one hit in
  `vite-env.d.ts` (pre-existing doc comment), zero new hits.
- `git diff main...HEAD -- backend/` — empty.

## Deviations from the spec

None of material substance. Two small call-its-out-loud items:

1. **Operator doc placement.** The design spec offered Vulcan a choice
   between "subsection in `docs/deployment/email-otp-setup.md`" or a
   new `docs/deployment/frontend-e2e.md`. I chose the subsection —
   keeps the fixture documentation in one place, avoids a new top-level
   operator doc for a single 90-line section.
2. **Logout navigation on API failure.** The design spec says the
   header "calls `POST /api/v1/auth/logout`, clears the in-memory
   `AuthContext`, and navigates to `/login`." I added a defensive
   `try/catch/finally` in `AuthContext.logout()` so that even if the
   API call throws (network error or 5xx) we still clear state and
   navigate. This matches the test spec's Error Case #5 ("Logout call
   fails with 5xx — UI still clears in-memory auth state and navigates
   to `/login`"). The UI surface stays identical.
