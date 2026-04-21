/**
 * Playwright config for feat_frontend_002 e2e suite.
 *
 * Runs against the compose stack the operator brings up with `make up`.
 * There is deliberately no `webServer` block — starting a separate
 * `bun run dev` + `uvicorn` pair would drift from the real deployment
 * path we want to exercise. See `docs/deployment/email-otp-setup.md`
 * section "E2E smoke test" for the operator flow.
 *
 * `baseURL` defaults to the Vite dev-server origin that compose
 * publishes on :5173. Operators running the prod profile (nginx on
 * :8080) override via `PLAYWRIGHT_BASE_URL=http://localhost:8080`.
 */

import { defineConfig, devices } from '@playwright/test';

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:5173';

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL,
    trace: 'on-first-retry',
    // Same-origin by contract — don't let the runner silently elevate
    // anything.
    ignoreHTTPSErrors: false,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
