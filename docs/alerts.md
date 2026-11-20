# Email alert episodes (API-06)

## Trigger and episode rules

`app.services.alert_engine.evaluate(session, issued_at)` evaluates the completed
run at that UTC hour. Only points with at least one `active` row in
`alert_subscriptions` are evaluated. API-04 must create that table with
`forecast_point_id` and `status`; the engine references the proposed schema
without creating a competing ORM model or migration.

Only non-shadow forecasts belonging to a `production` model are eligible.
The engine reads all five cut-offs from that model's `model_versions.thresholds`
JSON object, keyed by horizon strings (`1`, `3`, `6`, `12`, `24`). It never reads
model artifacts. Missing, negative or non-finite cut-offs fail evaluation; missing
or partial point forecasts are skipped rather than treated as clean.

Any predicted PM2.5 greater than or equal to its horizon's cut-off triggers an
episode. A new row has severity `unhealthy_sensitive`; its threshold, horizon
and model key come from the earliest exceeding horizon and remain unchanged.
`aqi_table_version` comes from `shared.aqi.AQI_TABLE_VERSION`. Alert thresholds
are model cut-offs, not EPA category boundaries. The initial peak is the highest
PM2.5 across all horizons; ties use the earliest horizon.

While exceeding, the engine updates `last_seen_at` and `latest_forecast_id`
(the earliest exceeding forecast in the latest run). It replaces the episode
peak and peak target time only when a higher value occurs. A forecast wobbling
above and below a cut-off stays in one episode until three clean hourly runs
have elapsed. On resolution, `resolved_at` is the run's `issued_at`. No all-clear
notification is returned. A later exceedance opens a new episode.

### Hourly sequencing requirement

Following #112, resolution uses `issued_at - last_seen_at >= 3 hours`, without a
new counter column. This represents three consecutive clean runs **only when
the pipeline evaluates every hourly run in chronological order without gaps**.
The caller must enforce this requirement; timestamps alone cannot distinguish
missed runs from clean ones. Gap-aware counting needs durable pipeline run
history or a separate evaluation checkpoint before it can be supported.

Evaluate after forecasts are written, before trimming grid forecasts. A run
already recorded as an episode's last exceedance or resolution changes nothing
and returns no notification. Repeating a clean run also changes nothing.
Historical replays are outside the ordered pipeline contract.

The service locks subscribed forecast-point rows in ID order to serialize
concurrent evaluations, and the existing `one_open_alert` index remains the
database safeguard. It flushes changes but leaves commit/rollback to its caller.
The returned `AlertChange(alert_id, forecast_point_id)` list contains only newly
opened episodes. OPS-06 should create notification outbox records in the same
transaction, then send after commit, enforcing one notification per subscription
and episode. Re-evaluating a committed run does not return its opened alerts again.

## Integration status

This implements the API-06 service against the proposed API-04 subscription
schema. Subscription endpoints/tables, pipeline invocation, notification
delivery, and the full PM-06 product/API contract are separate tasks. SQLite
fixture-table tests exercise ORM queries and episode behavior without a pipeline;
PostgreSQL row-lock and partial-index concurrency behavior needs a PostGIS
integration environment.
