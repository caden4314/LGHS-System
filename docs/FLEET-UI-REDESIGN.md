# Fleet Control UI Simplification

This document defines the next Fleet Control interaction model. The goal is to simplify the current terminal UI without changing the trusted control plane, release authority, Fleet API, SQLite state model, or typed privilege boundaries.

## Why change it

The current dashboard is capable but exposes too many concepts at the same level. The main menu currently separates Fleet, Telemetry, Sudo Requests, Deployments / Updates, Needs Attention, Activity, Notifications, Audit & Logs, and Controller. Device pages then expose another large action menu, while F-key navigation, number shortcuts, search, groups, jobs, refresh, and Backspace/B navigation all compete for memory.

The redesign should optimize for two questions:

1. Is anything wrong or waiting for me?
2. If I select a Pi or deployment, what is the next useful action?

Healthy detail should remain available but should not compete visually with exceptions.

## Design principles

- Status first: important changes, failures, approvals, and active work remain continuously visible.
- Recognition over recall: common actions are shown in a small context footer instead of depending on memorized F-key tables.
- Progressive disclosure: overview first, detail on Enter, actions only when a target is selected.
- Consistent navigation: Up/Down or j/k moves, Enter opens, Esc goes back, / filters, ? opens context help, : opens the command palette, R refreshes.
- Read-only by default: simply browsing never performs SSH or changes fleet state.
- Destructive actions remain explicit and confirmation-gated.
- Text labels always accompany status color; color is never the only signal.
- One hierarchy across terminal sizes. Narrow terminals change layout, not navigation semantics.

## Proposed primary navigation

Reduce the visible top-level navigation from nine destinations to five:

1. Overview
2. Fleet
3. Work
4. Requests
5. Events

Existing destinations are not deleted; they move into the hierarchy where they belong.

- Telemetry becomes part of device detail.
- Deployments, direct updates, active jobs, and recent commands become Work.
- Sudo approvals become Requests.
- Needs Attention is the primary panel on Overview and a saved filter in Events.
- Activity, notifications, warnings, and audit/log indexing become Events.
- Controller health/status becomes an Overview card and command-palette destination.

## Overview

The home screen should be an exception dashboard, not a second Fleet table.

```text
 LGHS 0.6.0 | Controller OK | Fleet 4/4 | Attention 0 | Requests 0 | Active 0

 + NEEDS ATTENTION ------------------+  + ACTIVE WORK ------------------------+
 | No current problems.              |  | No active deployments or commands. |
 |                                   |  |                                     |
 +-----------------------------------+  +-------------------------------------+

 + RECENT EVENTS ------------------------------------------------------------+
 | 10:22 CS-03 telemetry recovered                                           |
 | 10:18 CS-999 signed update completed                                      |
 +---------------------------------------------------------------------------+

 1 Overview  2 Fleet  3 Work  4 Requests  5 Events
 ↑↓ Move   Enter Open   / Filter   : Commands   ? Help   R Refresh
```

When something is wrong, Needs Attention sorts critical items first and makes the affected device the selectable object. Enter opens the relevant device/issue detail directly.

## Fleet

Fleet becomes the canonical list of enrolled Pis. Keep only columns useful for choosing a device:

```text
 DEVICE   STATE   GROUP      VERSION   LAST SEEN   CPU   TEMP
 CS-01    OK      Classroom  0.6.0     2.1s        3%    40C
 CS-02    OK      Classroom  0.6.0     1.7s        2%    39C
 CS-03    CHECK   Classroom  0.6.0     2.4s        5%    45C
 CS-999   OK      Canary     0.6.0     1.3s        1%    46C
```

Commit SHA, service inventory, raw telemetry, update internals, network counters, tags, and sudo history remain available after opening the device. They should not all be visible in the list.

Filtering stays on `/`. Group selection should become a filter chip/picker rather than a global hidden cycle.

## Device detail

Replace the current nine-item device menu with a detail screen. A selected Pi should immediately show the information an operator normally wants:

```text
 CS-03  CHECK   Classroom   main@5595ed3   seen 2.4s

 Health
 ! lghs-policy.service restarting
 ✓ Agent        ✓ Executor      ✓ SSH       ✓ NetworkManager
 ✓ Sudo broker  ✓ Lifecycle     ✓ Release signing

 Resources
 CPU 5%   RAM 7%   Disk 34%   Temp 45C   Wi-Fi -57 dBm

 Update
 Idle | installed 5595ed3 | signed sequence 3

 A Actions   U Update   L Logs   S SSH   Tab Details   Esc Back
```

`Tab` cycles Summary / Health / Update / Telemetry when deeper information is needed. Raw key/value dumps should be moved to a final Diagnostics tab.

## Work

Work combines concepts that are currently split across Deployments / Updates, jobs, update-progress popups, and recent commands.

Default sections:

- Active deployments
- Active direct commands
- Recent completed work

`N` creates a deployment. Enter opens deployment detail. Recovery actions are context actions rather than permanent navigation items.

A direct single-Pi update is still available from Device Actions, but multi-device changes should preferentially use a deployment so canary/health/recovery semantics stay visible.

## Requests

Requests starts with pending sudo approvals. The row should expose device, requester, command summary, age, and expiry. Enter shows full details. Approve/deny remain explicit actions and never share a single accidental keystroke with navigation.

Future human approvals can use the same view instead of adding another top-level screen.

## Events

Merge operator-facing warnings, activity, notifications, and audit index into one time-ordered stream:

```text
 TIME   LEVEL     DEVICE   TYPE       EVENT
 10:22  INFO      CS-03    HEALTH     policy recovered
 10:18  INFO      CS-999   UPDATE     signed release completed
 10:12  WARNING   CS-02    TELEMETRY  stale for 22s
```

`/` filters. Saved quick filters can expose Attention, Updates, Security, Lifecycle, and Controller. Enter drills into the source event or relevant device. Full audit/log text stays in a detail view.

## Command palette

Use `:` as the global command palette. It should support fuzzy matching and make infrequent operations discoverable without filling the normal UI with shortcuts.

Example commands:

- Fleet
- Work
- Requests
- Events
- Controller status
- Release status
- Backup controller
- Open CS-999
- Update selected device
- New deployment
- Jobs
- Quit

The palette is an accelerator, not the only route to common actions.

## Keyboard compatibility

New visible standard:

- Up/Down or j/k: move
- Enter: open/select
- Esc: back/cancel
- /: filter/search current list
- ?: context help
- :: command palette
- R: refresh
- A: context actions when a row/device is selected
- Tab / Shift-Tab: switch detail tabs or panes

Existing F2-F10 and B/Backspace bindings can remain as compatibility aliases for one release, but should disappear from the normal footer/help unless explicitly requested.

## Safety rules

- Read-only navigation never SSH polls.
- Updates continue through the controller-authoritative exact-SHA/signed-release path.
- Reboot, rollback, cancellation, service recovery, and other state-changing actions retain confirmation.
- Multi-device destructive actions show the frozen target set before confirmation.
- Status text must distinguish queued, accepted, running, succeeded, failed, stale, offline, shutdown, and rebooting rather than flattening them into generic colors.

## Implementation strategy

### Phase 1 — interaction cleanup in current curses UI

Do not change framework yet. Implement the five-view hierarchy, Esc back, context footer, simplified Fleet rows, device detail screen, Work consolidation, and command palette while keeping current backend functions.

### Phase 2 — flatten the UI code

The current day2/day3/day4/day5 runtime-extension chain should be replaced with a normal package such as:

```text
controller/lghs_ui/
  app.py
  state.py
  actions.py
  components.py
  screens/overview.py
  screens/fleet.py
  screens/device.py
  screens/work.py
  screens/requests.py
  screens/events.py
```

Pure data/model helpers should remain independently unit-testable so curses rendering is not required for most CI coverage.

### Phase 3 — evaluate Textual, not before

Textual is a strong candidate if the curses renderer becomes the maintenance bottleneck. Its command palette, DataTable, reactive widgets, bindings, and screen/modal model map well to this design. A framework migration should happen only after the simplified information architecture is proven, so interaction redesign and renderer migration are not debugged at the same time.

## Validation

Before replacing production Fleet Control:

- Existing filter/deployment tests stay green.
- Add tests for navigation registry and context actions.
- Add tests that Esc always returns one level and never triggers an action.
- Add tests that dangerous operations always pass through confirmation.
- Add tests for narrow/wide layout using the same navigation model.
- Test through Windows Terminal over the existing remote-admin path.
- Use CS-999 for UI action canaries before enabling the revised interface as the default.

## Research references

Design direction was informed by:

- K9s: consistent `?`, `/`, `:`, Enter, Esc and context-oriented resource views.
- Lazygit: universal navigation bindings, searchable list panels, visible context actions, and confirmation bias for risky operations.
- Textual: built-in fuzzy command palette and structured DataTable behavior.
- Nielsen Norman Group usability heuristics: visibility of system status, consistency, error prevention, recognition rather than recall, efficiency for expert users, and minimalist information hierarchy.
