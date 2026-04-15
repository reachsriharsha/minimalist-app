/**
 * Typed client for the minimalist-app backend.
 *
 * The only endpoint this module speaks to (for now) is `GET /api/v1/hello`.
 * All HTTP access from the UI goes through this file so the response shape
 * is defined exactly once and changes to the backend contract have a single
 * point of update.
 */

/**
 * Shape of `GET /api/v1/hello` — mirrors `app.schemas.HelloResponse` in the
 * backend (`backend/app/schemas.py`). If the backend contract drifts, update
 * this type to match.
 */
export interface HelloResponse {
  message: string;
  item_name: string;
  hello_count: number;
}

/**
 * Base URL for backend API calls.
 *
 * Read from `import.meta.env.VITE_API_BASE_URL` at build time. When unset we
 * fall back to an empty string so the request URL is a relative path
 * (`/api/v1/hello`), which resolves against the current origin. Under
 * `bun run dev` the Vite dev-server proxy forwards `/api/*` to the backend,
 * so a missing env file still works without code changes.
 */
const baseUrl: string = import.meta.env.VITE_API_BASE_URL ?? '';

/**
 * Fetch the hello payload from the backend.
 *
 * Throws on network failure or any non-2xx response. Callers are expected to
 * handle both cases in a single `catch` branch and surface `error.message` to
 * the user. The function never retries, caches, or sets auth headers.
 */
export async function getHello(): Promise<HelloResponse> {
  const url = `${baseUrl}/api/v1/hello`;

  let response: Response;
  try {
    response = await fetch(url);
  } catch (cause) {
    // Network failure (DNS, connection refused, CORS preflight error, etc.).
    const message = cause instanceof Error ? cause.message : String(cause);
    throw new Error(`network error calling ${url}: ${message}`);
  }

  if (!response.ok) {
    // Include the HTTP status in the thrown message so the error-state UI
    // tells a developer what happened (e.g. 503 when the seed row is
    // missing from the backend).
    throw new Error(
      `request to ${url} failed with HTTP ${response.status} ${response.statusText}`.trim(),
    );
  }

  const payload = (await response.json()) as HelloResponse;
  return payload;
}
