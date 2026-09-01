# LGHS Fleet Web UI Test Bundle

This bundle is for pre-release validation. It is not a release and does not change the LGHS release branch.

## Fastest visual test on Windows

1. Extract the bundle.
2. Open PowerShell in the `web-ui` folder.
3. Run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\START-WINDOWS-PREVIEW.ps1
```

The launcher opens `http://127.0.0.1:5173/` and uses the built-in mock fleet only. It does not contact LGCSCONT or send commands.

Check these first:

- Overview hierarchy and Signal Field artwork.
- Desktop and narrow/mobile layouts.
- Fleet search, status/group filters, sorting, and CS-999 drill-down.
- Light/dark theme behavior and persistence.
- Alerts, deployments, sudo, activity, groups, and settings navigation.
- Keyboard focus visibility and readable status states.
- Reduced-motion behavior if your OS has reduced motion enabled.

## Automated validation

From the `web-ui` folder:

```powershell
npm install --no-audit --no-fund
npm run build
npx playwright install chromium
npm run test:e2e
```

CI runs the same production frontend build, browser acceptance suite, gateway compilation/security tests, and deployment-shell validation before publishing the downloadable test artifact.

## Production bundle

`dist/` contains the compiled Vite frontend.

`gateway/` contains the FastAPI BFF that validates Cloudflare Access identity and proxies the controller Fleet API.

`deploy/` contains the controller deployment files. The service is designed to bind only to `127.0.0.1:8790` and remain deny-by-default until Cloudflare Access configuration and an explicit role mapping are supplied.

Do not expose the local gateway directly to the Internet and do not enable write operations during this first UI acceptance pass.

## What is intentionally not live yet

- Fleet write actions in the web console.
- Sudo approval writes.
- Historical telemetry charts until controller history storage/API is connected.
- Public Fleet UI tunnel until the local controller service passes acceptance.

The UI should show unavailable/preview states for these instead of pretending they are functional.
