/**
 * Typed client for the auth endpoints exposed by `backend/app/auth/router.py`.
 *
 * All four functions use **relative URLs** (e.g. `/api/v1/auth/me`) so the
 * `HttpOnly; SameSite=Lax` session cookie set by `/otp/verify` rides along
 * on subsequent calls without any `credentials: 'include'` fetch option.
 * The page origin matches the API origin in both dev (Vite proxy) and
 * prod (nginx origin), which is the invariant the whole auth story rests
 * on.
 *
 * `getMe()` is the one intentional non-throwing branch: a 401 returns
 * `null` so the `AuthContext` provider can treat "no session cookie" as
 * the anonymous happy path rather than an error state. All other non-2xx
 * responses (and the other three calls on any non-2xx) throw.
 */

/**
 * Shape of `GET /api/v1/auth/me` — mirrors `app.auth.schemas.MeResponse`
 * in the backend (`backend/app/auth/schemas.py`). If the backend contract
 * drifts, update this type to match.
 */
export interface Me {
  user_id: number;
  email: string;
  display_name: string | null;
  roles: string[];
}

/**
 * Thrown by `requestOtp()` when the backend returns 429. Carries the
 * number of seconds the server asked us to wait (from the response
 * body's `retry_after` field, which mirrors the `Retry-After` header).
 *
 * `LoginPage` catches this and renders a user-visible "try again in N
 * seconds" message.
 */
export class RateLimitError extends Error {
  readonly retryAfterSeconds: number;

  constructor(retryAfterSeconds: number, message?: string) {
    super(message ?? `rate limit exceeded; retry after ${retryAfterSeconds}s`);
    this.name = 'RateLimitError';
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

/** Parse a backend 429 body. Missing/malformed `retry_after` defaults to 60. */
function parseRetryAfter(payload: unknown): number {
  if (payload && typeof payload === 'object' && 'retry_after' in payload) {
    const raw = (payload as { retry_after: unknown }).retry_after;
    if (typeof raw === 'number' && Number.isFinite(raw) && raw >= 0) {
      return Math.ceil(raw);
    }
  }
  return 60;
}

/**
 * Fetch the current principal.
 *
 * - 200: returns the parsed `Me` payload.
 * - 401: returns `null`. The caller (AuthProvider) interprets this as
 *        "anonymous" — *not* an error.
 * - anything else: throws.
 *
 * Never retries, never caches, never sets auth headers.
 */
export async function getMe(): Promise<Me | null> {
  const url = '/api/v1/auth/me';

  let response: Response;
  try {
    response = await fetch(url);
  } catch (cause) {
    const message = cause instanceof Error ? cause.message : String(cause);
    throw new Error(`network error calling ${url}: ${message}`);
  }

  if (response.status === 401) {
    return null;
  }

  if (!response.ok) {
    throw new Error(
      `request to ${url} failed with HTTP ${response.status} ${response.statusText}`.trim(),
    );
  }

  const payload = (await response.json()) as Me;
  return payload;
}

/**
 * End the session.
 *
 * Calls `POST /api/v1/auth/logout`. The backend returns 204 and clears
 * the session cookie. Throws on any non-2xx response.
 */
export async function logout(): Promise<void> {
  const url = '/api/v1/auth/logout';

  let response: Response;
  try {
    response = await fetch(url, { method: 'POST' });
  } catch (cause) {
    const message = cause instanceof Error ? cause.message : String(cause);
    throw new Error(`network error calling ${url}: ${message}`);
  }

  if (!response.ok) {
    throw new Error(
      `request to ${url} failed with HTTP ${response.status} ${response.statusText}`.trim(),
    );
  }
}

/**
 * Request an OTP code for `email`.
 *
 * Calls `POST /api/v1/auth/otp/request`. On 204 (or any 2xx) resolves.
 * On 429, throws `RateLimitError` with the `retry_after` seconds parsed
 * from the body. Any other non-2xx throws a generic `Error`.
 */
export async function requestOtp(email: string): Promise<void> {
  const url = '/api/v1/auth/otp/request';

  let response: Response;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    });
  } catch (cause) {
    const message = cause instanceof Error ? cause.message : String(cause);
    throw new Error(`network error calling ${url}: ${message}`);
  }

  if (response.status === 429) {
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      // Body may be empty or non-JSON; fall back to the default.
    }
    throw new RateLimitError(parseRetryAfter(payload));
  }

  if (!response.ok) {
    throw new Error(
      `request to ${url} failed with HTTP ${response.status} ${response.statusText}`.trim(),
    );
  }
}

/**
 * Verify an OTP code.
 *
 * Calls `POST /api/v1/auth/otp/verify`. On 200 returns the parsed `Me`
 * payload and the backend's `Set-Cookie: session=...` header has already
 * been applied by the browser. On any non-2xx throws — the LoginPage
 * maps all errors to the uniform "bad code" inline message per the
 * anti-enumeration rule in `feat_auth_002`.
 */
export async function verifyOtp(email: string, code: string): Promise<Me> {
  const url = '/api/v1/auth/otp/verify';

  let response: Response;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, code }),
    });
  } catch (cause) {
    const message = cause instanceof Error ? cause.message : String(cause);
    throw new Error(`network error calling ${url}: ${message}`);
  }

  if (!response.ok) {
    throw new Error(
      `request to ${url} failed with HTTP ${response.status} ${response.statusText}`.trim(),
    );
  }

  const payload = (await response.json()) as Me;
  return payload;
}
