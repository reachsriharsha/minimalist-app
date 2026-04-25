/**
 * Routing root.
 *
 * `feat_frontend_001` shipped a single-page hello view here. With
 * `feat_frontend_002` the hello view moves into `HelloPanel` and is
 * rendered from the authed `Dashboard`. `feat_frontend_003` adds a
 * second authed route (`/profile`) that follows the same gate +
 * layout pattern.
 *
 * Route table:
 *   /login       — public, the two-step OTP form (LoginPage)
 *   /            — authed, dashboard wrapped in <AuthedLayout>
 *   /profile     — authed, profile page wrapped in <AuthedLayout>
 *   *            — redirect to `/` so typos flow through the auth gate
 *
 * `<BrowserRouter>` and `<AuthProvider>` are applied at `main.tsx` one
 * level up, so the routes below can call `useAuth()` and `useNavigate()`
 * freely.
 */

import { Navigate, Route, Routes } from 'react-router-dom';
import './App.css';
import { RequireAuth } from './auth/RequireAuth';
import { AuthedLayout } from './components/AuthedLayout';
import Dashboard from './pages/Dashboard';
import LoginPage from './pages/LoginPage';
import ProfilePage from './pages/ProfilePage';

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <AuthedLayout>
              <Dashboard />
            </AuthedLayout>
          </RequireAuth>
        }
      />
      <Route
        path="/profile"
        element={
          <RequireAuth>
            <AuthedLayout>
              <ProfilePage />
            </AuthedLayout>
          </RequireAuth>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
