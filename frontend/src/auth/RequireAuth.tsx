/**
 * Gate component for authed routes.
 *
 * - status === 'loading' — render a visible loading skeleton. We do NOT
 *   redirect here; a refresh on an authed page would briefly flash
 *   `/login` otherwise for users who actually have a valid cookie.
 * - status === 'anonymous' — `<Navigate to="/login" replace />` so the
 *   URL bar shows `/login` (not `/`) per Acceptance Criterion.
 * - status === 'authenticated' — render children.
 */

import type { ReactNode } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from './AuthContext';

interface RequireAuthProps {
  children: ReactNode;
}

export function RequireAuth({ children }: RequireAuthProps) {
  const { status } = useAuth();

  if (status === 'loading') {
    return (
      <div
        className="state state--loading auth-bootstrap"
        role="status"
        aria-live="polite"
        data-testid="auth-bootstrap"
      >
        Loading...
      </div>
    );
  }

  if (status === 'anonymous') {
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
}
