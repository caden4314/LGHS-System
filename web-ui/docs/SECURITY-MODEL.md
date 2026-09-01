# LGHS Fleet Web Security Model

## Trust boundaries

1. Internet/browser is untrusted.
2. Cloudflare Access authenticates a human identity before the public origin route.
3. LGHS web gateway validates the signed Access JWT at the origin and maps the verified identity to an LGHS role.
4. Fleet API admin token remains controller-local and is never serialized to the browser.
5. Student device tokens authenticate only their own report/command channels.
6. Cloudflare account API token remains controller-local.
7. Per-device remotely-managed tunnel tokens may be issued to one authenticated student bootstrap session only.

## Roles

- `viewer`: read fleet state/history/events.
- `operator`: viewer plus approved routine operations.
- `owner`: operator plus security/configuration/rollout policy and future identity-management operations.

Default is deny. A valid Cloudflare identity that is absent from the LGHS role map is not an authorized Fleet user.

## Browser session

Cloudflare Access owns the external login session. LGHS does not store a separate password database.

The gateway validates:

- JWT signature against Cloudflare Access keys;
- issuer/team domain;
- application audience;
- expiry and required claims;
- authorized email -> LGHS role mapping.

State-changing requests additionally require:

- same expected Origin;
- LGHS CSRF/custom header token;
- route-specific role;
- schema/input validation;
- target authorization;
- audit record;
- idempotency/replay strategy for operations where duplicate submission matters.

## Browser hardening

- `Content-Security-Policy` default deny outside self.
- no framing (`frame-ancestors 'none'` + X-Frame-Options defense-in-depth).
- `X-Content-Type-Options: nosniff`.
- restrictive Permissions Policy.
- no third-party scripts, fonts or analytics in the admin surface by default.
- no localStorage for high-value secrets.
- no Fleet API token in JavaScript.
- no Cloudflare API token in JavaScript.

## Operational action UX

Sensitive controls must not be easy to trigger accidentally.

Confirmation should state:

- action;
- device/group/all-fleet scope;
- immutable deployment commit/version when applicable;
- maintenance/reboot impact;
- whether rollback exists;
- whether the operation is immediately dispatched.

Do not use a generic `Are you sure?` dialog for destructive or fleet-wide operations.

## Logging

Every privileged web action should generate an audit event containing verified actor identity, role, action type, normalized target/scope, controller request ID/idempotency key, result, and timestamps. Secrets and full tunnel tokens are excluded.
