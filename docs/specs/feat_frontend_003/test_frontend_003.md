# Test Spec: Profile page — `/profile` route, header Profile button, email-only view

## Test harness

This feature ships **Playwright e2e tests only** — consistent with
`feat_frontend_002`. No Vitest, no React Testing Library, no component
tests. The runner targets the compose-brought-up stack (`make up` from
the repo root) and drives Chromium against `http://localhost:5173` (or
`PLAYWRIGHT_BASE_URL`).

- Location: `frontend/tests/e2e/profile.spec.ts` (new, this feature).
- Existing infrastructure reused (no changes):
  - `frontend/playwright.config.ts`
  - `frontend/tests/e2e/fixtures.ts` (`getOtpFixture()`)
  - `bun run test:e2e` script in `frontend/package.json`
- Env: same `TEST_OTP_EMAIL` / `TEST_OTP_CODE` pair as `login.spec.ts`.
  When unset, the new spec calls `test.skip` and exits cleanly.
- `./test.sh` is unchanged and does **not** invoke Playwright.

## Happy Path

| # | Test Case | Input | Expected Output |
|---|---|---|---|
| 1 | Header has a Profile button at leftmost slot | After login on `/` | `page.getByTestId('auth-header-profile')` is visible, enabled, and is the first child of `[data-testid="auth-header"]`. |
| 2 | Profile button label | After login on `/` | The Profile button's text content is exactly `Profile`. |
| 3 | Click Profile navigates to `/profile` | Login -> click Profile button | URL becomes `/profile`. The auth bootstrap (`/api/v1/auth/me`) is NOT re-fired by this navigation (only client-side route change). |
| 4 | Profile page renders heading | On `/profile` | A heading with text `Profile` is visible. |
| 5 | Profile page renders email value | On `/profile`, fixture email = `e2e@example.com` | `page.getByTestId('profile-page-email')` has text exactly `e2e@example.com`. |
| 6 | Profile page does NOT render `Email:` label | On `/profile` | No element on the profile page contains the literal text `Email:`. (The header still shows the email separately; the assertion is scoped to `[data-testid="profile-page"]`.) |
| 7 | Header still rendered on `/profile` | On `/profile` | `[data-testid="auth-header"]` is visible; Profile, email span, role chips, and Logout are all present. |
| 8 | Header order is Profile, email, roles, Logout | On `/profile` | The four `data-testid` elements appear in this DOM order under `[data-testid="auth-header"]`: `auth-header-profile`, `auth-header-email`, `auth-header-roles`, `auth-header-logout`. |
| 9 | Click Profile while on `/profile` is a no-op | On `/profile`, click Profile button | URL is still `/profile`. No console error. The page does not flicker into a loading state (because `<AuthContext>` does not re-bootstrap on a same-URL push). |
| 10 | Logout from `/profile` ends session | On `/profile`, click Logout | `POST /api/v1/auth/logout` returns 204; URL becomes `/login`; the email input from the login page is visible. |
| 11 | After logout, `/profile` redirects | After logout, `await page.goto('/profile')` | URL becomes `/login` (the `<RequireAuth>` gate redirects). |
| 12 | Relative-URL invariant | Inspect network log over the entire run | Every `/api/v1/...` request targets the same origin as the page. No `http://localhost:8000` origin appears. (Mirrors `login.spec.ts` happy-path #11; folded in as a safety net.) |
| 13 | Dashboard still works after this feature | Navigate `/profile` -> back-button -> `/` | Dashboard renders normally, header still has the Profile button at the leftmost slot. (Regression check that the `feat_frontend_002` flow is undisturbed.) |

The spec ships a single `test()` that performs the whole round trip
(login -> Profile click -> assertions on `/profile` -> Profile re-click
-> Logout -> redirect re-check). This matches the structural choice in
`login.spec.ts`. Splitting into multiple tests is acceptable but each
test would have to repeat the login dance, which is slow and adds rate-
limit risk.

## Error Cases

| # | Test Case | Input | Expected Behavior |
|---|---|---|---|
| 1 | Direct visit to `/profile` while signed out | Open a fresh page, `await page.goto('/profile')` | URL becomes `/login` (via `<RequireAuth>` -> `<Navigate to="/login" replace />`). The profile page heading does not flash on screen. |
| 2 | Backend 5xx on `/auth/me` while signed out, user opens `/profile` | Simulate 500 on `/auth/me` (or stop the backend container) | `<AuthContext>` lands in `'anonymous'`; `<RequireAuth>` redirects to `/login`. No crash, no infinite redirect loop. (Optional — covered implicitly by the existing `feat_frontend_002` design.) |
| 3 | Logout API returns 5xx from `/profile` | Backend errors on `POST /auth/logout` while user clicks Logout from `/profile` | UI still clears in-memory auth state and navigates to `/login` (defensive — mirrors `feat_frontend_002`'s logout error handling). Optional Playwright assertion. |
| 4 | Email contains HTML-special characters | User row has `email = 'a<b>"c"@example.com'` (synthetic — not a real fixture) | React escapes text children, so the literal string is rendered verbatim with no HTML interpretation. The element's `textContent` matches the raw email exactly. (Documented as expected behavior; not tested in CI because no operator-set fixture matches this shape.) |
| 5 | `user === null` while `status === 'authenticated'` | Defensive code path; cannot occur via normal flow | `ProfilePage` returns `null` (renders nothing). Documented; not asserted in Playwright. |

Cases 2 and 3 are documented for future testers but are **not** required
to land this feature. Case 1 IS required and is asserted by Happy
Path #11. Case 4 is documented as a property of React's text-child
escaping; no test infrastructure for synthetic email shapes is built.

## Boundary Conditions

| # | Test Case | Condition | Expected Behavior |
|---|---|---|---|
| 1 | Fixture not set | `TEST_OTP_EMAIL` or `TEST_OTP_CODE` empty on the Playwright runner | Spec calls `test.skip`; Playwright prints a clean skip; exit code 0. |
| 2 | OTP request rate-limited | `POST /auth/otp/request` returns 429 (e.g. because a prior run just ran) | Spec calls `test.skip('rate-limited; retry later')`, mirroring `login.spec.ts`. |
| 3 | Stack not up | Backend is not running when Playwright launches | First navigation times out; Playwright reports the network error cleanly. Operator is expected to run `make up` before `bun run test:e2e`. |
| 4 | Prod-profile frontend | Operator runs compose with `--profile prod` (frontend on :8080) | `PLAYWRIGHT_BASE_URL=http://localhost:8080 bun run test:e2e` runs the same spec against the prod bundle. The spec must not hardcode `:5173` outside config. |
| 5 | Refresh on `/profile` | User reloads the page while on `/profile` | Loading skeleton flashes (from `<RequireAuth>` during bootstrap), then `/profile` re-renders with email visible. URL is preserved (no redirect to `/`). |
| 6 | Click Profile on `/login` | Should not be possible — Profile button is in `<Header>`, which is only rendered on authed routes | Test is N/A. Documented for completeness: the Profile button does not exist on `/login`. |
| 7 | `display_name` is set | User row has `display_name = 'Ada Lovelace'` | The dashboard greeting still uses `display_name`, but the profile page shows the **email**, not the display name (per the user's "just email" requirement). |
| 8 | Email of unusual length | Email is 60+ chars long | The email renders without truncation. CSS does not introduce `text-overflow: ellipsis` or `overflow: hidden` on `.profile-page__email`. Horizontal overflow at very narrow viewports is acceptable; this feature does not add responsive layouts. |
| 9 | Browser back-button after navigating to `/profile` | On `/profile`, click browser Back | URL becomes `/`; dashboard renders. The history stack contains both entries, so Forward returns to `/profile`. |
| 10 | Manual URL edit to `/profile/sub` (non-existent sub-route) | Type `/profile/foo` into URL bar | Catches the `*` route in `App.tsx`, redirects to `/`, which then renders the dashboard. (No test asserts this; it's a property of the existing route table.) |

## Security Considerations

- **No new API surface.** This feature adds zero `fetch` calls. There
  is no new endpoint to authenticate, no new request body to validate,
  no new response shape to interpret. The threat model from
  `feat_frontend_002` is unchanged by this feature.
- **HttpOnly cookie still untouched.** The Playwright spec does not
  read `document.cookie`. Login state is asserted via observable UI
  (header strip, profile email, dashboard URL).
- **Relative-URL invariant.** Happy Path #12 carries the same
  assertion `login.spec.ts` ships: every `/api/v1/*` request targets
  the page origin. No accidental absolute-URL regression can slip in
  via this feature because it does not add any new `fetch`, but the
  test fires the assertion regardless, which guards the entire run
  including the login dance.
- **Profile button is not a URL injection vector.** The `onClick`
  handler hard-codes the path `/profile`. There is no user-supplied
  data flowing into the navigation target.
- **Email rendering is safe.** React escapes text children. No
  `dangerouslySetInnerHTML` is used. The email value, even if pre-
  populated by an attacker through some upstream flow, cannot inject
  script tags into the page.
- **No cross-origin requests.** This feature does not introduce any
  cross-origin call, redirect, or `<iframe>`.
- **No PII expansion.** The page renders only `email`, which the user
  is already authenticated as — the same value the `<Header>`
  already shows. No additional PII (e.g. phone numbers, addresses, IP)
  is surfaced.
- **No CSRF surface.** The feature adds zero state-mutating endpoints.
- **No console leak of sensitive data.** The new code does not
  `console.log` any auth state. The Playwright console listener
  inherited from the spec scaffolding (if used) asserts no fixture
  email or code appears in console output during the run; a copy-
  paste of the convention from `login.spec.ts` is acceptable but
  optional.

## Verification checklist for Vulcan

Before opening the build PR, Vulcan should confirm:

- [ ] `bun run build` passes with zero TS errors.
- [ ] `bun run test:e2e` passes locally with the fixture env set and
      `make up` running. Both `login.spec.ts` and `profile.spec.ts`
      green.
- [ ] `bun run test:e2e` skips cleanly (exit 0, no red tests) when the
      fixture env is unset.
- [ ] `./test.sh` still passes (backend + REST suite). No regression.
- [ ] Git grep for `credentials: 'include'` in `frontend/src/` returns
      zero hits (unchanged from `feat_frontend_002`).
- [ ] Git grep for `http://localhost` or absolute `http://` URLs in
      `frontend/src/` returns zero new hits.
- [ ] No new dependency added to `frontend/package.json` (the feature
      uses only deps already pulled in by `feat_frontend_002`).
- [ ] No file under `backend/`, `infra/`, or `tests/` is modified.
- [ ] `frontend/src/components/Header.tsx` shows Profile as the
      **first** JSX child of the `<header>` element (verified visually
      and via the e2e spec's DOM-order assertion).
- [ ] Spec README and `docs/tracking/features.md` rows are appended
      and the Spec PR + Issues columns are backfilled.
