# Changelog: feat_frontend_004

## Added

- **In-app dark/light theme toggle.** A fixed bottom-left button
  is rendered on every page (authed and unauthenticated, including
  `/login` and the bootstrap-loading state) so users can switch
  themes without hunting for a settings menu. The toggle has exactly
  two states — `light` and `dark` — and the label reflects the
  **action** rather than the current state (`Dark mode` when the
  active theme is light, `Light mode` when it is dark).
- **`themeStorage` module** at `frontend/src/theme/themeStorage.ts`.
  Versioned `localStorage` wrapper exposing `STORAGE_KEY`
  (`'minimalist-app:theme:v1'`), the `Theme` union, `readTheme()`,
  `writeTheme()`, and `seedFromMedia()`. All three functions guard
  `try / catch` against `localStorage` and `matchMedia` failures
  (private windows, quota errors, Safari ITP) and fall back to a
  module-level in-memory variable so the theme stays functional
  within a single page load even when storage is disabled.
  `readTheme()` returns `null` for any unrecognized stored value,
  signaling the caller to re-seed from the OS preference rather
  than crash.
- **`ThemeContext`** at `frontend/src/theme/ThemeContext.tsx`.
  `ThemeProvider` owns the in-memory theme state and applies
  `data-theme` to `<html>` on every change. `useTheme()` returns
  `{ theme, setTheme, toggleTheme }` and throws when called outside
  the provider, mirroring `useAuth()`.
- **`ThemeToggle` component** at `frontend/src/theme/ThemeToggle.tsx`.
  A single `<button>` styled as a fixed-position overlay; reads
  `useTheme()` and dispatches `toggleTheme()` on click. Carries
  `data-testid="theme-toggle"` for the e2e spec and `aria-label`
  for screen readers.
- **Inline boot script in `frontend/index.html`.** Reads the
  persisted theme (or seeds it from `prefers-color-scheme`) and
  applies the `data-theme` attribute on `<html>` synchronously,
  before React mounts. Eliminates the wrong-theme flash on reload.
  Plain ES5 with nested `try / catch` so a storage or media-query
  failure cannot break page load.
- **CSS-variable palette** in `frontend/src/index.css`. New
  variables: `--bg`, `--fg`, `--fg-muted`, `--border`, `--surface`,
  `--accent`, `--accent-bg`, `--danger-fg`, `--danger-border`,
  `--danger-bg`, `--success-fg`, `--success-border`, `--success-bg`.
  Light values declared on `:root` (the default); dark values
  override under `[data-theme='dark']`.
- **Theme-toggle CSS** in `frontend/src/App.css` under a new
  `feat_frontend_004` block: `.theme-toggle` (fixed position,
  bottom-left, low z-index), `.theme-toggle:hover`, and
  `.theme-toggle:focus-visible`.
- **Playwright e2e spec** at `frontend/tests/e2e/theme.spec.ts`.
  Eight test cases covering the toggle, persistence, no-flash on
  reload, OS-preference seed in both directions, user-choice
  stickiness, stale-unknown-value re-seed, rapid-click parity, and
  idle stability. Does **not** import `getOtpFixture` and does
  **not** call `test.skip` on a missing OTP fixture — every
  assertion runs on `/login` (unauthenticated) or on `/` (which
  redirects to `/login`).

## Changed

- **`frontend/src/main.tsx`.** Provider tree becomes
  `<StrictMode><ThemeProvider><BrowserRouter><AuthProvider><App /></AuthProvider></BrowserRouter><ThemeToggle /></ThemeProvider></StrictMode>`.
  `<ThemeProvider>` is the outermost provider so every subtree —
  including `<LoginPage>` — can read the theme. `<ThemeToggle>` is
  rendered as a sibling of `<BrowserRouter>` so route changes never
  unmount it.
- **`frontend/src/index.css`.** `:root` is now the LIGHT theme by
  default. The previous OS-preference media query is removed; the
  inline boot script and `<ThemeProvider>` together guarantee
  `data-theme` is always set on `<html>`, so the `:root` defaults
  are never observed without a matching attribute. `color-scheme`
  remains `light dark` so native form controls pick a sensible
  default. `body` and `#root` rules are unchanged.
- **`frontend/src/App.css`.** Surgical migration of color literals
  to CSS variables where the migration is clean: `.login-page` and
  `.auth-header` background-color use `var(--surface)`;
  `.login-form__submit / .login-form__back / .google-btn`
  background-color uses `var(--accent-bg)`; `.login-form__error`
  and `.state--error` use `var(--danger-border)` /
  `var(--danger-bg)`; `.login-form__info` and `.state--success`
  use `var(--success-border)` / `var(--success-bg)`.
  Opacity-tinted neutrals and the focus-ring accent are kept
  literal (each with a one-line comment). No selector is renamed,
  no markup is restructured.
- **`frontend/index.html`.** New inline `<script>` block in
  `<head>` runs the synchronous theme seed before React mounts.
- **`frontend/README.md`.** Updates the `bun run test:e2e` row in
  the scripts table to list all three specs, adds `theme.spec.ts`
  to the project-layout tree, and updates the Testing section
  blurb to call out `feat_frontend_004` and explicitly note that
  `theme.spec.ts` runs without the OTP fixture.
- **`docs/tracking/features.md` and `docs/specs/README.md`.** The
  `feat_frontend_004` row advances from `Ready` / `In Spec` to
  `In Build`.

## Removed

- **`@media (prefers-color-scheme: light)` block in `index.css`.**
  The OS preference is now consulted exactly once on first visit
  (by the boot script and `themeStorage.seedFromMedia`) and then
  persisted; subsequent loads read `localStorage` and never touch
  the media query. This is the explicit design — the user's
  in-app choice is sticky.

## Unchanged

- **Zero backend changes.** No file under `backend/`, `infra/`,
  or `tests/` (the REST suite) is modified. No new endpoints, no
  new schema, no new request/response shape.
- **Zero new dependencies.** `frontend/package.json` is unmodified.
  All work uses `react`, `react-dom`, `react-router-dom@^7`, and
  `@playwright/test@^1`, all already pulled in by earlier features.
- **Existing `/login` and `/` and `/profile` flows.** No assertion
  in `login.spec.ts` or `profile.spec.ts` needed to change. The
  global toggle is rendered with `position: fixed` outside the
  existing `[data-testid="auth-header"]` container, so no
  header-scoped selector matches it.
- **`./test.sh` behavior.** Provable by zero diff under `backend/`,
  `infra/`, `tests/`. Confirmed: 9 passed, 2 skipped (same shape
  as pre-this-feature; the 2 skips are OTP-fixture-dependent
  backend tests).
- **Component visuals on the dark theme.** The dark palette under
  `[data-theme='dark']` mirrors today's hard-coded values
  pixel-for-pixel where the migration was clean and reads
  acceptably elsewhere. The previous look is preserved for users
  who keep the dark theme.

## Security

- **No new API surface.** Zero new `fetch` calls, zero new request
  bodies, zero new response shapes. The threat model from
  `feat_frontend_003` carries forward unchanged.
- **No PII in `localStorage`.** The stored value is exactly one of
  `'light'` or `'dark'`. Nothing user-identifying.
- **No XSS via theme value.** The `data-theme` attribute is set via
  `setAttribute`, never via `innerHTML`. The value is constrained
  to two literals; unrecognized stored values are rejected by
  `themeStorage.readTheme()` (returns `null`, callers re-seed).
- **Inline `<script>` in `index.html`.** Currently the only inline
  script in the project. It does not interpolate any
  user-controlled data. A future CSP-hardening feature will need
  to either hash this script or move it to an external file; out
  of scope here.
- **No `eval`, no `Function()`, no dynamic imports.** The theme
  layer is pure DOM + storage.
- **No third-party origins.** The toggle does not reach out to
  any CDN, font service, or analytics endpoint.
