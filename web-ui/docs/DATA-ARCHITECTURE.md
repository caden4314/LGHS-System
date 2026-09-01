# LGHS Fleet Web — Telemetry, Analytics, and Data Architecture

## Decision

For the first production web dashboard, keep operational state and telemetry history in the controller's existing SQLite database instead of adding Prometheus, InfluxDB, or VictoriaMetrics immediately.

This is a deliberate small-fleet decision, not a claim that SQLite is the best time-series database at every scale.

Reasons:

- LGHS already has a transactional SQLite/WAL control-plane database.
- Agents already **push** structured reports into the Fleet API; adding Prometheus would introduce a second pull-oriented collection path or a translation service.
- A classroom fleet generates a modest number of series and the dashboard needs a fixed, known set of metrics.
- One database keeps backup, restore, migrations, deployment, and failure recovery simpler on a Raspberry Pi controller.
- Core rollups use normal SQL aggregates rather than a custom time-series engine.
- Event/audit data already belongs with the control plane and should not be split from deployment/device records without a reason.

Prometheus remains a strong option if LGHS later needs a standards-compatible observability endpoint or much larger metric cardinality. Its TSDB provides efficient block storage, WAL recovery, retention, and roughly 1–2 bytes/sample under typical conditions. VictoriaMetrics is also a future option for a dedicated low-resource time-series backend. Neither is required to make the first school fleet dashboard reliable.

The gateway/API contract should therefore avoid exposing SQLite-specific concepts so storage can be replaced later without rewriting the React application.

References:

- SQLite WAL: https://www.sqlite.org/wal.html
- SQLite aggregate functions: https://www.sqlite.org/lang_aggfunc.html
- SQLite window functions: https://www.sqlite.org/windowfunctions.html
- Prometheus local storage: https://prometheus.io/docs/prometheus/latest/storage/
- VictoriaMetrics single-node: https://docs.victoriametrics.com/victoriametrics/single-server-victoriametrics/

---

## Source-of-truth clocks and identity

Every telemetry report has multiple useful identifiers:

- `device_id`
- `boot_id`
- agent `sequence`
- agent `sent_at`
- controller `received_at`

Use **controller `received_at` as the canonical time-series timestamp**. Device `sent_at` is retained for diagnosing clock skew and transmission delay but should not be trusted for primary ordering before clock synchronization is known-good.

The tuple `(device_id, boot_id, sequence)` provides report identity/deduplication semantics.

A reboot creates a new `boot_id`. Counter-rate calculations never cross a boot boundary.

---

## Live path vs history path

Do not make historical storage slow down command delivery.

```text
Agent report (~5s)
    |
    v
Fleet API ingest
    |
    +--> update latest device snapshot immediately
    +--> command/sudo/audit processing immediately
    |
    +--> history sampler decides whether this report needs persistence
```

The latest snapshot is updated on every valid report.

The first history target is one persisted high-resolution telemetry sample per device per 30 seconds. A report received between persistence intervals still updates live state but does not create another history row.

This preserves responsive fleet status while bounding write volume.

---

## Proposed schema

Core numeric metrics use typed columns. Do not put frequently queried metrics only inside JSON blobs.

```sql
CREATE TABLE telemetry_samples (
    device_id TEXT NOT NULL,
    received_at REAL NOT NULL,
    sent_at REAL,
    boot_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,

    cpu_pct REAL,
    load1 REAL,
    load5 REAL,
    load15 REAL,
    cpu_frequency_hz INTEGER,

    memory_used_bytes INTEGER,
    memory_total_bytes INTEGER,
    mem_pct REAL,
    swap_used_bytes INTEGER,
    swap_total_bytes INTEGER,

    root_used_bytes INTEGER,
    root_total_bytes INTEGER,
    root_free_bytes INTEGER,
    disk_pct REAL,
    inode_pct REAL,
    root_readonly INTEGER,

    temp_c REAL,
    wifi_signal_dbm REAL,
    rx_bytes INTEGER,
    tx_bytes INTEGER,

    throttled_now INTEGER,
    undervoltage_now INTEGER,
    reboot_required INTEGER,

    PRIMARY KEY (device_id, received_at),
    UNIQUE (device_id, boot_id, sequence)
);

CREATE INDEX telemetry_samples_time
    ON telemetry_samples(received_at);
```

Additional low-frequency or forward-compatible measurements may live in an `extras_json` column, but a metric should graduate to a typed column once the product filters, sorts, alerts, or charts it regularly.

### Rollup table

```sql
CREATE TABLE telemetry_rollup_5m (
    device_id TEXT NOT NULL,
    bucket_start REAL NOT NULL,
    sample_count INTEGER NOT NULL,

    cpu_avg REAL,
    cpu_max REAL,
    mem_avg REAL,
    mem_max REAL,
    disk_last REAL,
    temp_avg REAL,
    temp_max REAL,
    wifi_avg REAL,
    wifi_min REAL,
    rx_bytes_delta INTEGER,
    tx_bytes_delta INTEGER,

    PRIMARY KEY (device_id, bucket_start)
);
```

The exact migration belongs in the existing Fleet database migration system, not as an ad-hoc standalone database.

---

## Retention

Initial policy:

| Data | Resolution | Retention |
| --- | --- | --- |
| Latest snapshot | latest only | while device exists |
| Raw/high-res telemetry | 30 seconds | 24 hours |
| Standard rollup | 5 minutes | 90 days |
| Long rollup | 1 hour | optional 1 year |
| State transitions | event | audit/event policy |
| Deployment/sudo audit | event | audit policy; never downsampled as metrics |

Retention settings should eventually be configurable from Settings with conservative safe limits.

Cleanup runs in bounded batches so deleting old data cannot hold a large write transaction during active fleet ingest.

---

## Rollup calculations

Do not average everything blindly.

CPU:
- average
- max

Memory:
- average
- max

Disk:
- last value for capacity trend
- max where alert analysis needs it

Temperature:
- average
- max

Wi-Fi signal:
- average
- minimum (worst signal)

Network counters:
- first and last valid counter inside a boot boundary
- delta converted to bytes/second at query time or stored as bucket delta
- a negative delta means reset/invalid sample, never negative traffic

Health state:
- stored as events/transitions rather than averaging severity

---

## Query API

The browser requests a time range and desired metric set. The server selects resolution.

Examples:

```text
GET /api/v1/devices/CS-999/telemetry?range=1h&metrics=cpu,mem,temp
GET /api/v1/devices/CS-999/telemetry?from=<ts>&to=<ts>&resolution=auto
```

`resolution=auto` policy example:

- <= 6h: raw 30s samples
- <= 7d: 5m rollups
- > 7d: 1h rollups

Responses should be bounded by a maximum point count. The API, not the browser, performs large-range downsampling.

This keeps mobile clients fast and prevents a chart from downloading hundreds of thousands of points it cannot meaningfully render.

---

## Live updates

Use Server-Sent Events for one-way controller -> browser operational updates.

Suggested event types:

```text
device.snapshot
device.health.changed
device.connectivity.changed
deployment.changed
sudo.requested
sudo.resolved
alert.opened
alert.resolved
controller.status
```

Events carry IDs so a reconnecting browser can resume where appropriate. REST remains the source for authoritative snapshots and all writes.

The frontend invalidates the relevant TanStack Query cache entry rather than maintaining a second giant global state store.

---

## Analytics

The overview is not a generic BI page. Fleet analytics answer operational questions.

### USE-oriented hardware analytics

For resources, apply the USE model:

- Utilization
- Saturation
- Errors

Examples:

CPU:
- utilization: CPU %
- saturation: load relative to core count
- errors: throttling/thermal health events

Memory:
- utilization: used %
- saturation: memory pressure/swap/OOM indicators
- errors: OOM/service failure events

Storage:
- utilization: disk %
- saturation: inode pressure / low-free-space trajectory
- errors: read-only filesystem / I/O-related failures when available

Network:
- utilization: throughput where useful
- saturation/quality: Wi-Fi signal and future retry/link information
- errors: connectivity transitions / Fleet transport failures

### Fleet aggregation

Prefer distributions/outliers over fleet averages.

Useful queries:

- hottest devices now
- devices above disk thresholds
- lowest Wi-Fi signal
- most frequently offline devices over 7d
- devices with repeated undervoltage/throttling events
- version/commit distribution
- deployment success/failure/verification duration
- before-vs-after deployment health changes

An average temperature across 30 Pis is rarely actionable if one Pi is overheating.

---

## Alert handling

Alert state must not be reconstructed solely in the browser.

The controller owns:

- current open/closed state
- first seen
- last seen
- severity
- device/scope
- observed value
- expected threshold
- acknowledgment
- related event/deployment

The browser filters and renders server-owned alert state.

Threshold changes should not rewrite history. Preserve the threshold/rule context needed to explain why an alert existed at the time.

---

## Data sent by student devices

Collect only what the product can justify.

Default telemetry should include machine health and LGHS state, not student activity.

Do collect:

- CPU/memory/storage/temperature
- hardware inventory
- service health
- update state
- network interface health/traffic counters
- Wi-Fi signal
- LGHS version/commit
- reboot/power/throttle state

Do **not** collect by default:

- Wi-Fi passwords
- browser history
- document contents
- keystrokes
- screenshots
- arbitrary process command lines
- student files
- secrets/tokens

If a future diagnostic feature needs sensitive data, it must be an explicit new capability with authorization, audit, retention, and UI disclosure designed for it.

---

## Scale trigger for a dedicated TSDB

Do not migrate storage because a different database looks more sophisticated.

Re-evaluate SQLite when measured operation shows one or more of:

- sustained write contention affecting Fleet commands/API latency
- telemetry database size becoming operationally difficult on the controller
- dashboard queries exceeding latency targets after indexing/rollups
- fleet size/cardinality growing far beyond the school deployment model
- need for PromQL/ecosystem integration
- need for independent metric replication/remote storage

At that point, the frontend contract remains the same and the gateway/query service can move history to Prometheus/VictoriaMetrics or another TSDB.
