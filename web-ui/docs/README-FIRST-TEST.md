# First Hosted Fleet UI Test Scope

The first hosted test should prove the read path and authentication boundary before privileged writes are enabled.

## Required

- Cloudflare Access protects the public UI hostname.
- Origin validates the Access JWT.
- Verified identity maps to an LGHS role.
- Overview loads real controller state.
- Fleet table loads real device state.
- CS-999 device page loads real current telemetry and health.
- Missing history is shown honestly; no synthetic production chart.
- Alerts page shows authoritative controller warnings or clearly states the read API is not connected.
- Deployments list shows real deployment state.
- Responsive layout works on desktop and phone.
- Dark/light theme follows system and can later gain an explicit toggle.
- Reduced motion disables Signal Field animation.
- UI never receives Fleet admin/Cloudflare/device tunnel secrets.
- Production build passes CI.

## Explicitly disabled for first hosted test

Until the write gateway tests are added, these controls should be visibly disabled or absent rather than pretending to work:

- reboot;
- maintenance changes;
- deployment creation/advance/retry/rollback;
- sudo approve/deny;
- group/tag mutation;
- provisioning/tunnel mutation.

This keeps the first test useful and safe while the visual/read architecture is validated against live LGHS data.
