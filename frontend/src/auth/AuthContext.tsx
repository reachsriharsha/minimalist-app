/**
 * AuthContext — single source of truth for "am I signed in".
 *
 * Contract (from `design_frontend_002.md` §AuthContext contract):
 *
 * - On provider mount: set `status = 'loading'`, call `getMe()`.
 * - On 200 (Me payload): `user = payload`, `status = 'authenticated'`.
 * - On 401 (null): `user = null`, `status = 'anonymous'`. Not an error.
 * - On any other failure: log a `console.warn`, set `status = 'anonymous'`
 *   — conservative fallback so a transient backend hiccup never wedges
 *   the UI in 'loading' forever.
 * - `refresh()` re-runs `getMe()`. Used by `LoginPage` after a 200
 *   `/otp/verify` so the dashboard renders with the fresh principal.
 * - `logout()` calls the API, clears in-memory state, and navigates to
 *   `/login`. The cookie is `HttpOnly`, so JS never reads it; the server
 *   is the source of truth.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { useNavigate } from 'react-router-dom';
import { getMe, logout as apiLogout, type Me } from '../api/auth';

export type AuthStatus = 'loading' | 'authenticated' | 'anonymous';

export interface AuthContextValue {
  user: Me | null;
  status: AuthStatus;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

interface AuthProviderProps {
  children: ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [user, setUser] = useState<Me | null>(null);
  const [status, setStatus] = useState<AuthStatus>('loading');

  // Guards against late setState after unmount (React 19 StrictMode mounts
  // twice in dev).
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const navigate = useNavigate();

  const runBootstrap = useCallback(async () => {
    try {
      const me = await getMe();
      if (!mountedRef.current) return;
      if (me === null) {
        setUser(null);
        setStatus('anonymous');
      } else {
        setUser(me);
        setStatus('authenticated');
      }
    } catch (cause) {
      // Conservative: any non-401 failure lands the user in 'anonymous'.
      // Never leave the UI stuck in 'loading' — that would blank the
      // screen indefinitely on a backend outage.
      // eslint-disable-next-line no-console
      console.warn('auth bootstrap failed; treating as anonymous', cause);
      if (!mountedRef.current) return;
      setUser(null);
      setStatus('anonymous');
    }
  }, []);

  // Bootstrap on mount. No dependencies — we want exactly one kick-off
  // per provider lifetime (StrictMode's double-mount in dev is fine:
  // both runs end up with the same final state).
  useEffect(() => {
    void runBootstrap();
  }, [runBootstrap]);

  const refresh = useCallback(async () => {
    setStatus('loading');
    await runBootstrap();
  }, [runBootstrap]);

  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } catch (cause) {
      // Defensive: even on a failed server-side logout, clear local
      // state and bounce the user to /login. A stuck cookie is less
      // bad than a stuck UI — the cookie TTL (and any subsequent
      // /auth/me 401) will finish the job.
      // eslint-disable-next-line no-console
      console.warn('logout API call failed; clearing local state anyway', cause);
    } finally {
      if (mountedRef.current) {
        setUser(null);
        setStatus('anonymous');
      }
      navigate('/login', { replace: true });
    }
  }, [navigate]);

  const value = useMemo<AuthContextValue>(
    () => ({ user, status, refresh, logout }),
    [user, status, refresh, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/**
 * Read the current `AuthContext`. Must be called from a descendant of
 * `<AuthProvider>`; throws otherwise so mistakes fail loudly in dev.
 */
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (ctx === null) {
    throw new Error('useAuth() must be used inside an <AuthProvider>');
  }
  return ctx;
}
