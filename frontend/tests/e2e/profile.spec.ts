/**
 * Profile e2e test for feat_frontend_003.
 *
 * Drives the profile flow in a real Chromium against the compose stack
 * the operator has brought up with `make up`. Same `TEST_OTP_EMAIL` /
 * `TEST_OTP_CODE` fixture pattern as `login.spec.ts`; when either env
 * var is unset the spec calls `test.skip` and exits cleanly.
 *
 * The spec covers (per `test_frontend_003.md`):
 *   - Happy path #1: Header has a Profile button at the leftmost slot.
 *   - Happy path #2: Profile button label is exactly `Profile`.
 *   - Happy path #3: Click Profile navigates to /profile (no
 *     /api/v1/auth/me re-fire on click).
 *   - Happy path #4: Profile page renders the `Profile` heading.
 *   - Happy path #5: Profile page renders the email value.
 *   - Happy path #6: Profile page does NOT render an `Email:` label
 *     anywhere inside [data-testid="profile-page"].
 *   - Happy path #7: Header still rendered on /profile.
 *   - Happy path #8: Header DOM order is Profile, email, roles, Logout.
 *   - Happy path #9: Click Profile while on /profile is a no-op.
 *   - Happy path #10: Logout from /profile ends the session.
 *   - Happy path #11: After logout, /profile redirects to /login.
 *   - Happy path #12: Relative-URL invariant — every /api/v1/* request
 *     observed during the run targets the page origin.
 *   - Happy path #13: After back-button from /profile to /, the
 *     dashboard renders normally and the Profile button is still
 *     present and leftmost (regression check on feat_frontend_002).
 *   - Boundary #2: 429 on OTP request triggers a clean test.skip.
 *   - Error case #1: direct visit to /profile while signed out
 *     redirects to /login (asserted after the logout step).
 */

import { test, expect, type Request } from '@playwright/test';
import { getOtpFixture } from './fixtures';

const fixture = getOtpFixture();

test.describe('profile flow', () => {
  test.skip(fixture === null, 'TEST_OTP_EMAIL / TEST_OTP_CODE not set');

  test('navigate to /profile, see email, logout', async ({ page, baseURL }) => {
    if (fixture === null) return; // unreachable under test.skip; narrows TS

    // --- network listeners up front -------------------------------------
    const apiOrigins: string[] = [];
    const authMeRequests: string[] = [];
    const consoleLines: string[] = [];
    const pageOrigin = new URL(baseURL ?? 'http://localhost:5173').origin;

    page.on('request', (req: Request) => {
      const url = req.url();
      if (url.includes('/api/v1/')) {
        apiOrigins.push(new URL(url).origin);
      }
      if (url.includes('/api/v1/auth/me')) {
        authMeRequests.push(url);
      }
    });

    page.on('console', (msg) => {
      consoleLines.push(msg.text());
    });

    // --- Sign in via OTP fixture (mirrors login.spec.ts steps 1–5) -----
    await page.goto('/');
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByTestId('login-email-input')).toBeVisible();

    await page.getByTestId('login-email-input').fill(fixture.email);

    const otpRequestPromise = page.waitForResponse((res) =>
      res.url().endsWith('/api/v1/auth/otp/request'),
    );
    await page.getByTestId('login-request-submit').click();
    const otpRequestResponse = await otpRequestPromise;

    // Boundary #2: rate-limited OTP request -> clean skip.
    test.skip(
      otpRequestResponse.status() === 429,
      'OTP rate limit hit; retry later',
    );
    expect(otpRequestResponse.status()).toBe(204);

    await expect(page.getByTestId('login-code-input')).toBeVisible();

    await page.getByTestId('login-code-input').fill(fixture.code);
    const verifyPromise = page.waitForResponse((res) =>
      res.url().endsWith('/api/v1/auth/otp/verify'),
    );
    await page.getByTestId('login-verify-submit').click();
    const verify = await verifyPromise;
    expect(verify.status()).toBe(200);

    await page.waitForURL(/\/$/);

    // Sanity: header strip and email visible on /
    await expect(page.getByTestId('auth-header')).toBeVisible();
    await expect(page.getByTestId('auth-header-email')).toHaveText(fixture.email);

    // --- Happy path #1 + #2: Profile button at leftmost slot -----------
    const profileBtn = page.getByTestId('auth-header-profile');
    await expect(profileBtn).toBeVisible();
    await expect(profileBtn).toBeEnabled();
    await expect(profileBtn).toHaveText('Profile');

    // Assert Profile is the FIRST child of the header strip.
    const firstChildTestId = await page
      .getByTestId('auth-header')
      .locator('> *')
      .first()
      .getAttribute('data-testid');
    expect(firstChildTestId).toBe('auth-header-profile');

    // --- Happy path #8: header DOM order is Profile, email, roles, Logout
    const headerChildTestIds = await page
      .getByTestId('auth-header')
      .locator('> *')
      .evaluateAll((els) =>
        els.map((el) => (el as HTMLElement).getAttribute('data-testid')),
      );
    expect(headerChildTestIds).toEqual([
      'auth-header-profile',
      'auth-header-email',
      'auth-header-roles',
      'auth-header-logout',
    ]);

    // --- Happy path #3: Click Profile navigates to /profile ------------
    // No /api/v1/auth/me re-fire on a client-side route push: the
    // <AuthProvider> stays mounted across the navigation.
    const meCallsBeforeClick = authMeRequests.length;
    await profileBtn.click();
    await page.waitForURL(/\/profile$/);
    // Give any would-be fetch a tick to settle, then assert /auth/me
    // didn't fire because of the click.
    await page.waitForTimeout(150);
    expect(authMeRequests.length).toBe(meCallsBeforeClick);

    // --- Happy path #4: Profile page heading is visible ----------------
    await expect(
      page.getByTestId('profile-page').locator('h1', { hasText: 'Profile' }),
    ).toBeVisible();

    // --- Happy path #5: Profile page renders the email value -----------
    await expect(page.getByTestId('profile-page-email')).toHaveText(fixture.email);

    // --- Happy path #6: No `Email:` label inside the profile page ------
    // The header still shows the email separately; assertion is scoped
    // to the profile page container.
    const profileBodyText = await page.getByTestId('profile-page').textContent();
    expect(profileBodyText ?? '').not.toContain('Email:');

    // --- Happy path #7: Header still rendered on /profile --------------
    await expect(page.getByTestId('auth-header')).toBeVisible();
    await expect(page.getByTestId('auth-header-profile')).toBeVisible();
    await expect(page.getByTestId('auth-header-email')).toBeVisible();
    await expect(page.getByTestId('auth-header-roles')).toBeVisible();
    await expect(page.getByTestId('auth-header-logout')).toBeVisible();

    // --- Happy path #9: Click Profile on /profile is a no-op -----------
    const meCallsBeforeReClick = authMeRequests.length;
    await page.getByTestId('auth-header-profile').click();
    await page.waitForTimeout(150);
    await expect(page).toHaveURL(/\/profile$/);
    // Profile page still showing the email; no flicker into a loading state.
    await expect(page.getByTestId('profile-page-email')).toHaveText(fixture.email);
    await expect(page.getByTestId('profile-loading')).toHaveCount(0);
    // No /auth/me re-fire on the same-URL push.
    expect(authMeRequests.length).toBe(meCallsBeforeReClick);

    // --- Happy path #13: back-button to / restores the dashboard ------
    await page.goBack();
    await page.waitForURL(/\/$/);
    await expect(page.getByTestId('dashboard')).toBeVisible();
    // Profile button still leftmost on /.
    const dashboardFirstChildTestId = await page
      .getByTestId('auth-header')
      .locator('> *')
      .first()
      .getAttribute('data-testid');
    expect(dashboardFirstChildTestId).toBe('auth-header-profile');
    // Forward back to /profile so we exercise logout from there.
    await page.goForward();
    await page.waitForURL(/\/profile$/);
    await expect(page.getByTestId('profile-page-email')).toHaveText(fixture.email);

    // --- Happy path #10: Logout from /profile -------------------------
    const logoutPromise = page.waitForResponse((res) =>
      res.url().endsWith('/api/v1/auth/logout'),
    );
    await page.getByTestId('auth-header-logout').click();
    const logoutResponse = await logoutPromise;
    expect([200, 204]).toContain(logoutResponse.status());
    await page.waitForURL(/\/login$/);
    await expect(page.getByTestId('login-email-input')).toBeVisible();

    // --- Happy path #11 / Error case #1: /profile redirects after logout
    await page.goto('/profile');
    await expect(page).toHaveURL(/\/login$/);

    // --- Happy path #12: Relative-URL invariant ----------------------
    expect(apiOrigins.length).toBeGreaterThan(0);
    for (const origin of apiOrigins) {
      expect(origin).toBe(pageOrigin);
    }

    // --- Security: OTP code is not logged by the frontend ------------
    const leakedCode = consoleLines.filter((line) => line.includes(fixture.code));
    expect(leakedCode).toEqual([]);
  });
});
