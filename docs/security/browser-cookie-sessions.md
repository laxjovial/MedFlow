# Browser cookie sessions

## Authentication contract

MedFlow now has two explicit authentication modes:

- Desktop and standalone API clients continue to send `Authorization: Bearer <token>`.
  Their login and desktop-pairing responses continue to include the bearer token.
- First-party browser clients send `X-MedFlow-Web-Session: 1`. The server sets
  `medflow_session` as an HttpOnly cookie and does not return the token in JSON.
  Browser requests use same-origin credentials.

An explicitly supplied Authorization header takes precedence. A malformed or
invalid bearer credential is rejected; it never falls back to a browser cookie.

## CSRF

Unsafe browser requests must send `X-CSRF-Token`, matching the readable
`medflow_csrf` cookie. The value is signed with HMAC-SHA256 and bound to the
HttpOnly session token. The server checks both the double-submit equality and
the signature. GET, HEAD and OPTIONS are exempt; TRACE is not.

Browser login, signup and Google login also require a same-origin Origin header.
This protects login and account-provisioning flows that do not yet have an
authenticated session CSRF token.

## Cookie transport

Both cookies use Path=/ and SameSite=Lax. The session cookie is HttpOnly.
The CSRF cookie is readable by same-origin JavaScript so it can be copied into
the request header.

`SessionConfig.cookie_secure` controls the Secure attribute:

- `None` (default): follow the ASGI request URL scheme.
- `True`: force Secure cookies. Set this when HTTPS terminates at a reverse
  proxy and the ASGI application itself receives HTTP.
- `False`: disable Secure explicitly; use only for controlled local development.

Production deployments must use HTTPS and force `cookie_secure: true` when
the application cannot directly observe the external HTTPS scheme. Do not
trust arbitrary forwarded-proto headers as a substitute for a trusted proxy
configuration.

## Logout and revocation limitation

Browser logout requires an authenticated cookie session and valid CSRF token,
then expires both browser cookies. User activation and temporary-account expiry
are still checked against the live user record on every request.

**This phase does not yet provide a persistent server-side per-session
revocation registry.** A copied signed token remains valid until its expiry,
even after the browser's cookies are cleared. Full session revocation,
device/session inventory, and administrative revocation require a persistent
session identifier/revocation store and are not claimed as complete here.

## XSS and browser limits

HttpOnly prevents JavaScript from reading the session token; it does not stop
an XSS payload from issuing authenticated requests in the victim's browser.
Existing HTML escaping and browser-level XSS testing remain necessary.

## Migration

The browser scripts remove the legacy `medflow.session` localStorage entry
and do not migrate its bearer token into a cookie. The user must sign in again.
Desktop/API bearer clients are unchanged.
