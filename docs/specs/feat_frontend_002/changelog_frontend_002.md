# Changelog — `feat_frontend_002`

## Added

- **Login UI.** `/login` route renders a two-step email-OTP form.
  Step 1 calls `POST /api/v1/auth/otp/request`; step 2 calls
  `POST /api/v1/auth/otp/verify`; a 200 navigates to `/`. Includes a
  disabled "Sign in with Google (coming soon)" button as a placeholder
  for `feat_auth_003`.
- **AuthContext.** New context in `frontend/src/auth/AuthContext.tsx`
  exposing `{ user, status, refresh, logout }`. States:
  `loading | authenticated | anonymous`. Bootstraps from
  `GET /api/v1/auth/me` on mount; a 401 is interpreted as anonymous,
  not an error.
- **RequireAuth route gate.** New `frontend/src/auth/RequireAuth.tsx`.
  Renders a loading skeleton during bootstrap and
  `<Navigate to="/login" replace />` when anonymous.
- **Dashboard + Header strip.** New `/` route renders a persistent
  header (email + role chips + logout) above a dashboard body
  (greeting + role list + the preserved `HelloPanel` that still
  exercises the `/api/v1/hello` Postgres+Redis demo).
- **Auth API client.** New `frontend/src/api/auth.ts` exports
  `getMe`, `logout`, `requestOtp`, `verifyOtp`, and the `Me` type.
  `getMe` returns `null` on 401 so the context can handle the
  anonymous happy path without an error-shaped return. `requestOtp`
  throws a typed `RateLimitError` on 429 carrying the `retry_after`
  seconds from the body.
- **Playwright e2e harness.** New `frontend/playwright.config.ts`,
  `frontend/tests/e2e/fixtures.ts`, and `frontend/tests/e2e/login.spec.ts`
  driving the full round-trip (redirect → OTP request → verify →
  dashboard → logout) in a real Chromium against the compose stack.
  Includes a relative-URL-invariant assertion that catches any
  absolute-URL regression in auth fetches.
- **`bun run test:e2e` script** in `frontend/package.json`, separate
  from `./test.sh`.
- **Operator guide.** New "E2E smoke test" section in
  `docs/deployment/email-otp-setup.md` covering one-time
  `bunx playwright install chromium`, the `TEST_OTP_EMAIL` /
  `TEST_OTP_CODE` fixture pair, prod-profile URL override, and
  rate-limit retry guidance.
- **Testing section in `frontend/README.md`** pointing at the
  operator guide.

## Changed

- `frontend/src/App.tsx` is now the routing root (`<Routes>` shell)
  rather than a standalone hello page. The hello-page logic moved
  into `frontend/src/components/HelloPanel.tsx`, rendered unchanged
  inside the authed `Dashboard`.
- `frontend/src/main.tsx` wraps `<App />` in `<BrowserRouter>` and
  `<AuthProvider>`.
- `frontend/src/App.css` grew by ~140 lines: styles for the login
  page, header strip, role chips, dashboard layout, and the
  auth-bootstrap loading skeleton.
- `frontend/.gitignore` now ignores `test-results/`,
  `playwright-report/`, `playwright/.cache/`, and
  `tests/e2e/.auth/`.
- Tracker rows in `docs/tracking/features.md` and
  `docs/specs/README.md` advanced `feat_frontend_002` from `Ready` to
  `In Build`.

## Dependencies

- **Added runtime:** `react-router-dom@^7.0.0`.
- **Added dev:** `@playwright/test@^1.49.0`. Dev-only by contract; the
  production bundle has no knowledge of it.
- **Added per-machine tool:** Playwright browser binaries installed
  via `bunx playwright install chromium`. Not a package dep — a
  binary download into `~/.cache/ms-playwright/`.

## Unchanged (by design)

- `backend/` — zero file edits. The backend already exposed exactly
  what this UI needed (`/auth/me`, `/auth/logout`, `/auth/otp/request`,
  `/auth/otp/verify`).
- `./test.sh` — still runs only the backend + REST suites
  (9 passed, 2 skipped). Playwright is a separate `bun run test:e2e`
  invocation.
- The `/api/v1/hello` endpoint and its Postgres+Redis wiring. The
  `HelloPanel` still renders it end-to-end from inside the authed
  dashboard.

## Acceptance criteria status

All 17 acceptance criteria from `feat_frontend_002.md` verified:

- [x] `/` with no cookie redirects to `/login`; URL bar shows `/login`.
- [x] `/login` renders email form + disabled "Sign in with Google
      (coming soon)" button.
- [x] Step-1 submit calls `/otp/request` exactly once and advances.
- [x] Step-2 submit calls `/otp/verify` exactly once; 200 → navigate
      to `/`.
- [x] After verify, `/` renders header strip + dashboard body.
- [x] Google click performs no network call (Playwright Happy #3).
- [x] Logout clears auth + navigates to `/login`.
- [x] Refresh with live cookie preserves authed UI.
- [x] Refresh after cookie expiry → redirect to `/login`
      (implicit — any 401 on `/auth/me` flows through the same
      anonymous gate).
- [x] No `credentials: 'include'`; no absolute URLs; verified by
      Playwright Happy #11 and by `git grep`.
- [x] `bun run build` passes with zero TS errors.
- [x] `@playwright/test` only under `devDependencies`.
- [x] `login.spec.ts` asserts the full flow including `/auth/me`
      data in the DOM.
- [x] Fixture-unset → clean skip, exit 0.
- [x] `frontend/README.md` documents install + run commands + links
      the operator guide.
- [x] `./test.sh` unchanged; no Playwright invocation.
- [x] No `backend/` files modified.
