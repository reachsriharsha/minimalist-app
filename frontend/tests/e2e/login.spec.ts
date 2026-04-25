/**
 * Login e2e test for feat_frontend_002.
 *
 * Drives the full round trip in a real Chromium against the compose
 * stack the operator has brought up with `make up`. Fixture pair
 * (`TEST_OTP_EMAIL` / `TEST_OTP_CODE`) is read from the runner env —
 * the backend honors the same pair inside `request_otp` only when
 * `ENV=test`, so an operator intentionally wires them up before the
 * stack starts.
 *
 * The spec covers:
 *   - Happy path #1: Unauthenticated landing redirect to /login.
 *   - Happy path #2: Login page renders key elements (email input,
 *     Send-code button, disabled Google button).
 *   - Happy path #3: Google button is inert — clicking produces no
 *     network request.
 *   - Happy path #4: OTP request advances to step 2.
 *   - Happy path #5: OTP verify lands on dashboard.
 *   - Happy path #6: Dashboard shows profile data + HelloPanel.
 *   - Happy path #7: Header strip shows identity + role chip.
 *   - Happy path #8: Refresh preserves auth.
 *   - Happy path #9: Logout ends session.
 *   - Happy path #10: After logout, / redirects to /login again.
 *   - Happy path #11: Relative-URL invariant — every /api/v1/* request
 *     targets the page origin (never http://localhost:8000 or similar).
 *   - Boundary #2: 429 on OTP request triggers a clean test.skip so the
 *     suite is re-runnable back-to-back without a red failure.
 *
 * Error-case coverage (#1 wrong code, #2 malformed email) is folded in
 * as secondary assertions where the happy-path state already gives us
 * the right starting point without a second full login.
 */

import { test, expect, type Page, type Request } from '@playwright/test';
import { getOtpFixture } from './fixtures';

const fixture = getOtpFixture();

test.describe('login flow', () => {
  test.skip(fixture === null, 'TEST_OTP_EMAIL / TEST_OTP_CODE not set');

  test('end-to-end: landing redirect -> OTP -> dashboard -> logout', async ({
    page,
    baseURL,
  }) => {
    if (fixture === null) return; // unreachable under test.skip; narrows TS

    // --- set up network listeners up front so we see every request
    // including the initial navigation + bootstrap /auth/me call ------
    const apiOrigins: string[] = [];
    const allRequests: string[] = [];
    const consoleLines: string[] = [];
    const pageOrigin = new URL(baseURL ?? 'http://localhost:5173').origin;

    page.on('request', (req: Request) => {
      const url = req.url();
      allRequests.push(url);
      if (url.includes('/api/v1/')) {
        apiOrigins.push(new URL(url).origin);
      }
    });

    page.on('console', (msg) => {
      consoleLines.push(msg.text());
    });

    // --- Happy path #1 + boundary #3: landing on / with no cookie
    //     redirects to /login. The AuthContext bootstrap hits
    //     /api/v1/auth/me, receives 401, and <RequireAuth> routes us. --

    await page.goto('/');
    await expect(page).toHaveURL(/\/login$/);

    // --- Happy path #2: login page renders key elements -------------
    await expect(page.getByTestId('login-email-input')).toBeVisible();
    await expect(page.getByTestId('login-request-submit')).toBeVisible();

    const googleBtn = page.getByTestId('login-google-button');
    await expect(googleBtn).toBeVisible();
    await expect(googleBtn).toBeDisabled();
    await expect(googleBtn).toHaveText(/coming soon/i);

    // --- Happy path #3: Google button is inert ----------------------
    // A `disabled` button's click handler never fires, but we still
    // exercise the click + assert no network request went out. Use
    // force:true so Playwright doesn't refuse to click a disabled
    // element.
    const beforeClick = allRequests.length;
    await googleBtn.click({ force: true }).catch(() => {
      // Some Playwright versions throw when click-targets are disabled;
      // either way, a disabled element produces no network side-effect,
      // which is what the assertion below measures.
    });
    // Give any would-be fetch a tick to settle, then assert nothing
    // new-fetchable fired on the click.
    await page.waitForTimeout(100);
    const newRequests = allRequests.slice(beforeClick);
    // We only care that no /api/v1/* call (nor any URL containing
    // "google") fired because the user clicked the disabled button.
    // HMR/dev-server traffic (/@vite/, /src/*, /node_modules/.vite/) is
    // ignored as noise.
    const googleAuthHits = newRequests.filter(
      (url) => url.includes('/api/v1/') || url.toLowerCase().includes('google'),
    );
    expect(googleAuthHits).toEqual([]);

    // --- Happy path #4: OTP request advances to step 2 --------------
    await page.getByTestId('login-email-input').fill(fixture.email);

    const otpRequestPromise = page.waitForResponse(
      (res) => res.url().endsWith('/api/v1/auth/otp/request'),
    );
    await page.getByTestId('login-request-submit').click();
    const otpRequestResponse = await otpRequestPromise;

    // Boundary #2: rate-limited OTP request -> clean skip so a
    // repeat run doesn't flail.
    test.skip(
      otpRequestResponse.status() === 429,
      'OTP rate limit hit; retry later',
    );
    expect(otpRequestResponse.status()).toBe(204);

    await expect(page.getByTestId('login-code-input')).toBeVisible();
    await expect(page.getByTestId('login-code-sent')).toContainText(fixture.email);

    // --- Error case #1: wrong code -> inline error, no navigation ---
    await page.getByTestId('login-code-input').fill('999999');
    const wrongVerifyPromise = page.waitForResponse((res) =>
      res.url().endsWith('/api/v1/auth/otp/verify'),
    );
    await page.getByTestId('login-verify-submit').click();
    const wrongVerify = await wrongVerifyPromise;
    expect([400, 401]).toContain(wrongVerify.status());
    await expect(page.getByTestId('login-error')).toBeVisible();
    await expect(page).toHaveURL(/\/login$/);

    // --- Happy path #5: submit the correct code ---------------------
    await page.getByTestId('login-code-input').fill(fixture.code);
    const verifyPromise = page.waitForResponse((res) =>
      res.url().endsWith('/api/v1/auth/otp/verify'),
    );
    await page.getByTestId('login-verify-submit').click();
    const verify = await verifyPromise;
    expect(verify.status()).toBe(200);

    // URL lands on / (the dashboard).
    await page.waitForURL(/\/$/);

    // --- Happy path #6 + #7: dashboard renders profile + header ----
    await expect(page.getByTestId('auth-header')).toBeVisible();
    await expect(page.getByTestId('auth-header-email')).toHaveText(fixture.email);
    // At minimum, every signed-in user holds the `user` role
    // (feat_auth_001 bootstrap); admin emails may hold additional roles.
    await expect(
      page.getByTestId('auth-header-roles').locator('.role-chip[data-role="user"]'),
    ).toBeVisible();

    await expect(page.getByTestId('dashboard')).toBeVisible();
    await expect(page.getByTestId('dashboard-greeting')).toContainText(/Welcome,/);
    // Role list must include "user".
    await expect(page.getByTestId('dashboard-role-list')).toContainText('user');
    // HelloPanel renders its success block (message visible).
    await expect(page.getByTestId('hello-panel-message')).toBeVisible();

    // --- Happy path #8: refresh preserves auth ----------------------
    await page.reload();
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByTestId('auth-header-email')).toHaveText(fixture.email);

    // --- Happy path #9: logout ends session -------------------------
    const logoutPromise = page.waitForResponse((res) =>
      res.url().endsWith('/api/v1/auth/logout'),
    );
    await page.getByTestId('auth-header-logout').click();
    const logoutResponse = await logoutPromise;
    expect([200, 204]).toContain(logoutResponse.status());
    await page.waitForURL(/\/login$/);
    await expect(page.getByTestId('login-email-input')).toBeVisible();

    // --- Happy path #10: after logout, / redirects again -----------
    await page.goto('/');
    await expect(page).toHaveURL(/\/login$/);

    // --- Happy path #11: relative-URL invariant --------------------
    // Every /api/v1/* request observed during the run must have
    // originated from the same origin as the page (baseURL). An
    // absolute-URL regression (e.g. http://localhost:8000) would fail
    // here even in dev.
    expect(apiOrigins.length).toBeGreaterThan(0);
    for (const origin of apiOrigins) {
      expect(origin).toBe(pageOrigin);
    }

    // --- Security: OTP code is not logged by the frontend ----------
    // Light-touch check per test spec §Security. The backend may
    // still log the decoy code per feat_auth_002 — that's out of
    // scope; we only assert the browser console stays clean.
    const leaked = consoleLines.filter((line) => line.includes(fixture.code));
    expect(leaked).toEqual([]);
  });

  test('malformed email blocks step 1 without a network call', async ({ page }) => {
    if (fixture === null) return;

    let apiHits = 0;
    page.on('request', (req: Request) => {
      if (req.url().includes('/api/v1/auth/otp/')) apiHits += 1;
    });

    await page.goto('/login');
    await expect(page.getByTestId('login-email-input')).toBeVisible();

    await page.getByTestId('login-email-input').fill('notanemail');
    await page.getByTestId('login-request-submit').click();

    // Give a potential fetch a tick to settle.
    await page.waitForTimeout(100);

    await expect(page.getByTestId('login-error')).toBeVisible();
    await expect(page.getByTestId('login-email-input')).toBeVisible();
    // Step 2 (code input) must NOT appear.
    await expect(page.getByTestId('login-code-input')).toHaveCount(0);
    // No OTP endpoint calls fired.
    expect(apiHits).toBe(0);
  });
});

// Helper kept at module scope so the top-level describe stays readable.
// Intentionally unused in prod code paths; retained so future spec
// authors can opt into it.
export async function waitForApiIdle(page: Page, ms = 200): Promise<void> {
  await page.waitForTimeout(ms);
}
