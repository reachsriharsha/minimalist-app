# Test Spec: Dark mode — fixed bottom-left toggle, two-state light/dark, persisted

## Test harness

This feature ships **Playwright e2e tests only** — consistent with
`feat_frontend_002` and `feat_frontend_003`. No Vitest, no React
Testing Library, no component tests. The runner targets the
compose-brought-up stack (`make up` from the repo root) and drives
Chromium against `http://localhost:5173` (or `PLAYWRIGHT_BASE_URL`).

- Location: `frontend/tests/e2e/theme.spec.ts` (new, this feature).
- Existing infrastructure reused (no changes):
  - `frontend/playwright.config.ts`
  - `bun run test:e2e` script in `frontend/package.json`
- The new spec **does not import `getOtpFixture`** and does **not**
  perform an OTP login. It runs all assertions on `/login`
  (unauthenticated) and on the `/login` page reached via redirect
  from `/`. There is no `test.skip` based on a missing OTP fixture.
- The new spec uses `page.emulateMedia({ colorScheme: 'dark' | 'light' })`
  to control the seed-from-OS path and `page.addInitScript()` to
  clear `localStorage` before each scenario.
- `./test.sh` is unchanged and does **not** invoke Playwright.
- Existing specs (`login.spec.ts`, `profile.spec.ts`) must continue to
  pass unchanged. They do not need theme-related modifications.

## Happy Path

| # | Test Case | Input | Expected Output |
|---|---|---|---|
| 1 | Toggle button visible on `/login` | `await page.goto('/login')` (clean storage) | `page.getByTestId('theme-toggle')` is visible. |
| 2 | Toggle button visible on `/` (which redirects to `/login`) | `await page.goto('/')` (clean storage) | URL becomes `/login`; toggle is visible. |
| 3 | First-visit seed: OS dark -> theme dark | `emulateMedia({ colorScheme: 'dark' })`, clear storage, `goto('/login')` | `document.documentElement.getAttribute('data-theme') === 'dark'`. |
| 4 | First-visit seed: OS light -> theme light | `emulateMedia({ colorScheme: 'light' })`, clear storage, `goto('/login')` | `document.documentElement.getAttribute('data-theme') === 'light'`. |
| 5 | First-visit seed writes to localStorage | After Test #3 | `localStorage.getItem('minimalist-app:theme:v1') === 'dark'`. |
| 6 | Toggle button label reflects action (light current) | OS=light, clean storage, `goto('/login')` | Toggle button text content is exactly `Dark mode`. |
| 7 | Toggle button label reflects action (dark current) | OS=dark, clean storage, `goto('/login')` | Toggle button text content is exactly `Light mode`. |
| 8 | Click toggle flips data-theme | OS=light, clean storage, `goto('/login')`, click toggle | `data-theme` becomes `dark` within the same tick (assert without an explicit wait beyond Playwright's auto-waiting). |
| 9 | Click toggle updates label | OS=light, clean storage, `goto('/login')`, click toggle | Toggle button text content becomes exactly `Light mode`. |
| 10 | Click toggle persists to localStorage | After Test #8 | `localStorage.getItem('minimalist-app:theme:v1') === 'dark'`. |
| 11 | Theme persists across reload | OS=light, clean storage, `goto('/login')`, click toggle, `page.reload()` | `data-theme` is `dark` immediately after reload (asserted via `page.evaluate` right after `reload()` resolves, no interaction in between). |
| 12 | User choice beats OS preference | OS=light, clean storage, `goto('/login')`, click toggle (now dark), `emulateMedia({ colorScheme: 'light' })`, `reload()` | `data-theme` is still `dark`. |
| 13 | OS-preference change while open does not change theme | After Test #12, in the same page, change emulation back and forth | The `data-theme` attribute remains the user's stored value across both emulations until the user clicks the toggle. |
| 14 | Toggle stays mounted across route transitions | OS=light, clean storage; assume an authed flow is not required for this assertion: navigate `/login` -> manually `goto('/profile')` (which redirects to `/login`); the toggle element returned by `getByTestId` is the same DOM node throughout (assertable via `evaluate` getting `outerHTML` and a stable reference). | The toggle remains visible; no console error. |
| 15 | Two themes leave existing e2e specs green | Run `bun run test:e2e` end-to-end (login + profile + theme) | All three specs pass. The login and profile specs do not reference the toggle; their selectors and assertions are unaffected. |
| 16 | No new fetch calls are made by the theme layer | OS=light, clean storage, `goto('/login')`, click toggle five times | `page.on('request', ...)` log shows zero requests from any URL containing `/api/v1/`. (The page itself triggers an initial bootstrap `/auth/me`; the theme toggling causes no additional traffic.) |

The spec ships **multiple smaller `test()` blocks** rather than one
giant round-trip. Each test starts with a fresh page (`addInitScript`
clears storage, `emulateMedia` sets the OS preference), so they are
independent of order. This differs from `login.spec.ts`'s
single-test-per-spec choice, which only made sense there because of
the rate-limit + login-cost concern. Theme tests have neither cost
nor rate-limit, so finer-grained tests are clearer.

## Error Cases

| # | Test Case | Input | Expected Behavior |
|---|---|---|---|
| 1 | localStorage throws on read | Manually wrap `localStorage.getItem` to throw, reload | Boot script catches; falls back to OS preference; `data-theme` is set. App does not crash. (Hard to test in Playwright without monkey-patching pre-load — documented as a property of the boot script + `themeStorage` design; not asserted in CI.) |
| 2 | localStorage throws on write | Quota exceeded simulated via `addInitScript` to override `setItem` | `themeStorage.writeTheme` catches; in-memory fallback holds the value for the session. The `data-theme` attribute still flips on click. (Documented; optional Playwright assertion.) |
| 3 | localStorage contains a stale unknown value (e.g. `'system'`) | `addInitScript` -> `localStorage.setItem('minimalist-app:theme:v1', 'system')`, OS=light, `goto('/login')` | Boot script does not match `'light'` or `'dark'`, falls through to OS-preference branch, writes `'light'` back to storage, sets `data-theme="light"`. (Required assertion.) |
| 4 | The toggle is clicked rapidly (10 clicks in a tight loop) | Programmatic `click()` x10 with no wait | The final `data-theme` matches the parity of the click count (10 clicks from `light` -> `light`). No console error, no React state desync. (Required assertion.) |
| 5 | `<html>` had `data-theme` removed by an external script before React mounts | Synthetic — not a real flow | The provider's `useEffect` re-applies `data-theme` on next state change. Documented; not asserted. |
| 6 | The user is in a private window | Real-world but not directly testable in a stock Playwright run | The boot script's `try/catch` and `themeStorage`'s in-memory fallback together keep the theme functional within the session. Documented; not asserted in CI. |

## Boundary Conditions

| # | Test Case | Condition | Expected Behavior |
|---|---|---|---|
| 1 | First visit with `matchMedia` undefined (very old browser) | Synthetic — Playwright targets modern Chromium | Boot script's `typeof window.matchMedia === 'function'` guard returns `false`; theme defaults to `light`. Documented; not asserted. |
| 2 | Theme value matches `data-theme` after a single full second of idle time | `goto('/login')`, wait 1s, assert | `data-theme` is unchanged. (Verifies no late effect or interval is overwriting the attribute.) |
| 3 | Multiple `<html data-theme>` writers (boot script + provider) converge | `goto('/login')`, observe via `MutationObserver` (synthetic) | The attribute may be set twice in rapid succession (boot script, then the provider's effect on first mount), but the final value is the same. Documented; not asserted unless a flake materializes. |
| 4 | `bun run build` produces a `dist/` with the inline script intact | Run `bun run build` locally during the build | The compiled `dist/index.html` contains the inline boot script's content (or an inlined-and-minified equivalent that still runs the same logic). Vulcan asserts during the build, not in Playwright. |
| 5 | Stack not up | Backend not running when Playwright launches | First navigation to `/login` times out. Same operator-side prerequisite as the existing specs. |
| 6 | Prod-profile frontend | `PLAYWRIGHT_BASE_URL=http://localhost:8080 bun run test:e2e` | Same theme spec passes; the boot script is part of the prod bundle's `index.html`. |
| 7 | The toggle button is keyboard-reachable | Tab from a fresh `goto('/login')` until focus lands on the toggle | The toggle is reachable via Tab. It receives a visible focus ring (`:focus-visible`). Documented; not strictly asserted unless flaking. |
| 8 | Theme value is preserved across two open tabs (no cross-tab sync) | Open Tab A and Tab B on `/login`; toggle in A; reload B | Tab B reflects the new theme on reload (because it re-reads `localStorage`). It does **not** auto-update without a reload — by design. (Documented; optional assertion.) |
| 9 | Light theme contrast is acceptable | Manual visual check | Body text on body bg passes WCAG AA; error/info banners are readable. Vulcan inspects screenshots during the build and includes them in the PR description. |
| 10 | Dark theme matches today's look | Manual visual check | The dark theme is visually indistinguishable from the current build for header strip, login form, dashboard, profile page (modulo the new toggle button). |

## Security Considerations

- **No new API surface.** The theme layer is pure-frontend. No new
  `fetch`, no new request body, no new response shape, no new
  endpoint to authenticate.
- **No PII in `localStorage`.** The stored value is exactly one of
  `'light'` or `'dark'`. Nothing user-identifying.
- **No XSS via theme value.** The `data-theme` attribute is set via
  `setAttribute`, never via `innerHTML`. The value is constrained to
  one of two literals; unrecognized values are rejected by
  `themeStorage.readTheme()` (returns `null`).
- **Inline `<script>` in `index.html`.** This is the only inline
  script in the project. It does not interpolate any user-controlled
  data. A future CSP-hardening feature must either hash this script
  or move it to an external file; out of scope here.
- **No `eval`, no `Function()`, no dynamic imports.** The theme layer
  is pure DOM + storage.
- **No third-party origins.** The toggle does not reach out to any
  CDN, font service, or analytics endpoint.
- **`localStorage` quota.** The single key holds at most six
  characters; quota concerns are nil. The `try/catch` around
  `setItem` is defensive against unrelated quota issues caused by
  other tabs / origins / extensions.
- **Cross-tab sync is intentionally absent.** A `storage` event
  handler would be a fine future addition, but it is not required
  for the security posture of this feature.
- **Console hygiene.** The theme layer does not `console.log`. The
  Playwright spec asserts no errors are logged during a click x N
  loop (boundary-case #4 implicitly covers this).

## Verification checklist for Vulcan

Before opening the build PR, Vulcan should confirm:

- [ ] `bun run build` passes with zero TS errors.
- [ ] The compiled `dist/index.html` still contains the inline boot
      script (or an equivalent that runs synchronously before React
      mounts).
- [ ] `bun run test:e2e` passes locally with `make up` running. All
      three specs (`login.spec.ts`, `profile.spec.ts`,
      `theme.spec.ts`) green.
- [ ] `bun run test:e2e` skips the OTP-dependent specs cleanly when
      the OTP fixture env is unset, and the theme spec runs anyway
      (because it does not require the fixture).
- [ ] `./test.sh` still passes (backend + REST suite). No regression.
- [ ] Git grep for `prefers-color-scheme` in `frontend/src/` and
      `frontend/index.html` returns:
        - One hit in `frontend/index.html` (the boot script's seed).
        - One hit in `frontend/src/theme/themeStorage.ts`
          (`seedFromMedia`).
        - **Zero hits in `frontend/src/index.css` or `App.css`** —
          the old media query is removed.
- [ ] Git grep for `data-theme` in `frontend/index.html`,
      `frontend/src/`, and `frontend/dist/` (post-build) returns the
      expected hits and **no stray references** in component CSS.
- [ ] No new dependency added to `frontend/package.json`.
- [ ] No file under `backend/`, `infra/`, or `tests/` is modified.
- [ ] Manual visual check completed for all 6 cells in the
      design-spec verification matrix (light × {`/login`, `/`,
      `/profile`} and dark × the same three). Screenshots attached
      to the build PR.
- [ ] Spec README and `docs/tracking/features.md` rows are appended
      and the Spec PR + Issues columns are backfilled.
- [ ] The `<ThemeProvider>` is the **outermost** provider, above
      `<BrowserRouter>` and `<AuthProvider>`. The `<ThemeToggle>` is
      a sibling of `<BrowserRouter>` (not inside it).
- [ ] The boot script in `index.html` is plain ES5 (no `let`,
      `const`, arrow functions, or template literals).
- [ ] The boot script is wrapped in a `try/catch` and never throws
      out to the page, even when `localStorage` and `matchMedia` are
      both unavailable.
