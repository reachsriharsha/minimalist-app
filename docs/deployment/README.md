# Deployment

External services that need manual setup before production. Each guide
is self-contained and lists the env vars it populates.

- [Email / OTP](email-otp-setup.md) -- required for `feat_auth_002` in
  non-dev environments (Sign in with email OTP).

*(Google OAuth -- added by `feat_auth_003`.)*

Separate from the top-level `deployment/` path reserved by
[`conventions.md` §8](../../conventions.md) for production artifacts
such as Helm charts and Terraform modules.
