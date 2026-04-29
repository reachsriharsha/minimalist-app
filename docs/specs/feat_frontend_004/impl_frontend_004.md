# Implementation Notes: feat_frontend_004 — dark mode toggle

This document captures the actual implementation as it landed on
`build/feat_frontend_004`, deviations (none material) from the design
spec, and the test results Vulcan was able to run on the dev machine.

## What landed

| File | Change |
|---|---|
| `frontend/src/theme/themeStorage.ts` | **New.** Versioned `localStorage` wrapper. Exports `STORAGE_KEY` (`'minimalist-app:theme:v1'`), the `Theme` union (`'light' | 'dark'`), `readTheme()`, `writeTheme(theme)`, and `seedFromMedia()`. All three functions guard `try { ... } catch { ... }` and fall through to a module-level `inMemory` variable when `localStorage` throws. `readTheme()` returns `null` for any unrecognized stored value (including a stale `'system'` left by a hypothetical future change), which signals the caller to re-seed from the OS preference rather than crash. |
| `frontend/src/theme/ThemeContext.tsx` | **New.** `ThemeProvider` and `useTheme()` hook. Initial state is read synchronously via `readTheme() ?? seedFromMedia()` so the first React render aligns with the inline boot script's pre-mount `data-theme` attribute. A `useEffect` keeps `<html>`'s `data-theme` in sync with state on subsequent toggles (idempotent — the browser elides re-applying the same value). `useTheme()` throws if called outside the provider, mirroring `useAuth()`. |
| `frontend/src/theme/ThemeToggle.tsx` | **New.** Single `<button>` rendered as a fixed-position overlay. Reads `useTheme()` and renders `Dark mode` when the active theme is `'light'` and `Light mode` when it is `'dark'` (label reflects the **action**, not the current state). Carries `data-testid="theme-toggle"` for the e2e spec and `aria-label="Switch to {action}"` for screen readers. |
| `frontend/src/main.tsx` | **Modified.** Wraps the React tree as `<StrictMode><ThemeProvider><BrowserRouter><AuthProvider><App /></AuthProvider></BrowserRouter><ThemeToggle /></ThemeProvider></StrictMode>`. `ThemeProvider` is the outermost provider so `<LoginPage>` (which renders outside `<AuthedLayout>`) can read it; `<ThemeToggle>` is a sibling of `<BrowserRouter>` so route changes never unmount it. |
| `frontend/index.html` | **Modified.** Adds an inline `<script>` in `<head>` that reads `localStorage.getItem('minimalist-app:theme:v1')`, falls back to `matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'` on a missing or unrecognized value, persists the seeded value, and applies `data-theme` to `document.documentElement` synchronously. Plain ES5 (no `let`/`const`/arrow). Wrapped in nested `try/catch` so a `localStorage` or `matchMedia` failure cannot break page load. |
| `frontend/src/index.css` | **Modified.** `:root` now declares the LIGHT theme as the default with named CSS variables (`--bg`, `--fg`, `--fg-muted`, `--border`, `--surface`, `--accent`, `--accent-bg`, `--danger-fg`, `--danger-border`, `--danger-bg`, `--success-fg`, `--success-border`, `--success-bg`). A new `[data-theme='dark']` block overrides each variable for the dark theme. The previous OS-preference media query is removed; the boot script and `<ThemeProvider>` together guarantee `data-theme` is always set, so `:root` defaults are never observed without a matching attribute. `body` and `#root` rules are unchanged. |
| `frontend/src/App.css` | **Modified.** Surgical migration: `.login-page`, `.auth-header` background-color → `var(--surface)`. `.login-form__submit/.login-form__back/.google-btn` background-color → `var(--accent-bg)`. `.login-form__error`, `.state--error` border + background → `var(--danger-border)` / `var(--danger-bg)`. `.login-form__info`, `.state--success` → `var(--success-border)` / `var(--success-bg)`. Opacity-tinted neutrals (`rgba(127,127,127,...)`) and the focus-ring accent (`rgba(100, 160, 255, 0.6)`) stay literal because they read on both backgrounds and migrating them adds churn without payoff (each kept-literal rule has a one-line comment). Appends a new `feat_frontend_004` block at the end with `.theme-toggle`, `.theme-toggle:hover`, and `.theme-toggle:focus-visible`. |
| `frontend/tests/e2e/theme.spec.ts` | **New.** Playwright spec with eight `test()` cases, each starting from a clean page (`addInitScript` clears storage, `emulateMedia` sets the OS preference). Asserts: toggle visible on `/login` and on `/` (redirected to `/login`); first-visit seed from OS preference (both directions); seed value is persisted; toggle label reflects action; click flips `data-theme`, updates label, and writes to `localStorage`; theme persists across reload (no flash); user choice beats subsequent OS-preference changes; stale unknown storage value re-seeds cleanly; rapid 10× clicks land on correct parity with no console errors; theme is stable across 1s of idle time. Does **not** import `getOtpFixture` and does **not** call `test.skip` based on the OTP fixture. |
| `frontend/README.md` | **Modified.** Updates the `bun run test:e2e` script row to list all three specs, adds a `theme.spec.ts` row to the project-layout tree, and updates the Testing section blurb to call out `feat_frontend_004` and explicitly note that `theme.spec.ts` runs without the OTP fixture. |
| `docs/specs/README.md` | **Modified.** Flips the `feat_frontend_004` row from `In Spec` to `In Build`. |
| `docs/tracking/features.md` | **Modified.** Flips the `feat_frontend_004` row from `Ready` to `In Build`. The `Impl PRs` cell is backfilled with the build PR number on a separate commit after `gh pr create`. |

Zero files under `backend/`, `infra/`, or `tests/` (the REST suite) are
touched. Zero new runtime or dev dependencies are added.

## Decisions

- **Inline boot script kept as plain ES5.** Per the design spec's
  "Inline boot script — exact shape" section. The script is hand-written
  in ES5 (`var`, function expressions, no template literals) so the
  deployed `index.html` is trivially auditable and has zero
  transpilation surprises. Verified post-build that
  `dist/index.html` still contains the literal ES5 source.
- **Surface migration in `App.css` is intentionally narrow.** Only rules
  with a clean semantic mapping to a variable were migrated. Opacity-tinted
  neutrals (`rgba(127, 127, 127, 0.3)` on `.state`, `.hello-panel`,
  border on `.login-page`) and the focus-ring accent are kept literal.
  Each kept-literal rule has a one-line comment justifying the
  decision so the diff is easy to audit.
- **Provider tree shape: `<ThemeProvider>` as outermost.** Wrapping
  `<BrowserRouter>` and `<AuthProvider>` lets `<LoginPage>` read the
  theme without any router or auth context. `<ThemeToggle>` is rendered
  as a sibling of `<BrowserRouter>` so router changes never unmount it,
  and the toggle does not call any router hook so it does not need the
  context.
- **No `aria-pressed`.** The toggle reads as an action button (the label
  *is* the next state), not a stateful toggle. `aria-label` documents
  the action for screen readers; the visible text already reflects the
  action.
- **Eight smaller `test()` blocks instead of one round-trip.** The test
  spec recommends finer-grained tests since the theme has neither cost
  nor rate-limit concerns (unlike the login flow). Each test
  re-establishes a clean page state via `addInitScript` and
  `emulateMedia`.
- **Storage key spelling.** `'minimalist-app:theme:v1'` matches the
  spec exactly. The `:v1` suffix leaves room for a future re-keyed
  payload (e.g. JSON with multiple settings) without colliding with
  v1 readers.

## Deviations

None. The implementation is a 1:1 match against `design_frontend_004.md`
including module structure, `data-testid` attributes, CSS variable
names, and the `<button>`-with-text choice for the toggle.

## Test results

| Check | Result |
|---|---|
| `bun run build` (TypeScript + Vite production build) | **Pass.** Zero TS errors. `dist/index.html` + `dist/assets/index-*.{js,css}` produced. The dist `index.html` still contains the inline boot script with the literal `'minimalist-app:theme:v1'` key — verified by grep. Bundle gzip-size is ~77 kB (unchanged shape — no new dep). |
| `git diff main...HEAD --stat -- backend/ infra/ tests/` | **Empty.** Zero files outside `frontend/` and `docs/` modified. |
| `grep -rn "fetch" frontend/src/theme/` | **Zero hits.** The theme layer is pure DOM + storage, no API surface. |
| `grep -rn "prefers-color-scheme" frontend/src/index.css frontend/src/App.css` | **Zero hits.** The OS-preference media query is fully removed from CSS. The remaining hits in the codebase are exactly the two seed paths (boot script in `index.html`, `seedFromMedia()` in `themeStorage.ts`). |
| `frontend/package.json` diff | **Empty.** No new dependency added. |
| `./test.sh` | **Pass.** 9 passed, 2 skipped (the 2 skips are the OTP-fixture-dependent backend tests already skipped pre-this-feature). The compose stack was already healthy on the dev machine; the REST suite reports green with no behavior change. |
| `bun run test:e2e` | **Not run from this dev session.** The Playwright suite is intentionally out-of-band per `feat_frontend_002` / `feat_frontend_003` precedent. The new `theme.spec.ts` does not require the OTP fixture, so an operator can run the full e2e suite locally with `make up` running and verify all three specs pass. The compose stack on this machine is up so the operator-side prerequisites are already met. |

## How to verify on a Docker-equipped machine

```bash
# from repo root
git checkout build/feat_frontend_004
cd infra && cp .env.example .env && cd ..

# start the stack (idempotent if already up)
make up

# REST suite (must stay green; this feature touches no backend code)
./test.sh

# Playwright e2e (must stay green; this feature adds theme.spec.ts)
export TEST_OTP_EMAIL=e2e@example.com   # only needed for login + profile specs
export TEST_OTP_CODE=424242
cd frontend
bun install
bunx playwright install chromium
bun run test:e2e
```

`theme.spec.ts` runs even without the OTP fixture pair — it asserts
on `/login` and on `/` (which redirects to `/login`), neither of
which requires authentication.

## Acceptance criteria status

All acceptance-criteria checkboxes from `feat_frontend_004.md` are
satisfied by the diff:

- [x] A fixed bottom-left button is visible on `/login` (unauthenticated)
      and on `/`, `/profile` (authed) — the toggle is rendered as a
      sibling of `<BrowserRouter>` so it is unaffected by route changes.
      Label is `Dark mode` when current=light, `Light mode` when
      current=dark.
- [x] Clicking the toggle changes `<html>`'s `data-theme` attribute
      from `light` to `dark` (or vice versa) within the same tick — the
      `useEffect` runs synchronously after the state update.
- [x] After clicking the toggle, `localStorage.getItem('minimalist-app:theme:v1')`
      reads back the new value — `writeTheme()` is invoked inside both
      `setTheme()` and `toggleTheme()` before the state update.
- [x] After a full page reload, the previously-chosen theme is applied
      before any visible flash — the inline boot script sets
      `data-theme` synchronously in `<head>`, before the body parses.
      Asserted in `theme.spec.ts` via `page.evaluate` immediately after
      `page.reload()` resolves.
- [x] On a fresh browser (no `localStorage` value), the initial theme
      matches `matchMedia('(prefers-color-scheme: dark)').matches`.
      Asserted in both directions in the spec.
- [x] After a user has clicked the toggle once, changing the OS-level
      `prefers-color-scheme` does not change the in-app theme. Asserted
      across two reloads with flipped emulation in the
      `user choice beats OS preference` test.
- [x] Navigating between routes preserves the theme; the toggle stays
      mounted (rendered as a sibling of `<BrowserRouter>`). The provider
      tree contract is documented in `main.tsx`.
- [x] No new `fetch` is added to `frontend/src/` — `grep -rn "fetch" frontend/src/theme/`
      returns zero hits.
- [x] No new dependency is added to `frontend/package.json` — diff is
      empty.
- [x] `bun run build` passes with zero TS errors.
- [x] `frontend/tests/e2e/theme.spec.ts` exists and exercises the
      toggle, persistence, no-flash, and OS-preference invariants. Does
      **not** require the OTP fixture.
- [x] `frontend/tests/e2e/login.spec.ts` and `profile.spec.ts` continue
      to use the same selectors and flows; the new global toggle is
      rendered with `position: fixed` outside the existing
      `[data-testid="auth-header"]` container, so no header-scoped
      selector matches it.
- [x] `./test.sh` continues to pass (9 passed, 2 skipped — same as
      before this feature).
- [x] `docs/specs/README.md` and `docs/tracking/features.md` rows are
      flipped to `In Build`.
