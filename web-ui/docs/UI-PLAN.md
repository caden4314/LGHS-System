# LGHS Fleet Web UI — Product, UX, Data, and Security Plan

Status: implementation foundation
Branch: `feature/fleet-web-ui-build`
Target public hostname: `fleet.scenicrouteservers.com`
Target controller origin: `127.0.0.1:8790`

## 1. Product goal

LGHS Fleet is an operations interface for managing Raspberry Pi classroom fleets. It is not a marketing dashboard and it is not an "AI dashboard". The interface should behave like a serious infrastructure administration product: fast, dense where density is useful, explicit about state and freshness, and conservative about destructive actions.

The primary jobs are:

1. See fleet health at a glance.
2. Find a device quickly.
3. Understand why a device is unhealthy.
4. Inspect live and historical telemetry.
5. Deploy LGHS and OS updates safely.
6. Review and resolve sudo requests.
7. Schedule maintenance/reboots.
8. Audit what happened, when, where, and who initiated it.
9. Manage groups, tags, policy, and future device capabilities without redesigning the whole application.

The web UI must remain usable from desktop, tablet, and phone. A later installed application may wrap the same frontend, but the web application is the canonical product.

---

## 2. Design principles

### 2.1 Operational, not decorative

- No hero sections inside the authenticated product.
- No gradients used as decoration.
- No glassmorphism.
- No giant metric cards containing one number and mostly empty space.
- No animated counters.
- No meaningless pie charts.
- No chart where a table, status, or sentence answers the question better.
- No color-only status meaning.
- No hidden critical controls behind hover-only interactions.

### 2.2 State must be obvious

Every fleet/device screen should make these states easy to distinguish:

- Online
- Stale
- Offline
- Healthy
- Warning
- Critical
- Maintenance
- Updating
- Reboot required
- Update failed
- Verification pending

Every live value should have a freshness context. The UI should prefer `last updated 8s ago` over implying that old data is live.

### 2.3 Actions should be harder to perform accidentally than to understand

Read operations are immediate. Mutating operations use clear verbs and a confirmation model proportional to risk.

Examples:

- Add tag: immediate or lightweight confirmation.
- Restart a service: one confirmation.
- Reboot one Pi: confirmation with hostname.
- Reboot a group: confirmation with device count and scope.
- Deploy update: review page showing exact commit, version, target selector, waves, health gates, and maintenance behavior before dispatch.
- Rollback or fleet-wide action: explicit destructive confirmation with target count.
- Sudo approval: show exact command, requester, working directory, age, expiry, and device before approving.

There will be no arbitrary remote shell textbox in the dashboard.

### 2.4 Progressive disclosure

The overview shows what needs attention, not every metric. The Fleet table shows comparable device facts. Device pages hold deep diagnostics. Raw payloads remain available in an advanced/debug view rather than taking over normal workflows.

### 2.5 Keyboard and touch are first-class

Desktop operators should be able to use search, tables, dialogs, menus, and command palette without a mouse. Touch targets are larger on coarse-pointer devices. Focus is always visible.

---

## 3. Information architecture

Persistent navigation:

1. **Overview**
2. **Fleet**
3. **Alerts**
4. **Deployments**
5. **Sudo**
6. **Activity**
7. **Groups**
8. **Settings**

The controller health indicator, global search, signed-in identity, and notifications remain available from the application shell.

### 3.1 Overview

The Overview answers: "Is the fleet okay, and what needs me?"

Layout order:

1. Fleet health summary strip
   - Online / total
   - Critical
   - Warning
   - Offline
   - Updating
2. Needs Attention
   - highest-value actionable issues only
3. Active Deployments
   - progress by wave and health gate
4. Fleet Utilization
   - CPU / memory / storage / temperature trends, summarized rather than one chart per device
5. Recent Activity
   - updates, sudo decisions, reboots, enrollment, health transitions
6. Controller status
   - API/tunnel/database state, only when it needs attention or when expanded

No vanity statistics.

### 3.2 Fleet

A sortable/filterable data table is the primary fleet view.

Default columns:

- Device
- Health
- Connectivity
- Version
- Group
- CPU
- Memory
- Disk
- Temperature
- Wi-Fi
- Uptime
- Last seen
- Update state

Optional columns:

- Model
- RAM size
- Commit
- IP
- RX rate
- TX rate
- Throttling
- Reboot required
- Serial
- Tags

Features:

- Search by hostname/device ID/tag/group.
- Multi-select.
- Saved column visibility locally in the browser.
- Server-side filtering/pagination once fleet size requires it.
- Sticky device column on wide tables.
- Row status does not depend on color alone.
- Bulk actions show the exact selected count.

### 3.3 Device detail

Header:

- Device ID / hostname
- Health
- Online/stale/offline
- Version and commit
- Group/tags
- Uptime
- Last report age
- Primary actions

Tabs:

#### Overview

- Current CPU / memory / disk / temp / Wi-Fi
- Current LGHS/update state
- Important health checks
- Network identity
- Hardware inventory
- Recent activity

#### Telemetry

- Time range selector: 15m, 1h, 6h, 24h, 7d, 30d, custom
- CPU + load
- Memory + swap
- Disk usage
- Temperature
- Wi-Fi signal
- RX/TX rate
- Power/throttling events
- annotations for reboot/update/offline events

#### Health

- Structured health checks grouped by system
- expected vs observed
- severity
- first/last failure if historical data exists
- remediation hint

#### Services

- Core LGHS and system service state
- last transition where available
- controlled restart actions for explicitly approved services

#### Updates

- Current/desired commit
- recent deployments
- execution stages
- verification state
- rollback history

#### Activity

- device-scoped audit timeline

#### Configuration

- groups/tags
- maintenance policy
- desired state
- future device capability configuration

### 3.4 Alerts

Alerts are actionable, not informational noise.

Each alert carries:

- severity
- device/scope
- concise reason
- observed value
- expected value
- first seen
- last seen
- recommended next action
- acknowledgment state
- related device/deployment link

Alert categories initially:

- connectivity
- temperature
- memory pressure
- disk pressure
- inode pressure
- root filesystem read-only
- weak Wi-Fi
- undervoltage
- throttling
- failed systemd units
- clock sync
- Fleet transport
- update failure
- version drift
- reboot required

### 3.5 Deployments

The deployment experience is a workflow rather than a generic form.

Create deployment:

1. Select exact target release/commit.
2. Select target scope.
3. Show resolved devices before creation.
4. Select rollout strategy/waves.
5. Select maintenance behavior.
6. Review health gates.
7. Review summary.
8. Create/dispatch.

Deployment detail:

- exact version and 40-character commit
- creator/time
- target selector snapshot
- wave progression
- device execution table
- stage/progress/errors
- health verification
- pause/resume/retry/cancel/rollback controls
- immutable event timeline

### 3.6 Sudo

Queue-first UI optimized for making a safe decision quickly.

A request includes:

- device
- requester
- exact command
- argv
- working directory
- requested time
- expiry/countdown
- request ID

Approve and deny are both explicit. Approval never generalizes into standing sudo access.

### 3.7 Activity

Unified operational timeline with filters for:

- device
- actor
- kind
- severity
- action
- deployment
- date range

Important writes include the authenticated user identity.

### 3.8 Groups

Manage groups, membership, tags, and group-level maintenance policy. Group pages eventually become useful scope pages with health and deployments, not just configuration forms.

### 3.9 Settings

Sections:

- Fleet controller
- Access and roles
- Telemetry retention
- Health thresholds
- Notifications
- Update defaults
- Tunnel/UI status
- About/build information

Secrets are never displayed in full.

---

## 4. Visual system

### 4.1 Character

Target feel: modern infrastructure console, closer to GitHub/Primer, Grafana, Cloudflare, and mature developer tools than a consumer analytics template.

Properties:

- Neutral surfaces.
- Thin borders rather than excessive shadows.
- Small-to-medium radii.
- Clear spacing rhythm.
- System font stack for speed and native rendering.
- Monospace only for hostnames, command text, IDs, versions, and commits.
- Semantic color reserved for meaning.
- Both dark and light tokens supported; dark is suitable for long operations sessions but not assumed to be the only theme.

### 4.2 Layout tokens

Base spacing unit: 4px.

Common spacing:

- 4px micro
- 8px tight
- 12px control internal
- 16px normal
- 24px section
- 32px page section

Radius:

- 4px controls
- 6px panels
- 8px dialogs

Desktop table density: 36–40px rows.
Touch/coarse pointer density: 44–48px targets.

### 4.3 Status presentation

Status always uses at least two channels, e.g. icon + text and optionally color.

Semantic classes:

- neutral
- info
- success
- warning
- critical
- maintenance
- updating

Do not use green to mean "online" and then another unrelated green for a chart series.

### 4.4 Charts

Charts answer trend/comparison questions only.

Preferred chart types:

- line: time series
- area: capacity only when fill adds meaning
- horizontal bar: category comparison
- event markers: reboot/update/offline events
- compact sparkline: small device trend where useful

Avoid by default:

- pie/donut charts
- radial gauges
- 3D charts
- stacked charts unless the parts truly form a whole
- dual-axis charts unless absolutely necessary

All charts provide:

- units
- visible time range
- hover/focus detail
- accessible text description/table fallback where practical
- no misleading smoothing
- no animation after initial load for continuously updating telemetry

Apache ECharts is selected for telemetry visualization because it supports large datasets, streaming/dynamic updates, Canvas/SVG rendering, data zoom, and ARIA descriptions. Import only required components to limit bundle size.

---

## 5. Motion and animation

Animation communicates state change; it does not decorate the dashboard.

Rules:

- Most hover/focus transitions: 100–150ms.
- Drawer/popover/dialog transitions: roughly 140–200ms.
- Avoid page-wide sliding transitions.
- Avoid bouncing/springy status indicators.
- No pulsing online dots.
- Loading uses static skeletons or restrained progress indicators.
- New alert rows may briefly emphasize background/border, then settle.
- Live numerical updates do not count upward from old values.
- Chart transitions are disabled or minimized during high-frequency updates.
- `prefers-reduced-motion` is honored globally.

Motion is optional to the meaning of every interaction.

---

## 6. Frontend architecture

Selected stack:

- React 19
- TypeScript
- Vite 8
- React Router 7
- TanStack Query
- TanStack Table
- Radix Primitives
- Apache ECharts
- Motion, used sparingly
- Lucide icons
- Zod for runtime API validation
- CSS design tokens and authored CSS; no template theme

Why:

- Vite gives a small static production build that the Pi can serve cheaply.
- React has a mature component/tooling ecosystem and supports a future desktop wrapper.
- Radix provides tested focus, keyboard, ARIA, dialog, menu, popover, and tooltip behavior without dictating visual style.
- TanStack Query handles server state/cache/retry/invalidation.
- TanStack Table keeps fleet tables flexible without adopting a visually heavy grid product.
- ECharts covers serious time-series needs without building a chart engine ourselves.
- Zod prevents silently trusting malformed API payloads.

### 6.1 Client state boundaries

Server state belongs in TanStack Query.

URL state:

- page
- filters worth sharing/bookmarking
- selected time range
- device tab

Local UI state:

- sidebar collapsed state
- column visibility
- density/theme preferences
- temporary dialog state

Do not mirror server data into a global client store.

### 6.2 Realtime model

Use REST for snapshots/history/actions and Server-Sent Events (SSE) for live one-way updates from controller to browser.

Reasons:

- telemetry/events flow primarily server -> browser
- browser reconnect behavior is built in
- event IDs support resume semantics
- simpler operational model than a bidirectional WebSocket connection

Writes remain explicit HTTP requests.

---

## 7. Controller web gateway (BFF)

The browser must never receive the Fleet API admin token.

Architecture:

```
Browser
  |
  | HTTPS
  v
Cloudflare Access
  |
Cloudflare Tunnel: lghs-fleet-ui
  |
127.0.0.1:8790
  |
LGHS Web Gateway / BFF
  |
  +--> static web build
  +--> local Fleet API 127.0.0.1:8789 using root-readable admin token
  +--> telemetry history/read model
```

The web gateway is a separate service from the device-facing Fleet API. This creates a clear trust boundary and lets the UI tunnel be managed independently.

Suggested gateway implementation:

- FastAPI
- Uvicorn
- `httpx` for local API calls
- PyJWT cryptographic JWT validation for Cloudflare Access assertions

The gateway binds only to `127.0.0.1` unless explicitly configured otherwise.

---

## 8. Authentication and authorization

### 8.1 Authentication

Production authentication is Cloudflare Access in front of `fleet.scenicrouteservers.com`.

Preferred login option: Cloudflare account-member identity or an existing trusted IdP with MFA. Email OTP may remain an emergency/fallback method, not the primary long-term owner login.

The gateway validates the `Cf-Access-Jwt-Assertion` signature, issuer, expiry, and application audience. It does not trust an email header by itself.

The application displays the authenticated identity in the shell and logs out through Cloudflare Access.

No LGHS password database is created.

### 8.2 Authorization

Application roles:

- **owner** — all Fleet actions and access administration
- **operator** — normal fleet operations, updates, maintenance, sudo decisions
- **viewer** — read-only

Start deny-by-default. Every mutating endpoint checks authorization server-side. Hiding a button is not authorization.

Future authorization can become attribute/scoped:

- allowed groups
- allowed actions
- school/class scope
- temporary elevation

### 8.3 Step-up safety

Critical actions may require a recent authenticated session, e.g. access token `iat` within a configured period, plus confirmation. This avoids building a second password prompt while still allowing reauthentication requirements later.

---

## 9. Browser/API security baseline

Required controls:

- Cloudflare Access deny-by-default policy.
- Origin bound to loopback behind Tunnel.
- Access JWT validation at the gateway or explicit cloudflared Access validation plus gateway verification.
- App authorization on every protected request.
- CSRF cookie-to-header token for state-changing requests.
- Validate `Origin` for writes.
- `Content-Security-Policy` with same-origin assets only; no CDN scripts.
- `frame-ancestors 'none'`.
- `object-src 'none'`.
- `base-uri 'none'`.
- `form-action 'self'`.
- `X-Content-Type-Options: nosniff`.
- strict Referrer Policy.
- permissions policy denying unneeded browser features.
- no secret/token in localStorage.
- no Fleet admin token in browser bundles or responses.
- no sensitive telemetry stored by a service worker.
- no arbitrary shell execution API.
- request body size limits.
- write rate limits.
- audit every privileged action with user identity.
- logs redact authentication/session secrets.

---

## 10. Telemetry data model

### 10.1 Live payload

Target metrics from a student Pi:

System:

- uptime_seconds
- boot_id
- kernel
- reboot_required

CPU:

- cpu_pct
- load1
- load5
- load15
- cpu_frequency_hz where available

Memory:

- memory_used_bytes
- memory_total_bytes
- mem_pct
- swap_used_bytes
- swap_total_bytes

Storage:

- root_used_bytes
- root_total_bytes
- root_free_bytes
- disk_pct
- inode_pct
- root_readonly

Thermal/power:

- temp_c
- undervoltage_now/history
- throttled_now/history
- raw throttle flags

Network:

- primary interface
- IPv4/IPv6 where safe/useful
- Wi-Fi interface
- signal dBm
- RX total bytes
- TX total bytes
- optional link speed

LGHS:

- version
- commit
- role
- agent version
- update state/stage/progress
- desired version/commit

Services/health:

- structured health checks
- failed units
- required service states
- controller transport freshness

Inventory:

- hostname
- Pi model
- RAM MB
- serial

### 10.2 Persistence strategy

The agent may continue reporting approximately every 5 seconds for fast command/state propagation, but not every report needs a permanent time-series row.

Initial retention proposal:

- Latest snapshot: every report.
- Persistent high-resolution telemetry: at most one sample per device per 30 seconds, retained 24 hours.
- 5-minute aggregates: retained 90 days.
- 1-hour aggregates: optional long-term retention, e.g. one year.
- State transitions/events: retained according to audit policy and not downsampled like metrics.

This keeps SQLite practical on the controller while preserving useful history.

### 10.3 Aggregation

For each numeric time bucket keep appropriate values:

- min
- max
- average
- last
- sample count

Counters such as network RX/TX are used to derive rates and reset safely across reboot/counter reset.

### 10.4 Query behavior

The history API chooses an appropriate resolution based on requested range. The browser should not download hundreds of thousands of points and downsample them itself.

---

## 11. Analytics philosophy

LGHS analytics are operational analytics, not business vanity analytics.

Use the USE method where appropriate for device resources:

- Utilization
- Saturation
- Errors

Examples:

- CPU utilization + load/saturation + health errors
- memory utilization + pressure + OOM/health errors
- storage utilization + inode pressure + read-only/errors
- network throughput + weak signal/disconnect errors

Fleet summary calculations should prefer distributions and outliers over averages that hide unhealthy machines.

Useful aggregate questions:

- Which Pis need attention now?
- Which devices are hottest?
- Which devices consistently have weak Wi-Fi?
- Which versions/commits are in the fleet?
- Is a deployment improving or degrading health?
- Which machines are frequently offline?
- Are power/throttle events concentrated in certain hardware?

---

## 12. Accessibility baseline

Target WCAG 2.2 AA for the application.

Requirements:

- Semantic HTML first.
- Keyboard operation for every action.
- Visible `:focus-visible` treatment.
- Minimum target sizing/spacing appropriate to WCAG 2.2.
- Dialog focus trap and focus return.
- Correct labels for icon-only controls.
- `aria-sort` and appropriate table semantics.
- Dynamic operation feedback exposed as status messages/live regions without stealing focus.
- Status never conveyed by color alone.
- Charts have descriptions and textual values.
- Reduced motion preference respected.
- Layout remains useful at 200% zoom.
- Mobile tables preserve access to all data through deliberate responsive patterns, not clipped content.

---

## 13. Performance targets

The UI runs on a Raspberry Pi controller but most rendering work occurs in the browser.

Initial targets:

- Static shell should load quickly on local/LAN-quality connections.
- Keep initial JS route small by lazy-loading telemetry charts and advanced pages.
- Import ECharts components on demand.
- Do not refresh data faster than its useful update frequency.
- Use SSE to invalidate/update current data rather than aggressive polling.
- Use table virtualization only if fleet size makes it necessary; normal semantic tables are simpler for small fleets.
- Historical telemetry is server-downsampled.
- Avoid browser persistence of large live datasets.

---

## 14. Responsive behavior

Desktop:

- persistent sidebar
- dense Fleet table
- multi-column Overview/Device layouts

Tablet:

- collapsible sidebar
- fewer default table columns
- telemetry still chart-first

Phone:

- bottom/sheet navigation or collapsed menu
- fleet rows become focused summary rows/cards where a full table would be unusable
- important actions remain reachable but dangerous bulk actions are not promoted
- charts use shorter vertical layouts and touch-friendly tooltips

Responsive design does not mean hiding critical data permanently. Detail moves to drill-down views when width is limited.

---

## 15. Updateability and future functionality

The web product should be an independently versioned component of LGHS.

Principles:

- frontend assets built in CI
- gateway/API contracts versioned
- UI can display frontend build version and controller API version
- rolling LGHS updates install assets atomically
- old static assets may coexist briefly so an open browser does not break during deployment
- `index.html` is no-cache; hashed assets are long-cache immutable
- frontend catches Vite preload errors and asks/reloads safely after a deployment
- feature routes can be added without reorganizing the application shell
- capability flags from the server determine availability of new features

Future feature areas already have a natural place:

- classroom/group views -> Groups
- remote approved actions -> device Actions / Activity
- imaging/provisioning status -> Fleet / Provisioning route
- backup/recovery -> device/configuration or dedicated Recovery route
- software/package inventory -> Device detail
- security posture -> Health / Alerts
- tunnel inventory -> Device network/configuration

---

## 16. Cloudflare tunnel/token boundary

The UI tunnel is separate from the device-facing Fleet API tunnel.

Proposed:

- Tunnel name: `lghs-fleet-ui`
- Hostname: `fleet.scenicrouteservers.com`
- Origin: `http://127.0.0.1:8790`

The controller Cloudflare API token used to manage tunnels is an infrastructure secret and must not be copied into generic student images.

Future unprovisioned-Pi tunnel setup should use controller-mediated provisioning. A safer future flow is:

1. Student first boot authenticates to controller over the existing bootstrap channel.
2. Controller creates/assigns only the device-specific tunnel credentials required by that Pi.
3. Controller delivers scoped credentials over the authenticated bootstrap transport (Bluetooth is a candidate).
4. Student stores them root-only and starts its tunnel.
5. Broad Cloudflare account/API tokens remain on the controller.

This is intentionally deferred until the website foundation and fresh-image provisioning are stable.

---

## 17. Implementation phases

### Phase A — foundation (current)

- product/UX/security architecture
- React/Vite TypeScript scaffold
- design tokens
- application shell
- Overview skeleton with realistic mock fleet data
- navigation routes
- API types/client boundary
- responsive baseline

### Phase B — secure controller gateway

- FastAPI gateway on `127.0.0.1:8790`
- Cloudflare Access JWT verification
- user/role mapping
- CSRF protection
- security headers
- read-only Fleet API proxy
- static production asset serving

### Phase C — real data

- devices
- device detail
- groups
- deployments
- current telemetry
- health/alerts
- controller status
- SSE live invalidation

### Phase D — telemetry history

- schema migration for time-series samples/rollups
- sampler/aggregator
- history API
- ECharts telemetry pages
- event annotations

### Phase E — operations

- sudo queue and decisions
- update/deployment workflows
- maintenance policies
- reboot schedules
- confirmations and action audit identity

### Phase F — hardening

- permission tests
- CSRF tests
- Access JWT tests
- UI accessibility tests
- browser integration tests
- performance/bundle budgets
- failure/offline behavior
- audit review

### Phase G — application packaging

After browser behavior is stable:

- PWA/static install behavior if appropriate
- optional Tauri desktop wrapper using the same remote application/auth model
- no duplicated business logic

---

## 18. Research references

This plan intentionally borrows established patterns instead of inventing them.

- Grafana dashboard best practices and USE/RED guidance: https://grafana.com/docs/grafana/latest/visualizations/dashboards/build-dashboards/best-practices/
- Grafana alerting best practices: https://grafana.com/docs/grafana/latest/alerting/guides/best-practices/
- GitHub Primer DataTable guidance/accessibility: https://primer.style/product/components/data-table/
- Atlassian design foundations/tokens: https://atlassian.design/foundations
- Atlassian data visualization color guidance: https://atlassian.design/foundations/color-new/data-visualization-color/
- Radix Primitives accessibility: https://www.radix-ui.com/primitives/docs/overview/accessibility
- TanStack Query: https://tanstack.com/query/latest
- TanStack Table: https://tanstack.com/table/latest
- Apache ECharts accessibility/features: https://echarts.apache.org/handbook/en/best-practices/aria/ and https://echarts.apache.org/en/feature.html
- Motion reduced-motion guidance: https://motion.dev/docs/react-accessibility
- WCAG 2.2: https://www.w3.org/TR/WCAG22/
- Cloudflare Access self-hosted application guidance: https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/
- Cloudflare Access application-token validation: https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/application-token/
- OWASP Authorization Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html
- OWASP CSRF Prevention Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html
- OWASP CSP Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Content_Security_Policy_Cheat_Sheet.html
- OWASP Session Management Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html
