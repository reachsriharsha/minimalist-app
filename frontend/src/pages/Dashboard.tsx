/**
 * `/` — the authed dashboard.
 *
 * Renders a greeting, a role list, and the `HelloPanel` (which still
 * exercises the `/api/v1/hello` endpoint end-to-end so the Postgres +
 * Redis demo the project ships with stays alive).
 *
 * Read-only relative to the AuthContext — never mutates `user` or
 * `status`. Logout lives in the `<Header>`.
 */

import { useAuth } from '../auth/AuthContext';
import { HelloPanel } from '../components/HelloPanel';

export default function Dashboard() {
  const { user } = useAuth();

  if (user === null) {
    // Defensive — <RequireAuth> guarantees this never fires in practice.
    return null;
  }

  const greetingName = user.display_name ?? user.email;

  return (
    <div className="dashboard" data-testid="dashboard">
      <h1 className="dashboard__greeting" data-testid="dashboard-greeting">
        Welcome, {greetingName}
      </h1>

      <section className="dashboard__roles">
        <h2 className="dashboard__subtitle">Your roles</h2>
        {user.roles.length === 0 ? (
          <p data-testid="dashboard-no-roles">No roles assigned.</p>
        ) : (
          <ul className="role-list" data-testid="dashboard-role-list">
            {user.roles.map((role) => (
              <li key={role}>{role}</li>
            ))}
          </ul>
        )}
      </section>

      <HelloPanel />
    </div>
  );
}
