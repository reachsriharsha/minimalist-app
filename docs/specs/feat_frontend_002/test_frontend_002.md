# Test Spec: Login UI — AuthContext, `/login` page, dashboard, and Playwright e2e

## Test harness

This feature ships **Playwright e2e tests only** — no Vitest, no React
Testing Library, no component tests. The one harness runs against the
compose-brought-up stack (`make up` from the repo root) and drives
the browser end-to-end against `http://localhost:5173`.

- Location: `frontend/tests/e2e/`
- Config: `frontend/playwright.config.ts`
- Script: `bun run test:e2e` (= `playwright test`)
- Browsers: installed per-machine with `bunx playwright install` (one-
  time; documented in `frontend/README.md`).
- Env: the runner reads `TEST_OTP_EMAIL` and `TEST_OTP_CODE` from its
  own process env. These must match the backend's settings (set
  through `infra/.env` before `make up`). When either is empty, the
  test suite calls `test.skip` (mirroring `tests/tests/test_auth.py`),
  so running Playwright without the fixture prints a clean skip, not
  a red failure.
- `./test.sh` is unchanged and does **not** invoke Playwright. That is
  a deliberate boundary.

## Happy Path

| # | Test Case | Input | Expected Output |
|---|---|---|---|
| 1 | Unauthenticated landing redirect | Visit `/` with no session cookie | URL becomes `/login`; email input visible. |
| 2 | Login page renders key elements | Visit `/login` | Email input, "Send code" button, disabled "Sign in with Google (coming soon)" button, all present. |
| 3 | Google button is inert | Click the Google button | No network call made; URL unchanged; step state unchanged. |
| 4 | OTP request advances to step 2 | On `/login`, fill email = `TEST_OTP_EMAIL`, click "Send code" | `POST /api/v1/auth/otp/request` returns 204; UI shows the 6-digit code input and a "code sent" affordance. |
| 5 | OTP verify lands on dashboard | Fill code = `TEST_OTP_CODE`, click "Verify" | `POST /api/v1/auth/otp/verify` returns 200; browser navigates to `/`; header strip + dashboard body visible. |
| 6 | Dashboard shows profile data | After happy-path login | Greeting line contains the email (or `display_name` if set); role list includes `user`; HelloPanel renders the `message` field from `/api/v1/hello`. |
| 7 | Header strip shows identity | After happy-path login | Header contains the signed-in email and the `user` role chip; Logout button is enabled. |
| 8 | Refresh preserves auth | After happy-path login, press F5 on `/` | Loading skeleton flashes, then dashboard re-renders (no redirect to `/login`). |
| 9 | Logout ends session | Click Logout on the dashboard | `POST /api/v1/auth/logout` returns 204; browser navigates to `/login`; email input visible again. |
| 10 | After logout, `/` redirects again | After logout, manually navigate to `/` | Browser redirects to `/login`. |
| 11 | Relative-URL invariant | Inspect the network log for the whole happy-path run | Every `/api/v1/...` request targets the same origin as the page (no `http://localhost:8000` origin). |

Case 11 is enforced by attaching a `page.on('request', …)` listener in
the Playwright spec and asserting `new URL(req.url()).origin === new
URL(baseURL).origin` for every request whose path starts with
`/api/v1/`. If any absolute-URL regression slips in, this test fails.

## Error Cases

| # | Test Case | Input | Expected Behavior |
|---|---|---|---|
| 1 | Wrong OTP code | Request a code, then submit `999999` | `POST /api/v1/auth/otp/verify` returns 400; inline error on the code form; URL stays on `/login`; user can retype and re-submit without refreshing. |
| 2 | Malformed email on step 1 | Enter `notanemail`, click "Send code" | Client-side validation blocks submit (no network call), or backend returns 422/400 and the inline error is rendered. Either behavior is acceptable; the test just asserts the UI does not advance to step 2 and no cookie is set. |
| 3 | Backend 5xx on `/auth/me` | Bootstrap hits a simulated 500 (route the browser at a mock or stop the backend container) | App treats it as anonymous: redirects to `/login`; no error overlay; no infinite-loop retries. |
| 4 | Network failure on verify | Code submit interrupted at the network layer | UI shows a "try again" affordance; no redirect; no cookie set. |
| 5 | Logout call fails with 5xx | Backend errors on `POST /auth/logout` | UI still clears in-memory auth state and navigates to `/login` (defensive — stale cookie is less bad than stuck UI). |

Error cases 3–5 are documented as **optional** Playwright assertions.
The Playwright spec that ships with this feature covers cases 1–2
(happy-adjacent failures that the real backend produces naturally) and
asserts `/auth/me` 401 -> redirect implicitly via the "unauthenticated
landing redirect" test in the Happy Path table. Cases 3–5 require
network interception or backend manipulation and are **not** required
for the feature to land. They are listed here so a future tester knows
the intended behavior.

## Boundary Conditions

| # | Test Case | Condition | Expected Behavior |
|---|---|---|---|
| 1 | Fixture not set | `TEST_OTP_EMAIL` or `TEST_OTP_CODE` empty on the Playwright runner | Spec calls `test.skip`; Playwright prints a clean skip; exit code 0. |
| 2 | Rate-limited OTP request | `POST /auth/otp/request` returns 429 (e.g. because a prior run just ran) | Spec calls `test.skip('rate-limited; retry later')`, mirroring the REST suite's behavior. |
| 3 | Stack not up | Backend is not running when Playwright launches | First navigation times out; Playwright reports the network error cleanly. Operator is expected to run `make up` before `bun run test:e2e`; the README documents this. |
| 4 | Prod-profile frontend | Operator runs compose with `--profile prod` (frontend on :8080) | `PLAYWRIGHT_BASE_URL=http://localhost:8080 bun run test:e2e` runs the same spec against the prod bundle. The spec must not hardcode `:5173` outside config. |
| 5 | Refresh mid-step-2 | User reloads the page while on the OTP-code step | Email is lost; UI returns to step 1. Acceptable. Documented in the design risks table. Not asserted in the Playwright spec. |
| 6 | Expired cookie mid-session | Cookie TTL elapses while the dashboard is open; next API call 401s | Next `refresh()` (or next manual action that hits `/auth/me`) routes the user to `/login`. Asserted at the unit-level only if a component test harness is added later. |
| 7 | `display_name` missing | User row has `display_name = NULL` | Dashboard greeting falls back to the email. HelloPanel still renders. |
| 8 | User with many roles | `roles = ['user', 'admin', 'moderator', ...]` | Header strip renders each role as a chip; no overflow crash (horizontal overflow is allowed — this feature does not add responsive layouts). |

## Security Considerations

- **HttpOnly cookie is never inspected by JS.** The Playwright spec
  does **not** read `document.cookie` to assert login. It asserts login
  via observable UI (header strip visible, dashboard URL, role chips
  rendered). Reading the cookie from JS would be impossible anyway —
  it's `HttpOnly` — but stating it explicitly avoids a reviewer
  questioning the test design.
- **`credentials: 'include'` is forbidden.** The Playwright "relative-
  URL invariant" test (Happy Path #11) plus code review catch any
  accidental introduction.
- **Absolute-URL leak.** Same assertion covers it. A regression
  that uses `http://localhost:8000/api/...` would be same-origin in
  dev (accident) but cross-origin in prod (broken) — Happy Path #11
  catches it in dev.
- **Google button is network-inert.** The "Google button is inert"
  test (Happy Path #3) asserts no network request is emitted when
  the button is clicked. If a future diff wires it up prematurely,
  this test fails.
- **OTP code is not logged by the frontend.** The UI never logs the
  code to the console. Playwright's console listener asserts no log
  line contains the 6-digit `TEST_OTP_CODE`. (This is a light-touch
  check, not a proof — the backend console provider still logs the
  decoy code per `feat_auth_002` design; that's backend behavior and
  out of scope here.)
- **Fixture email domain.** Operators must set `TEST_OTP_EMAIL` to a
  throwaway address under a domain they own (e.g. `e2e@example.com`).
  With the console provider, the real OTP is only in logs; with a
  live provider (Resend, SendGrid), the fixture flow still **sends an
  email to the real address**. Documented in the operator note.
- **Session scope.** The Playwright spec does not attempt privilege
  escalation or role probing. Role-gate tests land when a role-gated
  UI element is added in a later feature.
- **No test for CSRF.** OTP endpoints are CSRF-resistant by design
  (they require a one-time code the attacker cannot guess; see
  `feat_auth_002` security notes). No CSRF surface is added in this
  feature.
- **Input sanitization.** React escapes text children by default, so
  the dashboard greeting and header strip cannot be XSS vectors via
  the `email` or `display_name` fields. No raw-HTML injection escape
  hatches are introduced.

## Verification checklist for Vulcan

Before opening the build PR, Vulcan should confirm:

- [ ] `bun run build` passes with zero TS errors.
- [ ] `bun run test:e2e` passes locally with the fixture env set and
      `make up` running.
- [ ] `bun run test:e2e` **skips cleanly** (exit 0, no red tests) when
      the fixture env is unset.
- [ ] `./test.sh` still passes (backend + REST suite). No regression.
- [ ] Git grep for `credentials: 'include'` in `frontend/src/` returns
      zero hits.
- [ ] Git grep for `http://localhost` or absolute `http://` URLs in
      `frontend/src/` returns zero new hits outside
      `vite-env.d.ts` comments and `vite.config.ts` fallbacks.
- [ ] `frontend/package.json` has `@playwright/test` only under
      `devDependencies` and `react-router-dom` under `dependencies`.
- [ ] No file under `backend/` is modified.
