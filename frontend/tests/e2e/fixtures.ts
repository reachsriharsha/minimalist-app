/**
 * Test fixtures for the Playwright e2e suite.
 *
 * Mirrors `_otp_fixture_env()` in `tests/tests/test_auth.py`: the OTP
 * fixture is `{ email, code }` when both env vars are non-empty, and
 * `null` otherwise. The spec file calls `test.skip(fixture === null,
 * …)` so running Playwright without the fixture prints a clean skip,
 * not a red failure.
 */

export interface OtpFixture {
  email: string;
  code: string;
}

export function getOtpFixture(): OtpFixture | null {
  const email = (process.env.TEST_OTP_EMAIL ?? '').trim();
  const code = (process.env.TEST_OTP_CODE ?? '').trim();
  if (email === '' || code === '') {
    return null;
  }
  return { email, code };
}
