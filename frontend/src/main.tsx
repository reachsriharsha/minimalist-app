import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import './index.css';
import App from './App.tsx';
import { AuthProvider } from './auth/AuthContext';
import { ThemeProvider } from './theme/ThemeContext';
import { ThemeToggle } from './theme/ThemeToggle';

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('Root element #root not found in index.html');
}

// `<ThemeProvider>` is the outermost provider so every subtree —
// including `<LoginPage>` (rendered outside `<AuthedLayout>`) — can
// read it. `<ThemeToggle>` is rendered as a sibling of
// `<BrowserRouter>` so route changes never unmount it; the toggle has
// no router dependencies (no `useNavigate`, no `useLocation`).
//   feat_frontend_004
createRoot(rootElement).render(
  <StrictMode>
    <ThemeProvider>
      <BrowserRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BrowserRouter>
      <ThemeToggle />
    </ThemeProvider>
  </StrictMode>,
);
