/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Base URL for the backend API (e.g. "http://localhost:8000").
   *
   * Read at build time. Under `bun run dev` the Vite dev server also proxies
   * `/api/*` to this target, so the API client can use a relative URL and
   * bypass CORS in local development.
   *
   * Leave unset to default to an empty string (relative URLs only, which
   * works under the Vite dev proxy with no env file).
   */
  readonly VITE_API_BASE_URL: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
