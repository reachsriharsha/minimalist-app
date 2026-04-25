/**
 * Persistent header strip rendered on authed routes.
 *
 * Shows the signed-in email, role chips, and a logout button. The button
 * calls the context's `logout()` which clears local state and navigates
 * to `/login`. While the logout request is in flight the button is
 * disabled so a double-click cannot fire two POSTs.
 */

import { useState } from 'react';
import { useAuth } from '../auth/AuthContext';

export function Header() {
  const { user, logout } = useAuth();
  const [loggingOut, setLoggingOut] = useState(false);

  if (user === null) {
    // Shouldn't happen — <RequireAuth> guards the routes that render
    // this header — but render nothing rather than crash if misused.
    return null;
  }

  const handleLogout = async () => {
    if (loggingOut) return;
    setLoggingOut(true);
    try {
      await logout();
    } finally {
      // `logout()` is defensive and always clears state + navigates, so
      // resetting here is mostly cosmetic; covers the edge case where
      // the component remains mounted after an error path.
      setLoggingOut(false);
    }
  };

  return (
    <header className="auth-header" data-testid="auth-header">
      <span className="auth-header__email" data-testid="auth-header-email">
        {user.email}
      </span>
      <ul className="auth-header__roles" data-testid="auth-header-roles">
        {user.roles.map((role) => (
          <li key={role} className="role-chip" data-role={role}>
            {role}
          </li>
        ))}
      </ul>
      <button
        type="button"
        className="auth-header__logout"
        onClick={handleLogout}
        disabled={loggingOut}
        data-testid="auth-header-logout"
      >
        {loggingOut ? 'Signing out…' : 'Logout'}
      </button>
    </header>
  );
}
