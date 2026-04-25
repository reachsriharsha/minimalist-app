# Design: Profile page — `/profile` route, header Profile button, email-only view

## Approach

This feature reuses every shell that `feat_frontend_002` already shipped:

- `AuthProvider` already exposes `user` (`Me | null`) and `status`.
- `<RequireAuth>` already gates authed routes.
- `<AuthedLayout>` already wraps authed routes with the persistent
  `<Header>`.
- `react-router-dom@^7` already drives navigation.

What changes:

1. `<Header>` gets a new leftmost element: a plain-text **Profile**
   button that calls `useNavigate()` to push `/profile`.
2. `App.tsx` gains one more `<Route>` at `/profile`, gated identically
   to `/`.
3. A new page component `ProfilePage` reads the email from
   `useAuth().user.email` and renders it. It also handles the
   `status === 'loading'` case with a plain-text placeholder, even
   though `<RequireAuth>` will normally never let it render in that
   state — the placeholder is a defensive belt-and-braces (the user
   asked for a visible loading affordance, so we provide one even
   though the gate already covers most cases).
4. A new Playwright spec `profile.spec.ts` exercises the round trip.

The implementation is intentionally tiny. There is no new API client,
no new hook, no new context. The data already lives in
`AuthContext.user`; the page only reads it.

## Files to Modify

| File | Change Description |
|---|---|
| `frontend/src/components/Header.tsx` | Prepend a plain-text **Profile** button as the leftmost child of the `<header>` element. The button is `<button type="button" onClick={() => navigate('/profile')}>Profile</button>` (or an equivalent `<Link>`; see "Profile button: `<button>` vs `<Link>`" below for the choice). Add a `data-testid="auth-header-profile"` for the e2e spec. The existing email span, roles list, and logout button move one slot to the right but otherwise are unchanged. |
| `frontend/src/App.tsx` | Add `import ProfilePage from './pages/ProfilePage';` and a new `<Route path="/profile" element={<RequireAuth><AuthedLayout><ProfilePage /></AuthedLayout></RequireAuth>} />`. Order it after the `/` route and before the `*` catch-all. Do not touch the existing `/` and `/login` routes. |
| `frontend/src/App.css` | Add a `.auth-header__profile` class mirroring `.auth-header__logout` (plain-text-styled button: same padding, same border, same background-transparent, same cursor). Add `.profile-page` styles consistent with `.dashboard` (left-aligned, max-width container). The new classes do not touch any existing selector. |
| `frontend/README.md` | In the existing **Testing** section (added by `feat_frontend_002`), update the bullet that lists the e2e specs to include `profile.spec.ts` alongside `login.spec.ts`. No other README changes. |
| `docs/specs/README.md` | Append a row to the feature roster table for `feat_frontend_003`. |
| `docs/tracking/features.md` | Append a row for `feat_frontend_003`. Backfill the Spec PR + Issues columns after `gh pr create` and `gh issue create`. |

## Files to Create

| File | Purpose |
|---|---|
| `frontend/src/pages/ProfilePage.tsx` | The `/profile` route component. Reads `useAuth()`. Renders `<h1>Profile</h1>` plus a single element holding the email value. Renders a `Loading…` placeholder when `status === 'loading'`. Renders nothing (or a defensive null) if `user === null` while `status === 'authenticated'` — should not happen in practice. Default-export so it matches the `Dashboard.tsx` and `LoginPage.tsx` import style in `App.tsx`. |
| `frontend/tests/e2e/profile.spec.ts` | The new Playwright spec. Mirrors the structure of `login.spec.ts`: imports `getOtpFixture()` from `./fixtures.ts`, calls `test.skip(fixture === null, …)`, then runs one or more tests covering the profile flow. See the **Playwright spec contract** section below for assertion details. |

No file is deleted. No file under `backend/`, `infra/`, or `tests/`
(REST suite) is touched.

## Profile button: `<button>` vs `<Link>`

Two reasonable shapes for the Profile element exist in
`react-router-dom@7`:

1. `<button type="button" onClick={() => navigate('/profile')}>Profile</button>`
2. `<Link to="/profile">Profile</Link>` styled to look like the
   existing buttons.

**Vulcan picks option 1 (`<button>`)** for symmetry with the existing
Logout element in `<Header>`, which is also a `<button>` that hooks
into router state via a callback. The two adjacent header elements
should look and behave the same; using `<Link>` for one and `<button>`
for the other would produce subtly different keyboard / focus
semantics.

If a future feature adds nav-active styling (highlighting the current
route), that change can switch both to `<Link>` / `<NavLink>` in one
go. This feature does not pre-emptively make that change.

## Data Flow

```mermaid
sequenceDiagram
    actor User
    participant Browser
    participant Header
    participant Router as react-router-dom
    participant Profile as ProfilePage
    participant AuthCtx as AuthContext

    Note over User,Browser: Already on / (dashboard)
    User->>Header: click "Profile"
    Header->>Router: navigate('/profile')
    Router->>Router: push history entry
    Router->>Profile: mount
    Profile->>AuthCtx: useAuth()
    AuthCtx-->>Profile: { user, status: 'authenticated' }
    Profile->>Profile: render <h1>Profile</h1> + email
    Profile-->>User: page rendered

    Note over User,Browser: Click Profile again on /profile
    User->>Header: click "Profile" (still rendered)
    Header->>Router: navigate('/profile')
    Router->>Router: same URL — no-op (no remount, no extra render
                     beyond router internals)
    Router-->>User: still on /profile
```

Note the absence of any `fetch` call in the diagram. The profile page
neither hits `/auth/me` nor any other backend endpoint — it reads from
`AuthContext.user`, which was already populated during the
`AuthProvider` bootstrap.

## Component sketch — `ProfilePage.tsx`

```tsx
import { useAuth } from '../auth/AuthContext';

export default function ProfilePage() {
  const { user, status } = useAuth();

  if (status === 'loading') {
    return (
      <div
        className="state state--loading profile-loading"
        role="status"
        aria-live="polite"
        data-testid="profile-loading"
      >
        Loading…
      </div>
    );
  }

  if (user === null) {
    // Defensive — <RequireAuth> guarantees this never fires under
    // normal flow. Render nothing rather than crash.
    return null;
  }

  return (
    <div className="profile-page" data-testid="profile-page">
      <h1 className="profile-page__title">Profile</h1>
      <p className="profile-page__email" data-testid="profile-page-email">
        {user.email}
      </p>
    </div>
  );
}
```

A `<p>` is a reasonable element choice because the value sits on its
own line as a paragraph. Vulcan may use `<span>` or `<div>` if a stronger
case emerges; the test spec keys off the `data-testid`, not the tag.

## Component sketch — updated `Header.tsx`

The existing `<Header>` body becomes:

```tsx
return (
  <header className="auth-header" data-testid="auth-header">
    <button
      type="button"
      className="auth-header__profile"
      onClick={() => navigate('/profile')}
      data-testid="auth-header-profile"
    >
      Profile
    </button>
    <span className="auth-header__email" data-testid="auth-header-email">
      {user.email}
    </span>
    <ul className="auth-header__roles" data-testid="auth-header-roles">
      {user.roles.map((role) => (
        <li key={role} className="role-chip" data-role={role}>
          {role}
        </li>
      ))}
    </ul>
    <button
      type="button"
      className="auth-header__logout"
      onClick={handleLogout}
      disabled={loggingOut}
      data-testid="auth-header-logout"
    >
      {loggingOut ? 'Signing out…' : 'Logout'}
    </button>
  </header>
);
```

`useNavigate()` is added at the top of the component:

```tsx
import { useNavigate } from 'react-router-dom';

export function Header() {
  const { user, logout } = useAuth();
  const [loggingOut, setLoggingOut] = useState(false);
  const navigate = useNavigate();
  // ...
}
```

The `flex: 1` rule on `.auth-header__roles` already pushes the role
list to take the remaining space, which keeps Logout at the right
edge after the new Profile element is prepended at the left edge. No
flex layout changes are needed.

## CSS additions — App.css

```css
/* ---- feat_frontend_003: profile button + page ------------------------- */

.auth-header__profile {
  padding: 0.4rem 0.85rem;
  font-size: 0.9rem;
  border-radius: 0.4rem;
  border: 1px solid rgba(127, 127, 127, 0.4);
  background-color: transparent;
  color: inherit;
  cursor: pointer;
  font-family: inherit;
}

.auth-header__profile:focus-visible {
  outline: 2px solid rgba(100, 160, 255, 0.6);
  outline-offset: 1px;
}

.profile-page {
  max-width: 42rem;
}

.profile-page__title {
  margin-top: 0;
  margin-bottom: 1rem;
  font-size: 1.5rem;
}

.profile-page__email {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  margin: 0;
}

.profile-loading {
  margin: 4rem auto;
  max-width: 20rem;
  text-align: center;
}
```

The `.auth-header__profile` selector deliberately mirrors
`.auth-header__logout` so the two header buttons read as a matched
pair. The monospace font on `.profile-page__email` is consistent with
the existing `.state dd` rule (the only other place in the app where a
raw value is rendered without a label).

## Routing contract update

After this feature, `App.tsx` declares:

```tsx
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
  <Route
    path="/profile"
    element={
      <RequireAuth>
        <AuthedLayout>
          <ProfilePage />
        </AuthedLayout>
      </RequireAuth>
    }
  />
  <Route path="*" element={<Navigate to="/" replace />} />
</Routes>
```

The `<RequireAuth>` and `<AuthedLayout>` wrappers are duplicated rather
than hoisted into a layout route. Vulcan may refactor to a layout route
(`<Route element={<RequireAuth><AuthedLayout /></RequireAuth>}>` with
`<Outlet />` inside `AuthedLayout`) **only if** the change can be made
without behavior drift and without touching `feat_frontend_002`'s
existing route assertions. If in doubt, keep the duplicated form — the
two-route version is still small enough that the duplication cost is
lower than the refactor cost.

## Playwright spec contract — `profile.spec.ts`

The new spec follows the same structural pattern as `login.spec.ts`:

```ts
import { test, expect, type Request } from '@playwright/test';
import { getOtpFixture } from './fixtures';

const fixture = getOtpFixture();

test.describe('profile flow', () => {
  test.skip(fixture === null, 'TEST_OTP_EMAIL / TEST_OTP_CODE not set');

  test('navigate to /profile, see email, logout', async ({ page, baseURL }) => {
    if (fixture === null) return;

    // 1. Sign in via the OTP fixture (helper extracted into the spec
    //    body or imported from a small shared module — Vulcan picks).
    // 2. Assert we are on / (the dashboard).
    // 3. Assert the header has a Profile button at the leftmost slot
    //    (data-testid="auth-header-profile") and that it is enabled.
    // 4. Click Profile.
    // 5. Assert page.url() ends with /profile.
    // 6. Assert the profile page heading and email are visible:
    //    expect(page.getByTestId('profile-page-email')).toHaveText(fixture.email)
    // 7. Click Profile again (still on /profile). Assert URL is still
    //    /profile, no error toast, no console error.
    // 8. Click Logout. Assert URL becomes /login.
    // 9. Optional but recommended: also assert the relative-URL
    //    invariant for any /api/v1/* requests that fired during the run
    //    (mirrors login.spec.ts happy-path #11).
  });
});
```

The login helper (steps 1–2) may be:

- Inlined in this spec file (simplest, ~15 lines, copy from
  `login.spec.ts`), **or**
- Extracted into a new `frontend/tests/e2e/helpers.ts` module and
  imported by both specs.

Vulcan picks based on diff size at build time. A shared helper is
preferred if the inline copy would exceed ~20 lines; otherwise inlined
is fine. Either choice is acceptable; the test spec asserts behavior,
not file structure.

### Why the spec re-runs the login flow

The Playwright runner does not share storage state between `*.spec.ts`
files by default, and we deliberately do **not** introduce a global
auth fixture in this feature (that's a future test-infra refactor).
Each spec drives login itself. The cost is small — login is about ~5
seconds — and isolating specs avoids inter-test ordering pitfalls.

## Edge Cases & Risks

| Risk | Mitigation |
|---|---|
| `<Header>` is rendered before `user` is populated and the Profile button appears with a stale email next to it. | The existing `<Header>` early-returns `null` when `user === null`, so the Profile button never renders without a populated `user`. New code preserves this guard. |
| User clicks Profile rapidly multiple times — does it pile up history entries? | `useNavigate()` defaults to `push`. Multiple identical pushes (`/profile` -> `/profile` -> `/profile`) are no-ops at the URL level (same pathname); browsers and `react-router-dom` do not stack identical history entries beyond the first. Acceptable. |
| Click on Profile while on `/profile` triggers a re-render of `ProfilePage` and re-fires any side effects. | `ProfilePage` has no `useEffect` and no fetch, so a re-render is observably free (just re-reads `useAuth()`). |
| The user's email contains characters that need escaping (e.g. `<`, `>`, `"`). | React escapes text-children automatically. Rendering `{user.email}` is safe. No `dangerouslySetInnerHTML` is used. |
| `feat_frontend_002` is not yet merged when Vulcan starts the build. | Build branch is cut **after** `feat_frontend_002` lands on `main`. Atlas explicitly notes the dependency in the feature spec. |
| `feat_frontend_002`'s files diverge before merge (e.g. Header restructuring), invalidating this design's edit anchors. | Design references file *names* and component shapes, not line numbers. If a fundamental restructuring lands (e.g. Header is renamed, or AuthContext stops exposing `user.email`), Vulcan stops and escalates. |
| `<RequireAuth>` is bypassed somehow and `ProfilePage` renders with `user === null`. | `ProfilePage` returns `null` defensively in that branch. No crash, no exception. |
| Tab-order regression: the new Profile button at the left changes keyboard navigation order in the header. | This is the desired behavior. The leftmost element is the first focusable; a user tabbing through the header now hits Profile first, then email span (not focusable), then role chips (not focusable), then Logout. The order matches visual reading order. |
| Loading-text wording diverges from the rest of the app. | The text `Loading…` (with the ellipsis character) matches `<RequireAuth>`'s existing copy and the project's bland-Vite tone. Vulcan keeps it consistent. |
| Test fixture (`TEST_OTP_*`) is not set when running the e2e suite locally. | `test.skip` mirrors `login.spec.ts`. The test prints a clean skip; no red failure. |
| Two e2e specs both drive login and rate-limit each other (`POST /auth/otp/request` 429s on the second one). | `feat_frontend_002` already documents this risk and mitigation: each spec calls `test.skip('rate-limited; retry later')` if it sees a 429 on the OTP request. The new spec follows the same pattern. |
| `react-router-dom@7`'s `<Link>` and `useNavigate()` mixed in the same component cause subtle history bugs. | Not a concern — the new `useNavigate()` call is in a click handler, no `<Link>` is added. |

## Dependencies

- **Hard:** `feat_frontend_002` merged to `main` first.
- **Runtime (no new):** `react-router-dom@^7` (already a dependency
  after `feat_frontend_002`).
- **Dev (no new):** `@playwright/test@^1` (already a dev dependency
  after `feat_frontend_002`).
- **External tools (no new):** Playwright browsers, already installed
  by operators per `feat_frontend_002`'s README instructions.
- **Backend:** unchanged. No new endpoints, no schema changes.

## Deviations

- **Email rendered without a label.** The user explicitly asked for
  "just email" — the page shows the email value as a bare paragraph.
  A label like `Email:` was considered and rejected per the user's
  guidance. The page-level `<h1>Profile</h1>` heading is kept for
  accessibility and page-title semantics; this is the only piece of
  framing text on the page body.
- **Profile button stays active on `/profile`.** The user explicitly
  confirmed this. Adding nav-active styling is deferred to a future
  feature (likely whichever feature lands a third authed route).
- **No duplicate logout on the profile page.** Logout remains in
  `<Header>`, which is on every authed page including `/profile`. The
  user confirmed this interpretation.
- **Loading-state placeholder is plain text.** The user explicitly
  rejected a spinner library; a `Loading…` text placeholder matches
  the existing `<RequireAuth>` skeleton and the bland Vite default
  styling.
- **Directory and filename use `feat_<domain>_<NNN>` only.** Matches
  `conventions.md` §2 and every existing sibling. No slug suffix.
- **Branch name has no slug.** `spec/feat_frontend_003`, per
  `conventions.md` §3.
