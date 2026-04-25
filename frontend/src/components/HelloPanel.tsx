/**
 * The original `feat_frontend_001` hello-world view, extracted from
 * `App.tsx` into a reusable panel so the authed `Dashboard` can render
 * it inside the broader layout. Behavior is unchanged — same `getHello()`
 * call, same three-state render (loading / error / success).
 *
 * Keeping this panel alive matters: `getHello()` is what exercises the
 * Postgres + Redis wiring end-to-end. If the panel renders an error, the
 * backend's data plane is broken even if auth is fine.
 */

import { useEffect, useState } from 'react';
import { getHello, type HelloResponse } from '../api/client';

export function HelloPanel() {
  const [data, setData] = useState<HelloResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    let cancelled = false;

    setLoading(true);
    setError(null);
    setData(null);

    getHello()
      .then((response) => {
        if (cancelled) return;
        setData(response);
        setLoading(false);
      })
      .catch((cause: unknown) => {
        if (cancelled) return;
        const message = cause instanceof Error ? cause.message : String(cause);
        setError(message);
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section className="hello-panel" data-testid="hello-panel">
      <h2 className="hello-panel__title">backend hello</h2>

      {loading && (
        <div className="state state--loading" role="status" aria-live="polite">
          Loading...
        </div>
      )}

      {!loading && error !== null && (
        <div className="state state--error" role="alert">
          Failed to load: {error}
        </div>
      )}

      {!loading && error === null && data !== null && (
        <div className="state state--success">
          <strong data-testid="hello-panel-message">{data.message}</strong>
          <dl>
            <dt>item_name</dt>
            <dd>{data.item_name}</dd>
            <dt>hello_count</dt>
            <dd>{data.hello_count}</dd>
          </dl>
        </div>
      )}
    </section>
  );
}
