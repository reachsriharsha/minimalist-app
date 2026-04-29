/**
 * ThemeContext — single source of truth for the active UI theme.
 *
 * Contract (from `design_frontend_004.md`):
 *
 * - On provider mount: read the persisted theme via `readTheme()`. If
 *   no value is stored (or the stored value is unrecognized), call
 *   `seedFromMedia()` to derive and persist one. The inline boot
 *   script in `index.html` performs the same seed logic in plain ES5
 *   before React mounts, so the `data-theme` attribute on `<html>` is
 *   already correct on first paint; this provider just keeps the
 *   React state and the DOM in sync afterward.
 * - `setTheme(t)` sets the state and persists. `toggleTheme()` flips
 *   between `'light'` and `'dark'`.
 * - The provider's effect is idempotent: re-applying the same
 *   `data-theme` value is a no-op the browser elides.
 * - Mounted **above** `<AuthProvider>` and `<BrowserRouter>` in
 *   `main.tsx` so every React subtree (including `LoginPage`, which
 *   renders outside `<AuthedLayout>`) can read it.
 *
 * Introduced by feat_frontend_004.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { readTheme, seedFromMedia, writeTheme, type Theme } from './themeStorage';

export interface ThemeContextValue {
  theme: Theme;
  setTheme: (t: Theme) => void;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

interface ThemeProviderProps {
  children: ReactNode;
}

export function ThemeProvider({ children }: ThemeProviderProps) {
  // Initial state must be synchronous so the React render after the
  // inline boot script does not flash the wrong theme. We read storage;
  // if missing, we seed (which writes back). Both branches return a
  // concrete `Theme`.
  const [theme, setThemeState] = useState<Theme>(() => {
    return readTheme() ?? seedFromMedia();
  });

  // Apply data-theme on every change. The inline boot script already
  // set this once before React mounted; this effect keeps the DOM and
  // React state in sync on subsequent toggles. Re-applying the same
  // value is a no-op the browser elides.
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  const setTheme = useCallback((t: Theme) => {
    writeTheme(t);
    setThemeState(t);
  }, []);

  const toggleTheme = useCallback(() => {
    setThemeState((prev) => {
      const next: Theme = prev === 'light' ? 'dark' : 'light';
      writeTheme(next);
      return next;
    });
  }, []);

  const value = useMemo<ThemeContextValue>(
    () => ({ theme, setTheme, toggleTheme }),
    [theme, setTheme, toggleTheme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

/**
 * Read the current `ThemeContext`. Must be called from a descendant of
 * `<ThemeProvider>`; throws otherwise so mistakes fail loudly in dev,
 * mirroring `useAuth()`.
 */
export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (ctx === null) {
    throw new Error('useTheme() must be used inside a <ThemeProvider>');
  }
  return ctx;
}
