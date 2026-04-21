# Email / OTP setup

Operator guide for the email-OTP sign-in flow introduced by
`feat_auth_002`. Covers the dev-mode console provider (the default)
and the Resend HTTP provider used in staging / production.

## Overview

The backend ships with two `EMAIL_PROVIDER` implementations:

- **`console`** (default) -- OTP codes are logged through the backend's
  structlog chain. No email is sent. Intended for local development
  only.
- **`resend`** -- OTP codes are delivered through the
  [Resend](https://resend.com) HTTP API. Use this (or any other real
  provider wired in later) for staging and production.

The two endpoints they back are `POST /api/v1/auth/otp/request` and
`POST /api/v1/auth/otp/verify`. See
[`docs/specs/feat_auth_002/`](../specs/feat_auth_002/) for the full
feature spec.

## Provider comparison

| Provider   | Price tier                       | Setup effort                         | Free-tier ceiling       | Primary region |
|------------|----------------------------------|--------------------------------------|-------------------------|----------------|
| Resend     | Free -> $20/mo (50k emails)      | 5-10 min (API key + DKIM/SPF)        | 100/day, 3k/month       | us-east        |
| SendGrid   | Free -> $19.95/mo (40k emails)   | 15-30 min (API key + domain auth)    | 100/day forever         | global         |
| Amazon SES | $0.10/1000 emails (no free tier) | 30-60 min (IAM + DKIM + SES console) | 62k/month when on EC2   | per-region     |
| Postmark   | $15/mo (10k emails)              | 10-20 min (server token + DKIM)      | 100-email developer tier| us / eu        |

## Why the template defaults to Resend

Resend has the simplest API surface (one JSON endpoint, one header)
and a free tier that comfortably covers every use case this template
is likely to see in its first year. When an operator needs to swap to
a different provider the work is localized to
`backend/app/auth/email/resend.py` plus a small dispatch change in
`factory.py` -- there is no SDK or webhook infrastructure to rip out.

## Dev login flow (console provider)

With the default `EMAIL_PROVIDER=console`, no email leaves the stack.
The OTP code lands in the backend's structured log. Extract it with:

```bash
docker compose logs backend | grep auth.email.console_otp_sent | tail -n 1
```

A sample log line looks like:

```json
{"event":"auth.email.console_otp_sent","email_hash":"8b1a9953c4611296a827abf8c47804d7","code":"482917","level":"info","filename":"console.py","func_name":"send_otp","lineno":37,"timestamp":"2026-04-21T14:22:11.004512Z"}
```

Grep for `"code":"` to pull the digits directly:

```bash
docker compose logs backend | grep -o '"code":"[0-9]\{6\}"' | tail -n 1
```

> **Warning.** `EMAIL_PROVIDER=console` is a developer convenience only.
> OTP codes land in plaintext in the log stream; anyone with log
> access (or an external log pipeline) can sign in as any user.
> Switch to a real provider before exposing the backend to the public
> internet.

## Step 1: Create a Resend account

1. Sign up at <https://resend.com>. Free tier, no credit card.
2. Confirm the signup email.
3. Note the default "From" domain Resend hands out on signup -- it's
   usable for small-scale testing but you'll want your own domain for
   anything user-facing.

## Step 2: Verify your sending domain

Resend verifies sending domains through DKIM + SPF DNS records.

1. In the Resend dashboard, pick **Domains** -> **Add Domain**. Enter
   the domain you'll send from (`example.com`, not `mail.example.com`).
2. Resend shows DNS records to add. A typical set:

   | Type  | Name                             | Value                                                        |
   |-------|----------------------------------|--------------------------------------------------------------|
   | TXT   | `_dkim1._domainkey.example.com`  | `v=DKIM1; k=rsa; p=MIIBIjANB...` (long base64)               |
   | TXT   | `resend._domainkey.example.com`  | `v=DKIM1; k=rsa; p=MIIBIjANB...`                             |
   | TXT   | `example.com`                    | `v=spf1 include:amazonses.com ~all` (if you're sending from SES upstream) |
   | MX    | `send.example.com`               | `10 feedback-smtp.us-east-1.amazonses.com`                   |

   Resend will show the exact values for your domain; copy them verbatim.
3. Add the records through your DNS provider's UI. **Propagation can
   take up to 24 hours**; most clear inside an hour. Don't move on
   until Resend's dashboard shows all records as verified.

## Step 3: Generate an API key

1. In the Resend dashboard, pick **API Keys** -> **Create API Key**.
2. Give it a descriptive name (`minimalist-app-prod`, `staging`, etc.).
3. Pick **Sending access** -- OTPs don't need read or management
   scopes.
4. Copy the key out immediately -- Resend only shows it once.

## Step 4: Populate `infra/.env`

Edit (or create) `infra/.env`:

```ini
EMAIL_PROVIDER=resend
EMAIL_FROM=yourdomain <no-reply@example.com>
RESEND_API_KEY=re_XXXXXXXXXXXXXXXXXXXXX
EMAIL_PROVIDER_TIMEOUT_SECONDS=5
```

The `EMAIL_FROM` value is what shows up in the recipient's inbox. Use
an address on the verified domain; mismatch with the DKIM-signed
domain will push the message straight to spam.

Restart the stack: `make down && make up`. Lifespan startup builds the
provider and validates that `RESEND_API_KEY` and `EMAIL_FROM` are both
non-empty. A missing/empty value crashes the backend with a clear
error -- `make up` fails loudly rather than the operator discovering
the problem mid-login.

## Step 5: Verify end-to-end

With the stack running:

```bash
curl -sS -X POST http://localhost:8000/api/v1/auth/otp/request \
    -H 'Content-Type: application/json' \
    -d '{"email": "you@yourdomain.com"}' -i
```

Expected:

- HTTP `204 No Content`.
- An email arrives within a few seconds at `you@yourdomain.com`.
- Inspect the raw email in your client's "view source". Confirm the
  message carries a `DKIM-Signature:` header and that
  `Authentication-Results:` shows `dkim=pass`.

Now verify the code:

```bash
curl -sS -X POST http://localhost:8000/api/v1/auth/otp/verify \
    -H 'Content-Type: application/json' \
    -d '{"email": "you@yourdomain.com", "code": "482917"}' -i
```

Expected: HTTP `200 OK`, `Set-Cookie: session=...`, and a JSON body
with `user_id`, `email`, and `roles`.

## Troubleshooting

| Symptom                                        | Fix                                                                                                                                    |
|------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------|
| Email lands in spam / promotions               | Confirm DKIM pass in headers; add an SPF record if one doesn't exist; warm the sending domain with a handful of replied-to emails.     |
| `dkim=fail` in `Authentication-Results`        | DKIM public key in DNS doesn't match Resend's private key. Re-copy the TXT record from Resend's dashboard; wait for TTL to expire.     |
| `sender-not-verified` error from Resend        | Domain verification did not complete; Resend dashboard will show which record is missing. Re-run DNS verification there.               |
| Resend returns `429 Too Many Requests`         | Upstream rate limit exceeded. The backend swallows this and logs `auth.otp.send_failed`; per-email rate limits in the app itself are looser and get hit first in normal use. |
| Want to swap providers (e.g., to SendGrid)     | Add a new sender class alongside `ResendEmailSender`, extend the `email_provider` Literal in `app/settings.py`, update the factory, and flip `EMAIL_PROVIDER` in `.env`. |

## Rotating credentials

1. In the Resend dashboard, create a new API key with a rotation-
   suffixed name (`minimalist-app-prod-2026Q2`).
2. Update `RESEND_API_KEY` in the environment where the backend runs.
3. Restart the backend (graceful redeploy; no migration needed).
4. In the Resend dashboard, revoke the old key once you've confirmed
   the new key is working (tail `auth.otp.requested` events in the
   backend log for a successful send).

## Test-OTP fixture reminder

The backend also reads two additional settings, `TEST_OTP_EMAIL` and
`TEST_OTP_CODE`. These exist so the external REST test suite
(`tests/tests/test_auth.py`) can drive the OTP flow deterministically.

**They must stay empty in non-test environments.** The factory
(`backend/app/auth/email/factory.py`) refuses to build the email
sender when either variable is set with `ENV != "test"` -- the
backend fails to start. This is deliberate: a leaked production
`.env` with both values set would otherwise let anyone who knew the
test code sign in as the configured canary account.

If you hit `EmailProviderConfigError: TEST_OTP_EMAIL / TEST_OTP_CODE
are set but ENV != 'test'` on startup, clear both values in your
`infra/.env` (or set `ENV=test`, in a genuinely test-only host).

## E2E smoke test

`feat_frontend_002` adds a Playwright e2e suite under
`frontend/tests/e2e/` that drives the full OTP login flow through a
real Chromium. The suite consumes the same `TEST_OTP_EMAIL` /
`TEST_OTP_CODE` pair documented above. It is **not** invoked by
`./test.sh` — it runs as a separate `bun run test:e2e` from the
`frontend/` directory, mirroring how the external REST suite under
`tests/` is invoked.

### One-time setup per machine

```bash
cd frontend
bun install
bunx playwright install chromium
```

Only Chromium is required; the suite uses a single `chromium` project.
Skip `firefox` and `webkit` unless you plan to cross-test manually.

### Configure the fixture

Edit `infra/.env` on the host that will run the stack:

```ini
ENV=test
TEST_OTP_EMAIL=e2e@example.com
TEST_OTP_CODE=424242

# Optional: relax the OTP per-minute/per-hour limits so the suite can
# re-run without tripping 429.
OTP_RATE_PER_MINUTE=60
OTP_RATE_PER_HOUR=600
```

`ENV=test` is required — the backend's `build_email_sender` refuses to
start with the fixture pair set in any other environment.

### Run the suite

From the repo root:

```bash
make up   # brings up backend + postgres + redis + frontend on :5173
```

In another shell, export the same pair so the **Playwright runner**
sees them (the backend reads them out of the compose `env_file`; the
runner reads them out of its own process env, so you have to export
them in the shell where you invoke `bun run test:e2e`):

```bash
export TEST_OTP_EMAIL=e2e@example.com
export TEST_OTP_CODE=424242

cd frontend
bun run test:e2e
```

Expected output: one green test, roughly 10-20 seconds on a warm
Docker host.

### Behavior when the fixture is unset

If you run `bun run test:e2e` without exporting the pair, the suite
prints a clean skip and exits 0 — not a red failure. This mirrors
`tests/tests/test_auth.py`'s `_otp_fixture_env` skip behavior.

### Prod-profile frontend

When the stack is brought up with `--profile prod`, the frontend is
served by nginx on `:8080` instead of Vite on `:5173`. Point
Playwright at the prod origin:

```bash
PLAYWRIGHT_BASE_URL=http://localhost:8080 bun run test:e2e
```

The suite does not hardcode `:5173` outside the Playwright config's
default.

### Rate-limit retry

Two consecutive full runs against the same `TEST_OTP_EMAIL` will trip
the per-minute rate limit. The suite detects a 429 on
`/otp/request` and calls `test.skip('OTP rate limit hit; retry
later')` so a back-to-back invocation does not report a red failure.
Either wait out the `Retry-After` window or bump `OTP_RATE_PER_MINUTE`
in `infra/.env` (both shown above).

> The Playwright suite is **not** a regression gate in `./test.sh`. It
> is an operator smoke test you run locally before merging a PR that
> touches login UI or the OTP flow. Wiring it into CI is deferred to a
> later feature.
