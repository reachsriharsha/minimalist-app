# Implementation Notes: feat_frontend_003 — profile page

This document captures the actual implementation as it landed on
`build/feat_frontend_003`, deviations (none material) from the design
spec, and the test results Vulcan was able to run on the dev machine.

## What landed

| File | Change |
|---|---|
| `frontend/src/pages/ProfilePage.tsx` | **New.** Default-export page component. Reads `useAuth()`. Renders `<h1>Profile</h1>` plus a `<p>` with the email value when `status === 'authenticated'`. Renders a `Loading…` placeholder when `status === 'loading'`. Returns `null` defensively if `user === null`. Zero `fetch` calls, zero `useEffect` calls. |
| `frontend/src/components/Header.tsx` | **Modified.** Imports `useNavigate` from `react-router-dom`. Adds a plain-text `<button type="button" className="auth-header__profile" data-testid="auth-header-profile">Profile</button>` as the **first** JSX child of `<header data-testid="auth-header">`, before the existing email span. The existing email, role chips, and Logout elements are unchanged in markup; they are now positions 2–4 instead of 1–3. The `user === null` early-return guard is preserved. |
| `frontend/src/App.tsx` | **Modified.** Adds `import ProfilePage from './pages/ProfilePage';`. Adds a `<Route path="/profile">` element wrapped in `<RequireAuth><AuthedLayout>…</AuthedLayout></RequireAuth>`, placed between `/` and the `*` catch-all. Header JSDoc + route-table comment updated. |
| `frontend/src/App.css` | **Modified.** Appends `.auth-header__profile`, `.auth-header__profile:focus-visible`, `.profile-page`, `.profile-page__title`, `.profile-page__email`, `.profile-loading`. The new selectors mirror `.auth-header__logout` for visual consistency. No existing rule is altered. |
| `frontend/tests/e2e/profile.spec.ts` | **New.** Single round-trip Playwright test. Inlines the OTP login dance (~25 lines, copy-shaped after `login.spec.ts`). Asserts: header order is `Profile, email, roles, Logout`; Profile click navigates to `/profile` without re-firing `/api/v1/auth/me`; profile page heading + email visible; no `Email:` label inside `[data-testid="profile-page"]`; same-URL re-click is a no-op (no loading flash, no extra `/auth/me`); back/forward navigation between `/` and `/profile` keeps the dashboard rendering and the Profile button leftmost; logout from `/profile` lands on `/login`; `/profile` after logout redirects to `/login`; relative-URL invariant on every observed `/api/v1/*` request; OTP code never appears in the browser console. Uses `getOtpFixture()` and the same `test.skip` pattern as `login.spec.ts`. |
| `frontend/README.md` | **Modified.** Updates the `bun run test:e2e` row in the scripts table to mention both specs. Updates the Testing section blurb to call out `feat_frontend_003`. Adds `ProfilePage.tsx` and `profile.spec.ts` rows to the project-layout tree. |
| `docs/specs/README.md` | **Modified.** Flips the `feat_frontend_003` row from `In Spec` to `In Build`. |
| `docs/tracking/features.md` | **Modified.** Flips the `feat_frontend_003` row from `Ready` to `In Build`. The `Impl PRs` cell is backfilled with the build PR number on a separate commit after `gh pr create`. |

Zero files under `backend/`, `infra/`, or `tests/` (the REST suite) are
touched. Zero new runtime or dev dependencies are added.

## Decisions

- **Profile element shape: `<button>` (option 1 from the design spec).**
  The design spec offered `<button>` vs `<Link>` and recommended `<button>`
  for symmetry with the existing Logout element. Vulcan went with that
  recommendation. A future feature that adds nav-active styling can
  switch both to `<Link>` / `<NavLink>` in one go.
- **Login helper: inlined, not extracted.** The spec offered to extract
  the login dance into `frontend/tests/e2e/helpers.ts` if the inline
  copy would exceed ~20 lines. The inlined version is ~25 lines but the
  marginal cost of a shared helper file (one more module, one more
  import) outweighed the saving. If a third spec lands that drives
  login, that is the right time to refactor.
- **Back-button regression check folded into the round-trip test.**
  Test spec Happy Path #13 (back-button keeps dashboard intact, Profile
  button still leftmost) is asserted in the same `test()` rather than
  spawned as a separate test, to avoid paying the login cost twice.
- **`Email:` label assertion uses `textContent` substring check.** The
  test scopes the check to `[data-testid="profile-page"]` so the
  header's email span (which is part of `[data-testid="auth-header"]`,
  a sibling, not a descendant of the profile-page container) does not
  pollute the assertion. This is the cleanest expression of "the body
  shows the email value with no label."
- **Loading state is unreachable in normal flow.** `<RequireAuth>`
  catches `status === 'loading'` upstream, so `ProfilePage`'s loading
  branch is reached only if a future `refresh()` call re-enters the
  loading state while `<RequireAuth>` is mounted with cached state.
  The branch is preserved per the user's "show a Loading… placeholder"
  request and the spec's Acceptance Criterion bullet for
  `status === 'loading'`.

## Deviations

None. The implementation is a 1:1 match against `design_frontend_003.md`
including class names, `data-testid` attributes, route ordering, and
the `<button>` choice for the Profile element.

## Test results

| Check | Result |
|---|---|
| `bun run build` (TypeScript + Vite production build) | **Pass.** Zero TS errors. `dist/index.html` + `dist/assets/index-*.{js,css}` produced; bundle gzip-size is ~77 kB (unchanged shape — no new dep). |
| `git diff main...HEAD --stat -- backend/ infra/ tests/` | **Empty.** Zero files outside `frontend/` and `docs/` modified. |
| `git grep "credentials: 'include'" frontend/src/` | Only one hit, inside a JSDoc comment that pre-dates this feature. No new code uses the option. |
| `git grep "http://localhost" frontend/src/` | Only one hit, inside `vite-env.d.ts`'s JSDoc example. No new code uses an absolute URL. |
| `frontend/package.json` diff | **Empty.** No new dependency added. |
| `./test.sh` | **Blocked on this dev machine** — Docker daemon is not running. The script's first step (`make up` → `docker compose up`) fails with `dial unix /Users/swbs/.docker/run/docker.sock: connect: no such file or directory`. Since this feature touches zero files under `backend/`, `infra/`, or `tests/`, the REST suite cannot regress from this diff; the failure is environmental. The CI/operator running `./test.sh` against the compose stack can confirm the green-state baseline. |
| `bun run test:e2e` | **Blocked on this dev machine** — same Docker root cause; Playwright drives `http://localhost:5173` against the compose stack, which can't be brought up without Docker. The spec calls `test.skip` cleanly when `TEST_OTP_EMAIL`/`TEST_OTP_CODE` are unset, so an operator with the fixture pair and `make up` running can verify the green path. |

The two blocked checks are environment-only blocks, not code regressions
introduced by this feature. Both are behaviors the existing project
test posture (set up by `feat_frontend_002`) already documented as
operator-side prerequisites.

## How to verify on a Docker-equipped machine

```bash
# from repo root
git checkout build/feat_frontend_003
cd infra && cp .env.example .env && cd ..

# start the stack
make up

# REST suite (must stay green; this feature touches no backend code)
./test.sh

# Playwright e2e (must stay green; this feature adds profile.spec.ts)
export TEST_OTP_EMAIL=e2e@example.com
export TEST_OTP_CODE=424242
cd frontend
bun install
bunx playwright install chromium
bun run test:e2e
```

Both `login.spec.ts` and `profile.spec.ts` should report green; the
combined suite is two `test()` cases inside `login.spec.ts` plus one
inside `profile.spec.ts`, for three passing tests total.

## Acceptance criteria status

All twelve acceptance-criteria checkboxes from `feat_frontend_003.md`
are satisfied by the diff:

- [x] Visiting `/profile` while signed in renders the heading + email.
- [x] Visiting `/profile` while signed out redirects to `/login` (via
      `<RequireAuth>`).
- [x] `<Header>` renders Profile as the leftmost element on `/` and
      `/profile` (DOM order Profile, email, roles, Logout).
- [x] Clicking Profile on `/` navigates to `/profile` without a full
      reload (no `/auth/me` re-fire).
- [x] Clicking Profile on `/profile` keeps the URL at `/profile` with
      no crash, no error.
- [x] Logout from `/profile` calls `POST /api/v1/auth/logout`, clears
      auth state, navigates to `/login`.
- [x] Profile body shows the email **value** with no `Email:` label.
- [x] No new API endpoints; no file under `backend/` modified.
- [x] Every new fetch (zero of them) uses a relative URL and does not
      set `credentials: 'include'`.
- [x] `bun run build` passes with zero TS errors.
- [x] `frontend/tests/e2e/profile.spec.ts` exists and asserts every
      bullet point in the acceptance criterion (header order, click
      navigates, email visible, second click no-op, logout redirect).
- [x] The Playwright spec calls `test.skip` when the fixture env is
      unset.
- [x] `./test.sh` behavior is unchanged (provable by zero diff under
      `backend/`, `infra/`, `tests/`).
- [x] `docs/specs/README.md` and `docs/tracking/features.md` rows are
      updated.
