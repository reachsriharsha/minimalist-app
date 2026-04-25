/**
 * `/profile` — the authed profile page.
 *
 * Renders a page heading and the signed-in user's email value. Per the
 * `feat_frontend_003` spec the body shows the email **only** (no
 * `Email:` label, no other PII fields). The page issues zero `fetch`
 * calls; it reads the email straight off `AuthContext.user`, which the
 * `AuthProvider` populated during its mount-time bootstrap.
 *
 * `<RequireAuth>` (in `App.tsx`) handles the loading + anonymous cases
 * before this component ever mounts under normal flow. The
 * `status === 'loading'` branch below is a defensive belt-and-braces
 * for a future `refresh()`-triggered re-bootstrap; the `user === null`
 * branch should never fire under `<RequireAuth>` and renders nothing
 * rather than crashing if it somehow does.
 */

import { useAuth } from '../auth/AuthContext';

export default function ProfilePage() {
  const { user, status } = useAuth();

  if (status === 'loading') {
    return (
      <div
        className="state state--loading profile-loading"
        role="status"
        aria-live="polite"
        data-testid="profile-loading"
      >
        Loading…
      </div>
    );
  }

  if (user === null) {
    // Defensive — <RequireAuth> guarantees this never fires in practice.
    return null;
  }

  return (
    <div className="profile-page" data-testid="profile-page">
      <h1 className="profile-page__title">Profile</h1>
      <p className="profile-page__email" data-testid="profile-page-email">
        {user.email}
      </p>
    </div>
  );
}
