# Changelog: feat_frontend_003

## Added

- **`/profile` authed route.** A second authed route landed in
  `frontend/src/App.tsx`, gated by the existing `<RequireAuth>` and
  wrapped in the existing `<AuthedLayout>`. Direct visits while
  signed out are redirected to `/login` with no new redirect logic.
- **Profile button in the header strip.** `<Header>` gains a
  plain-text **Profile** button as the leftmost element. It uses
  `useNavigate()` from `react-router-dom` for client-side navigation
  to `/profile`. The button is rendered on every authed route,
  including `/profile` itself; clicking it from `/profile` is a
  harmless re-navigation to the same URL.
- **`ProfilePage` component** at `frontend/src/pages/ProfilePage.tsx`.
  Renders `<h1>Profile</h1>` plus the signed-in user's email value
  (no `Email:` label, no other PII). The page reads the email
  straight off `AuthContext.user`, so it issues zero `fetch` calls.
  Defensively handles the `status === 'loading'` and
  `user === null` branches with a plain-text `Loading…` placeholder
  and a silent `null` return, respectively — neither branch is
  reachable under normal flow because `<RequireAuth>` upstream
  handles those states.
- **Playwright e2e spec** at `frontend/tests/e2e/profile.spec.ts`.
  One round-trip test: log in via the OTP fixture, click the header
  Profile button, assert the URL becomes `/profile` and the email is
  visible on the page body, click Profile a second time on `/profile`
  (no-op), use the browser back-button to return to `/` and forward
  back to `/profile`, click Logout, assert redirect to `/login`,
  and finally assert that visiting `/profile` after logout redirects
  to `/login`. Includes the relative-URL invariant (every observed
  `/api/v1/*` request targets the page origin) and a console-leak
  check for the OTP code. Calls `test.skip` cleanly when
  `TEST_OTP_EMAIL` / `TEST_OTP_CODE` are unset and on a 429 from
  `/auth/otp/request`.

## Changed

- **`<Header>` layout.** The existing email span, role chips, and
  logout button move one slot to the right; their order is preserved
  among themselves. Final DOM order under `[data-testid="auth-header"]`:
  Profile, email, roles, Logout.
- **`App.tsx` route table.** The new `/profile` route is registered
  after `/` and before the `*` catch-all. The catch-all behavior is
  unchanged — typo paths still bounce to `/`, then through
  `<RequireAuth>` to the right place.
- **`App.css`.** Six new selectors: `.auth-header__profile`,
  `.auth-header__profile:focus-visible`, `.profile-page`,
  `.profile-page__title`, `.profile-page__email`, `.profile-loading`.
  No existing rule is altered.
- **`frontend/README.md`.** Updates the `bun run test:e2e` row in the
  scripts table to mention both Playwright specs, updates the Testing
  section blurb, and adds `ProfilePage.tsx` and `profile.spec.ts`
  rows to the project-layout tree.
- **`docs/tracking/features.md` and `docs/specs/README.md`.** The
  `feat_frontend_003` row advances from `Ready` / `In Spec` to
  `In Build`.

## Unchanged

- **Zero backend changes.** No file under `backend/` is modified, no
  new endpoints, no schema changes. The page reads from the existing
  `/auth/me` payload that `AuthContext` already holds.
- **Zero infrastructure or REST-suite changes.** `infra/` and `tests/`
  are untouched. `./test.sh` behavior is unchanged.
- **Zero new dependencies.** `frontend/package.json` is unmodified.
  All work uses `react-router-dom@^7` and `@playwright/test@^1`,
  both already pulled in by `feat_frontend_002`.
- **Existing `/login` and `/` flows.** No assertion in `login.spec.ts`
  needed to change. The dashboard greeting still uses `display_name`
  with a fallback to email; the profile page deliberately uses the
  email regardless of `display_name`, per the user's "just email"
  requirement.

## Security

- No new API surface. Zero new `fetch` calls; zero new request bodies;
  zero new response shapes. The threat model from `feat_frontend_002`
  carries forward unchanged.
- Email rendering is safe (React-escaped text child; no
  `dangerouslySetInnerHTML`).
- Profile-button `onClick` hard-codes the path `/profile`; no
  user-supplied data flows into the navigation target.
- The Playwright spec re-asserts the relative-URL invariant across
  the entire run (login through logout), guarding against any
  accidental absolute-URL regression elsewhere in the codebase.
