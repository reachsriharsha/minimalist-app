/**
 * Theme toggle e2e test for feat_frontend_004.
 *
 * Drives the dark/light toggle in a real Chromium against the compose
 * stack the operator has brought up with `make up`. Unlike
 * `login.spec.ts` and `profile.spec.ts`, this spec does NOT need the
 * OTP fixture — every assertion runs on `/login` (unauthenticated) or
 * on the `/login` page reached via redirect from `/`. There is no
 * `test.skip` based on a missing OTP fixture; the spec runs on a
 * vanilla compose stack.
 *
 * The spec covers (per `test_frontend_004.md`):
 *   - Happy path #1: Toggle button visible on /login.
 *   - Happy path #2: Toggle button visible on / (redirected to /login).
 *   - Happy path #3: First-visit seed: OS=dark -> theme=dark.
 *   - Happy path #4: First-visit seed: OS=light -> theme=light.
 *   - Happy path #5: First-visit seed writes to localStorage.
 *   - Happy path #6: Toggle label = `Dark mode` when current=light.
 *   - Happy path #7: Toggle label = `Light mode` when current=dark.
 *   - Happy path #8: Click toggle flips data-theme.
 *   - Happy path #9: Click toggle updates label.
 *   - Happy path #10: Click toggle persists to localStorage.
 *   - Happy path #11: Theme persists across reload (no flash).
 *   - Happy path #12: User choice beats OS preference.
 *   - Happy path #13: Stored OS-preference change does not reseed.
 *   - Error case #3: Stale unknown localStorage value re-seeds from OS.
 *   - Error case #4: Rapid 10x click parity is correct.
 *   - Boundary #2: Theme stable across 1s of idle time.
 */

import { test, expect } from '@playwright/test';

const STORAGE_KEY = 'minimalist-app:theme:v1';

test.describe('theme toggle', () => {
  test('toggle button is visible on /login', async ({ page }) => {
    await page.addInitScript(() => {
      try {
        window.localStorage.removeItem('minimalist-app:theme:v1');
      } catch {
        /* private window — ignore */
      }
    });
    await page.goto('/login');
    await expect(page.getByTestId('theme-toggle')).toBeVisible();
  });

  test('toggle button is visible on / (redirected to /login)', async ({ page }) => {
    await page.addInitScript(() => {
      try {
        window.localStorage.removeItem('minimalist-app:theme:v1');
      } catch {
        /* private window — ignore */
      }
    });
    await page.goto('/');
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByTestId('theme-toggle')).toBeVisible();
  });

  test('first visit seeds from OS preference (dark)', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.addInitScript(() => {
      try {
        window.localStorage.removeItem('minimalist-app:theme:v1');
      } catch {
        /* private window — ignore */
      }
    });
    await page.goto('/login');

    const theme = await page.evaluate(() =>
      document.documentElement.getAttribute('data-theme'),
    );
    expect(theme).toBe('dark');

    // Happy path #5: seed value is persisted.
    const stored = await page.evaluate(
      (key) => window.localStorage.getItem(key),
      STORAGE_KEY,
    );
    expect(stored).toBe('dark');

    // Happy path #7: label reflects the action (current=dark -> "Light mode").
    await expect(page.getByTestId('theme-toggle')).toHaveText('Light mode');
  });

  test('first visit seeds from OS preference (light)', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'light' });
    await page.addInitScript(() => {
      try {
        window.localStorage.removeItem('minimalist-app:theme:v1');
      } catch {
        /* private window — ignore */
      }
    });
    await page.goto('/login');

    const theme = await page.evaluate(() =>
      document.documentElement.getAttribute('data-theme'),
    );
    expect(theme).toBe('light');

    const stored = await page.evaluate(
      (key) => window.localStorage.getItem(key),
      STORAGE_KEY,
    );
    expect(stored).toBe('light');

    // Happy path #6: label reflects the action (current=light -> "Dark mode").
    await expect(page.getByTestId('theme-toggle')).toHaveText('Dark mode');
  });

  test('toggle flips theme, updates label, persists, and survives reload', async ({
    page,
  }) => {
    await page.emulateMedia({ colorScheme: 'light' });
    await page.addInitScript(() => {
      try {
        window.localStorage.removeItem('minimalist-app:theme:v1');
      } catch {
        /* private window — ignore */
      }
    });
    await page.goto('/login');

    // Initial: light (seeded).
    expect(
      await page.evaluate(() =>
        document.documentElement.getAttribute('data-theme'),
      ),
    ).toBe('light');
    await expect(page.getByTestId('theme-toggle')).toHaveText('Dark mode');

    // Happy path #8: click toggle flips data-theme.
    await page.getByTestId('theme-toggle').click();
    expect(
      await page.evaluate(() =>
        document.documentElement.getAttribute('data-theme'),
      ),
    ).toBe('dark');

    // Happy path #9: label updated.
    await expect(page.getByTestId('theme-toggle')).toHaveText('Light mode');

    // Happy path #10: persisted to localStorage.
    expect(
      await page.evaluate(
        (key) => window.localStorage.getItem(key),
        STORAGE_KEY,
      ),
    ).toBe('dark');

    // Happy path #11: theme persists across reload, no flash of wrong
    // theme. Asserted via `page.evaluate` immediately after `reload()`
    // resolves (no interaction in between).
    await page.reload();
    const themeOnReload = await page.evaluate(() =>
      document.documentElement.getAttribute('data-theme'),
    );
    expect(themeOnReload).toBe('dark');
    await expect(page.getByTestId('theme-toggle')).toHaveText('Light mode');
  });

  test('user choice beats OS preference (no reseed after toggle)', async ({
    page,
  }) => {
    await page.emulateMedia({ colorScheme: 'light' });
    await page.addInitScript(() => {
      try {
        window.localStorage.removeItem('minimalist-app:theme:v1');
      } catch {
        /* private window — ignore */
      }
    });
    await page.goto('/login');

    // User picks dark.
    await page.getByTestId('theme-toggle').click();
    expect(
      await page.evaluate(() =>
        document.documentElement.getAttribute('data-theme'),
      ),
    ).toBe('dark');

    // Happy path #12 / #13: OS preference flips to light; reload.
    // Stored choice still wins.
    await page.emulateMedia({ colorScheme: 'light' });
    await page.reload();
    expect(
      await page.evaluate(() =>
        document.documentElement.getAttribute('data-theme'),
      ),
    ).toBe('dark');

    // Flip OS preference to dark; reload. Still the user's choice.
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.reload();
    expect(
      await page.evaluate(() =>
        document.documentElement.getAttribute('data-theme'),
      ),
    ).toBe('dark');
  });

  test('stale unknown localStorage value re-seeds from OS preference', async ({
    page,
  }) => {
    // Error case #3: hand-edited / future-leftover value should not
    // crash; readTheme returns null and the seed path runs.
    await page.emulateMedia({ colorScheme: 'light' });
    await page.addInitScript(() => {
      try {
        window.localStorage.setItem('minimalist-app:theme:v1', 'system');
      } catch {
        /* private window — ignore */
      }
    });
    await page.goto('/login');

    const theme = await page.evaluate(() =>
      document.documentElement.getAttribute('data-theme'),
    );
    expect(theme).toBe('light');

    // Storage is rewritten to a known-good value.
    const stored = await page.evaluate(
      (key) => window.localStorage.getItem(key),
      STORAGE_KEY,
    );
    expect(stored).toBe('light');
  });

  test('rapid 10x clicks land on the correct parity with no errors', async ({
    page,
  }) => {
    // Error case #4: programmatic click x10 from light starts -> light.
    await page.emulateMedia({ colorScheme: 'light' });
    await page.addInitScript(() => {
      try {
        window.localStorage.removeItem('minimalist-app:theme:v1');
      } catch {
        /* private window — ignore */
      }
    });

    const consoleErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        consoleErrors.push(msg.text());
      }
    });
    page.on('pageerror', (err) => {
      consoleErrors.push(err.message);
    });

    await page.goto('/login');
    expect(
      await page.evaluate(() =>
        document.documentElement.getAttribute('data-theme'),
      ),
    ).toBe('light');

    const toggle = page.getByTestId('theme-toggle');
    for (let i = 0; i < 10; i += 1) {
      await toggle.click();
    }

    // 10 clicks from light -> light (even parity).
    expect(
      await page.evaluate(() =>
        document.documentElement.getAttribute('data-theme'),
      ),
    ).toBe('light');
    expect(
      await page.evaluate(
        (key) => window.localStorage.getItem(key),
        STORAGE_KEY,
      ),
    ).toBe('light');

    // No console errors caused by the click loop.
    expect(consoleErrors).toEqual([]);
  });

  test('theme is stable across 1s of idle time', async ({ page }) => {
    // Boundary #2: verify no late effect or interval rewrites the
    // attribute.
    await page.emulateMedia({ colorScheme: 'light' });
    await page.addInitScript(() => {
      try {
        window.localStorage.removeItem('minimalist-app:theme:v1');
      } catch {
        /* private window — ignore */
      }
    });
    await page.goto('/login');

    const before = await page.evaluate(() =>
      document.documentElement.getAttribute('data-theme'),
    );
    expect(before).toBe('light');

    await page.waitForTimeout(1000);

    const after = await page.evaluate(() =>
      document.documentElement.getAttribute('data-theme'),
    );
    expect(after).toBe('light');
  });
});
