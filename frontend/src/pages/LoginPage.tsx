/**
 * `/login` — the two-step email-OTP form.
 *
 * Step 1 (request): user enters email, submit calls
 *   `POST /api/v1/auth/otp/request`. On success advance to step 2.
 *   On 429, render a "try again in N seconds" message. On any other
 *   error, render a generic "try again" message.
 *
 * Step 2 (verify): user enters six-digit code, submit calls
 *   `POST /api/v1/auth/otp/verify`. On 200, call
 *   `AuthContext.refresh()` (awaited, so the dashboard sees the fresh
 *   principal on first render) and navigate to `/` with replace so the
 *   back button doesn't land them back on `/login`. On any error, render
 *   a uniform "code didn't work" message and stay on step 2 — the user
 *   can retype or click the back link to re-request.
 *
 * The Google button is a disabled placeholder for `feat_auth_003`. It
 * is a plain `<button type="button" disabled>` with no `onClick`, no
 * `fetch`, and no reference to any backend path. `feat_auth_003` will
 * replace this element wholesale.
 */

import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { requestOtp, verifyOtp, RateLimitError } from '../api/auth';
import { useAuth } from '../auth/AuthContext';

type Step = 'request' | 'verify';

export default function LoginPage() {
  const { refresh } = useAuth();
  const navigate = useNavigate();

  const [step, setStep] = useState<Step>('request');
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const reset = () => {
    setError(null);
    setInfo(null);
  };

  const goBackToEmail = () => {
    reset();
    setCode('');
    setStep('request');
  };

  const onRequestSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitting) return;

    reset();

    const trimmed = email.trim();
    // Minimal client-side shape check — the backend does the real
    // validation (and returns the same 400 regardless on verify, per the
    // anti-enumeration rule). Blocking obviously-malformed input here
    // avoids a pointless network round-trip and satisfies the
    // boundary-case test for "malformed email".
    if (!trimmed.includes('@') || trimmed.length < 3) {
      setError('Please enter a valid email address.');
      return;
    }

    setSubmitting(true);
    try {
      await requestOtp(trimmed);
      setEmail(trimmed);
      setStep('verify');
      setInfo(`We sent a code to ${trimmed}.`);
    } catch (cause) {
      if (cause instanceof RateLimitError) {
        setError(
          `Too many requests. Try again in ${cause.retryAfterSeconds} second${
            cause.retryAfterSeconds === 1 ? '' : 's'
          }.`,
        );
      } else {
        setError("Couldn't send the code. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  const onVerifySubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitting) return;

    reset();

    const trimmedCode = code.trim();
    if (trimmedCode.length !== 6 || !/^\d{6}$/.test(trimmedCode)) {
      setError('Enter the 6-digit code from your email.');
      return;
    }

    setSubmitting(true);
    try {
      await verifyOtp(email.trim(), trimmedCode);
      // Refresh AuthContext BEFORE navigating so the dashboard renders
      // with the fresh principal on first mount (avoids a loading-flash
      // or, worse, a redirect back to /login if StrictMode re-runs the
      // bootstrap before the cookie propagates).
      await refresh();
      navigate('/', { replace: true });
    } catch {
      // Uniform error: we never distinguish "wrong code" from "expired"
      // from "too many attempts" at the UI layer — the backend enforces
      // this at the API layer too (anti-enumeration, see
      // `feat_auth_002`).
      setError("That code didn't work. Try again, or request a new one.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="login-page" data-testid="login-page">
      <h1 className="login-page__title">Sign in</h1>

      {step === 'request' && (
        <form
          className="login-form"
          onSubmit={onRequestSubmit}
          data-testid="login-request-form"
          noValidate
        >
          <label className="login-form__label" htmlFor="login-email">
            Email
          </label>
          <input
            id="login-email"
            name="email"
            type="email"
            autoComplete="email"
            autoFocus
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={submitting}
            data-testid="login-email-input"
          />

          {error !== null && (
            <div className="login-form__error" role="alert" data-testid="login-error">
              {error}
            </div>
          )}

          <button
            type="submit"
            className="login-form__submit"
            disabled={submitting}
            data-testid="login-request-submit"
          >
            {submitting ? 'Sending…' : 'Send code'}
          </button>

          <div className="login-form__divider" aria-hidden="true">
            or
          </div>

          <button
            type="button"
            disabled
            aria-disabled="true"
            title="Google sign-in coming soon"
            className="google-btn google-btn--disabled"
            data-testid="login-google-button"
          >
            Sign in with Google (coming soon)
          </button>
        </form>
      )}

      {step === 'verify' && (
        <form
          className="login-form"
          onSubmit={onVerifySubmit}
          data-testid="login-verify-form"
          noValidate
        >
          {info !== null && (
            <div
              className="login-form__info"
              role="status"
              aria-live="polite"
              data-testid="login-code-sent"
            >
              {info}
            </div>
          )}

          <label className="login-form__label" htmlFor="login-code">
            6-digit code
          </label>
          <input
            id="login-code"
            name="code"
            type="text"
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="[0-9]{6}"
            maxLength={6}
            autoFocus
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
            disabled={submitting}
            data-testid="login-code-input"
          />

          {error !== null && (
            <div className="login-form__error" role="alert" data-testid="login-error">
              {error}
            </div>
          )}

          <button
            type="submit"
            className="login-form__submit"
            disabled={submitting}
            data-testid="login-verify-submit"
          >
            {submitting ? 'Verifying…' : 'Verify'}
          </button>

          <button
            type="button"
            className="login-form__back"
            onClick={goBackToEmail}
            disabled={submitting}
            data-testid="login-back-to-email"
          >
            Back to email
          </button>
        </form>
      )}
    </div>
  );
}
