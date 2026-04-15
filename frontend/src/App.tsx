import { useEffect, useState } from 'react';
import './App.css';
import { getHello, type HelloResponse } from './api/client';

/**
 * Single-page hello app. On mount, calls the backend's `/api/v1/hello`
 * endpoint through the typed API client and renders exactly one of three
 * states: loading, error, or success.
 */
export default function App() {
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
    <div className="app">
      <h1>minimalist-app</h1>
      <p className="subtitle">frontend talking to the backend hello endpoint</p>

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
          <strong>{data.message}</strong>
          <dl>
            <dt>item_name</dt>
            <dd>{data.item_name}</dd>
            <dt>hello_count</dt>
            <dd>{data.hello_count}</dd>
          </dl>
        </div>
      )}
    </div>
  );
}
