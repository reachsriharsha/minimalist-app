/**
 * ThemeToggle — fixed bottom-left button that flips light/dark.
 *
 * Renders a single `<button>` styled as a fixed-position overlay (see
 * `.theme-toggle` in `App.css`). The label reflects the **action**, not
 * the current state: when the active theme is `'light'` the button
 * reads `Dark mode` (because clicking it switches to dark), and vice
 * versa. The button is always mounted (rendered as a sibling of
 * `<BrowserRouter>` in `main.tsx`), so it stays visible across every
 * route — including `/login` (unauthenticated) and the bootstrap
 * `loading` state.
 *
 * Introduced by feat_frontend_004.
 */

import { useTheme } from './ThemeContext';

export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  const label = theme === 'light' ? 'Dark mode' : 'Light mode';

  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={toggleTheme}
      data-testid="theme-toggle"
      aria-label={`Switch to ${label.toLowerCase()}`}
    >
      {label}
    </button>
  );
}
