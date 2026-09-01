# LGHS Fleet Web UI

This directory contains the next-generation LGHS Fleet operations interface.

The web UI is intentionally separate from the existing curses console. During development, the CLI remains available as an administrative fallback; the browser interface becomes the primary product after security, hardware, and rollout validation.

## Architecture

```text
Browser
  |
  | HTTPS
  v
Cloudflare Access
  |
Cloudflare Tunnel: lghs-fleet-ui
  |
  v
127.0.0.1:8790  LGHS Web Gateway
  |       |
  |       +-- serves Vite production build
  |
  +----------> 127.0.0.1:8789 Fleet API
                     |
                     +-- SQLite/WAL
                     +-- latest telemetry cache
                     +-- commands / deployments / audit
```

The browser never receives the Fleet API admin token.

See [`docs/UI-PLAN.md`](docs/UI-PLAN.md) for the product, UX, telemetry, security, accessibility, and rollout plan.

## Frontend

Stack:

- React + TypeScript
- Vite
- React Router
- TanStack Query
- TanStack Table
- Radix Primitives
- Apache ECharts
- Lucide icons
- Motion for limited functional transitions
- Zod for runtime contract validation as real endpoints are connected

Development defaults to realistic mock data. Mock mode is intentionally limited to development builds.

```bash
cd web-ui
npm install
npm run dev
```

To force the real gateway during Vite development:

```bash
VITE_LGHS_MOCK=0 npm run dev
```

Vite proxies `/api` to `http://127.0.0.1:8790`.

Production build:

```bash
npm run build
```

Production must not silently fall back to mock data. If the gateway is missing or unhealthy, the product displays an explicit controller-data error.

## Gateway

The gateway is a same-origin Backend-for-Frontend (BFF). It exists so browser code does not need controller administrative credentials.

Install its Python dependencies into a dedicated virtual environment:

```bash
python3 -m venv /opt/lghs-web/venv
/opt/lghs-web/venv/bin/pip install -r web-ui/gateway/requirements.txt
```

Required production configuration:

```text
LGHS_WEB_CF_TEAM_DOMAIN=https://<your-team>.cloudflareaccess.com
LGHS_WEB_CF_AUDIENCE=<Access application AUD>
LGHS_WEB_PUBLIC_ORIGIN=https://fleet.scenicrouteservers.com
```

Optional paths default to:

```text
Fleet API:       http://127.0.0.1:8789
Fleet token:     /etc/lghs/fleet-api-tokens.json
Fleet cache:     /var/lib/lghs/fleet-cache.json
Role map:        /etc/lghs/web-roles.json
CSRF secret:     /etc/lghs/web-csrf.key
Static build:    /usr/local/share/lghs-web-ui
```

Create a CSRF secret once on the controller:

```bash
sudo install -d -m 0750 -o root -g root /etc/lghs
sudo sh -c 'umask 077; head -c 48 /dev/urandom > /etc/lghs/web-csrf.key'
```

Role mapping is deny-by-default. Use `gateway/web-roles.example.json` as the schema and install the real file root-readable only. An identity that successfully passes Cloudflare Access but has no LGHS role mapping still receives HTTP 403.

Development/mock mode does not weaken gateway authentication. The browser frontend simply uses local mock data while `import.meta.env.DEV` is true. The production gateway always expects a valid Cloudflare Access assertion.

Run the gateway manually after configuration:

```bash
cd web-ui/gateway
/opt/lghs-web/venv/bin/uvicorn app:app --host 127.0.0.1 --port 8790
```

## Security boundaries

- Cloudflare Access authenticates the user before the request reaches the origin.
- The gateway independently verifies the signed `Cf-Access-Jwt-Assertion`, audience, issuer, and expiry.
- LGHS maps the verified email identity to `owner`, `operator`, or `viewer`.
- Unknown identities are denied.
- Every future mutating endpoint will enforce its minimum role server-side.
- Unsafe same-origin API requests require CSRF validation and expected `Origin`.
- The gateway sets restrictive CSP, frame, referrer, content-type, and browser-feature headers.
- No broad Cloudflare API/tunnel token belongs in the frontend or generic student image.
- No arbitrary shell endpoint is planned for the web dashboard.

## Current implementation status

Implemented foundation:

- application shell/navigation
- Overview
- searchable/filterable Fleet table
- device detail
- alerts view
- deployment list
- sudo approval empty-state/workflow design
- audit/activity timeline
- groups
- settings structure
- responsive light/dark design tokens
- reduced-motion behavior
- accessible status labels
- modular ECharts telemetry chart
- development mock model
- API/query boundary
- read-only authenticated gateway foundation

Still intentionally deferred:

- real telemetry-history persistence/API
- SSE live event stream
- privileged write endpoints
- sudo approve/deny from web
- deployment-create/recovery forms
- maintenance/reboot forms
- Access application/tunnel deployment
- real role configuration
- production service/install integration
- browser/E2E/accessibility testing
- npm lockfile and CI build validation

Those are staged after the foundation so the trust boundary and UI information architecture are stable before adding high-impact controls.

## Cloudflare target

Planned UI tunnel:

```text
Tunnel: lghs-fleet-ui
Host:   fleet.scenicrouteservers.com
Origin: http://127.0.0.1:8790
```

This tunnel should remain separate from the existing device-facing Fleet API tunnel.

## Student tunnel provisioning later

Do not place the controller's broad Cloudflare API token into the student image.

The future provisioning design is controller-mediated: the controller retains infrastructure credentials, creates or obtains only device-scoped tunnel material, and sends that scoped material to an authenticated unprovisioned Pi through the bootstrap channel. Bluetooth can be part of that delivery path after the fresh-image provisioning flow is validated.
