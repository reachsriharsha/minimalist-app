/**
 * Versioned localStorage wrapper for the user's theme choice.
 *
 * One key, two values, one media query. Falls back to an in-memory
 * variable when localStorage throws (private windows, quota errors,
 * SSR sneaks). Treats unrecognized stored values (e.g. a hand-edited
 * 'system' or a stale value left by a hypothetical future change) as
 * "unset" so the caller can re-seed from the OS preference rather
 * than crash.
 *
 * Introduced by feat_frontend_004.
 */

export const STORAGE_KEY = 'minimalist-app:theme:v1';

export type Theme = 'light' | 'dark';

// In-memory fallback used when localStorage is unavailable (private
// windows, Safari ITP, quota errors). Module-scoped so it survives
// across React StrictMode double-mounts within a single page load.
let inMemory: Theme | null = null;

/**
 * Read the persisted theme. Returns `null` when no value is stored or
 * when the stored value is not exactly `'light'` or `'dark'`. A `null`
 * return means the caller should seed from OS preference.
 */
export function readTheme(): Theme | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === 'light' || raw === 'dark') {
      return raw;
    }
    return null;
  } catch {
    // localStorage unavailable — fall back to whatever we last held
    // in memory for this page load.
    return inMemory;
  }
}

/**
 * Write the theme to localStorage. Always updates the in-memory
 * fallback so a subsequent read still sees the new value even when
 * the storage write itself throws (private window, quota error).
 */
export function writeTheme(theme: Theme): void {
  inMemory = theme;
  try {
    window.localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // private window / quota — keep in-memory fallback. No throw.
  }
}

/**
 * Derive the initial theme from the OS preference and persist it.
 * Called by the React layer when `readTheme()` returns `null`. The
 * inline boot script in `index.html` performs the same logic in plain
 * ES5 before React mounts; both paths converge on the same value.
 */
export function seedFromMedia(): Theme {
  let prefersDark = false;
  try {
    prefersDark =
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-color-scheme: dark)').matches;
  } catch {
    prefersDark = false;
  }
  const theme: Theme = prefersDark ? 'dark' : 'light';
  writeTheme(theme);
  return theme;
}
