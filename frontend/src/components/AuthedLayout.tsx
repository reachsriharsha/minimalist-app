/**
 * Structural wrapper applied to every authed route.
 *
 * Renders the persistent `<Header>` strip above a `<main>` element that
 * receives the route's children. Kept in `src/components/` (not
 * `src/pages/`) because it is layout, not content.
 */

import type { ReactNode } from 'react';
import { Header } from './Header';

interface AuthedLayoutProps {
  children: ReactNode;
}

export function AuthedLayout({ children }: AuthedLayoutProps) {
  return (
    <div className="authed-layout">
      <Header />
      <main className="authed-layout__main">{children}</main>
    </div>
  );
}
