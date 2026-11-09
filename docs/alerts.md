# Email alerts contract (PM-06)

Status: contract for Phase 4. Owner: Tin. Issue: #109. Builds on the scope freeze (`docs/scope.md` §4, §10, §11), decision #45 (alert trigger) and decision #47 (this contract).

What each Phase 4 issue builds:

| Issue | What | Owner | Sections |
|---|---|---|---|
| API-04 #110 | `alert_subscriptions`, `alert_notifications` tables | Shresta | 3 |
| API-05 #111 | subscribe / confirm / unsubscribe endpoints, `cell.active_alert` | Shresta | 2 |
| API-06 #112 | episode engine (forecasts → `alerts`) | Phuong (Miaoqing reviews cut-offs) | 4 |
| API-07 #113 | mail backends, templates, Mailpit | Vuong | 5, 6 |
| OPS-06 #114 | post-run alert job: episodes, sending, clean-up | Vuong | 4, 5, 7 |
| WEB-05 #115 | sign-up form, token pages, in-app warning | Malije | 6c, 8 |
| PM-07 #116 | Phase 4 gate, privacy note, teardown | Vuong, Tin | 7, 9 |

Every alert is an **experimental model estimate, not an official warning**.

## 1. Overview and flow

```
subscribe (email + ZIP or point) ──► pending ──► confirmation email (double opt-in)
        │                                              │ link → frontend page → POST /alerts/confirm
        │                                              ▼
        │                                           active ──► alert email when an episode opens
        │                                              │ link or one-click → POST /alerts/unsubscribe
        ▼                                              ▼
  unconfirmed after 48 h → deleted              row deleted (hard delete)
```

- **Location → one grid cell.** A subscription covers exactly one California grid cell (`forecast_points.kind = 'grid_cell'`), resolved the same way as `GET /forecast/point` (PR #100):
  - ZIP → `zip_codes.forecast_point_id` (row must have a `forecast_point_id`; otherwise 404 `zip_not_found`).
  - lat/lon → `lookup_grid_forecast_point(lon, lat)`; no cell → 404 `out_of_scope`, the same error as `/forecast/point`.
  - The email never determines the location. No forecast point is created.
- **One subscription per email.** A new subscribe for an email that already has an active subscription does not change anything until the new request is confirmed; confirming it replaces the old subscription (section 3).
- Only grid cells are alerted on. Monitor forecast points are never subscribed to.

## 2. Endpoints (API-05, #111)

All under `/api/v1`, JSON in and out, errors in the shared `Error` shape (`docs/api.md` → Errors). Request and response bodies are in `docs/api/openapi.yaml` (`components/schemas/Alert*`, strict). API-05 adds the three `paths` entries with the routes, plus POST support in the spec tooling (`validate.py`, `fixture_manifest.json`, `tests/test_api_contract.py`, `frontend/scripts/sync-api.mjs` all assume GET today), and the fixtures for them.

**Validation errors are 400 `invalid_query`**, as for every other endpoint (`docs/api.md`): FastAPI's default 422 is mapped to 400 by the existing handlers.

### `POST /alerts/subscriptions`

Body (`AlertSubscribeRequest`): `{"email", "zip"}` or `{"email", "lat", "lon"}`, exactly one location form.

| Response | When |
|---|---|
| `202 {"status": "pending_confirmation"}` | Every valid request, whether or not the email is known, already pending or already active (no account enumeration). |
| 400 `invalid_query` | Bad JSON, bad email, both or neither location forms, `lat` without `lon`. |
| 404 `out_of_scope` | lat/lon outside California. |
| 404 `zip_not_found` | No California ZCTA for that ZIP. |

What happens on a valid request:
1. `email` is trimmed and lower-cased. `lat`/`lon` are rounded to 2 decimals after the cell is resolved (the cell comes from the exact point; only the rounded point is stored).
2. **Rate limit first:** at most 3 confirmation emails per email per 24 h. If the email's pending row has `confirmation_sends_24h >= 3` and `last_confirmation_sent_at` less than 24 h ago, nothing changes (the row and its last link stay valid), no email is sent, and the response is still 202. The counter resets to 0 when `last_confirmation_sent_at` is more than 24 h old, so the limit is at least as strict as "3 per 24 h".
3. Otherwise, if the email has a **pending** row it is updated in place: new location, new confirm token (the old link stops working), `confirm_expires_at = now + 48 h`, counter + 1, `last_confirmation_sent_at = now`. If not, a new pending row is inserted with the counter at 1. An existing **active** row is left alone until the new one is confirmed.
4. The confirmation email is sent through the mail backend (section 5) after the row is committed, and an `alert_notifications` row (`kind = 'confirmation'`) records `sent` or `failed`. A failed confirmation email is not retried (the raw token is gone); the user subscribes again.

### `POST /alerts/confirm`

Body (`AlertTokenRequest`): `{"token"}`.

| Response | When |
|---|---|
| `200 {"status": "confirmed"}` | The token matches a pending row that has not expired. The row becomes `active`, `confirmed_at = now`. If the email had another active row, that row is deleted in the same transaction (its notifications cascade). |
| `200 {"status": "already_confirmed"}` | The token matches a row that is already `active`. |
| 404 `invalid_token` | Malformed token, or no row has this `confirm_token_hash` (never issued, replaced by a newer subscribe, unsubscribed, or deleted after 48 h). |
| 410 `token_expired` | The row is still pending and `confirm_expires_at` has passed, but the alert job has not deleted it yet (at most about an hour; after that, 404). |

### `POST /alerts/unsubscribe`

Body (`AlertTokenRequest`): `{"token"}`. Also accepts the RFC 8058 one-click POST from mail providers: `POST /api/v1/alerts/unsubscribe?token=…` with a form body `List-Unsubscribe=One-Click` (`application/x-www-form-urlencoded`). The token comes from the query string in that form.

| Response | When |
|---|---|
| `200 {"status": "unsubscribed"}` | A well-formed token. If a row has this `unsubscribe_token_hash`, it is deleted (hard delete, notifications cascade). If none does, it was already deleted, so the same 200 is returned (idempotent). |
| 404 `invalid_token` | Malformed token (not 43 base64url characters). After a hard delete a used token can't be told apart from an unknown one, so 404 is only for malformed tokens. |

Unsubscribe tokens don't expire. Unsubscribing a pending row is allowed too.

### Email links never change state

Email links open **frontend** pages, which read the token from the URL and call the POST endpoint. A GET never changes state, because mail scanners prefetch links.

| Email link | Page | Calls |
|---|---|---|
| `{FRONTEND_BASE_URL}/alerts/confirm?token=…` | confirm page | `POST /api/v1/alerts/confirm` |
| `{FRONTEND_BASE_URL}/alerts/unsubscribe?token=…` | unsubscribe page | `POST /api/v1/alerts/unsubscribe` |

The `List-Unsubscribe` header points at the API itself (`{API_BASE_URL}/api/v1/alerts/unsubscribe?token=…`), since mail providers POST to it directly.

### In-app warning: `cell.active_alert` on `GET /forecast/point`

Additive, optional field (v1 rule), already in the spec and the point fixtures:

```json
"active_alert": {
  "severity": "unhealthy_sensitive",
  "first_triggered_at": "2024-07-27T09:00:00Z",
  "peak_pm25_predicted": 105.1,
  "peak_target_time": "2024-07-28T00:00:00Z",
  "horizon_hours": 6
}
```

- From the cell's open `alerts` row (`status = 'open'`, `severity = 'unhealthy_sensitive'`). `null` when there is none. Clients treat a missing field as `null` (the DB repository may not send it until API-05).
- `peak_pm25_predicted` is truncated to 0.1 like every `pm25`. `horizon_hours` is the horizon of the peak forecast (the `alerts.horizon_hours` column).
- Every active grid cell is evaluated each run (section 4), so `active_alert` works for any California location, subscribed or not. It is the in-app fallback if email slips (scope §10).

### CORS

The API allows `GET` only today. API-05 adds `POST` and the `Content-Type` request header for `/api/v1/alerts/*`, for the same `CORS_ALLOWED_ORIGINS`, still with no credentials. The one-click POST comes from mail servers, not browsers, so CORS does not apply to it.

## 3. Tables (API-04, #110)

Full column tables are in `docs/schema.md` → `alert_subscriptions` and `alert_notifications`. The migration is API-04's. The rules:

- `alert_subscriptions`: one row per subscription.
  - The email is stored trimmed and lower-cased. The location is `forecast_point_id` (a grid cell) plus either `zip` or `query_lat`/`query_lon` rounded to 2 decimals (~1 km). The exact point is never stored.
  - `status` is `pending | active | unsubscribed`. Unsubscribe deletes the row, so `unsubscribed` is never stored by v1; the value stays in the CHECK for audit or a later soft delete.
  - Raw tokens are never stored; the table holds their SHA-256 hashes (hex).
    - **Confirm token:** 32 random bytes (`secrets.token_bytes(32)`), base64url. It is only needed in the confirmation email, which is sent in the same request.
    - **Unsubscribe token:** 32 bytes, `HMAC-SHA256(ALERTS_TOKEN_SECRET, "unsubscribe:" + id)`, base64url. The alert job builds unsubscribe links hours or days after subscribe, so the token has to be re-derivable without storing it. Changing `ALERTS_TOKEN_SECRET` invalidates every unsubscribe link already sent, so don't change it before teardown.
  - At most **one pending and one active row per email**: two partial unique indexes, `(email) WHERE status = 'pending'` and `(email) WHERE status = 'active'`. Confirming deletes the old active row in the same transaction (section 2), so after confirm there is again one row. A single index on `status IN ('pending','active')` would block "replace the location after re-confirmation", because the new pending row would collide with the active one.
- `alert_notifications`: one row per email attempt.
  - `UNIQUE (subscription_id, alert_id)` is the "at most one email per subscription per episode" guarantee. Postgres treats NULLs as distinct, so confirmation rows (`alert_id IS NULL`) don't collide.
- **Deletion:**
  - Unsubscribe is a hard delete of the subscription; its notifications cascade.
  - Pending rows are deleted by the alert job once `confirm_expires_at` has passed, 48 h after the last confirmation email (section 5).
  - Deleting an `alerts` row cascades to its notifications.

## 4. Episode rules (API-06, #112)

Reuses the existing `alerts` table (episodes: one open row per `(forecast_point_id, severity)`, `latest_forecast_id ON DELETE SET NULL`). No new table and no new column.

- **When.** Once after each successful pipeline run (`pipeline_runs.status = 'success'`, i.e. after `finish_run`), on that run's cycle: `issued_at` and `model_key` from the `pipeline_runs` row. Grid rows of the cycle are `forecasts` with that `issued_at` and `model_key`, `source = 'idw'`, `is_shadow = false`. Shadow forecasts are never used.
- **Which cells.** **All active grid cells** (`forecast_points.kind = 'grid_cell' AND active`), whether or not anyone subscribed, plus any cell that still has an open episode. This way `cell.active_alert` works everywhere as the in-app warning. That is about 3,000 cells × 5 horizons per run, done as one set-based query over the cycle's rows, not a loop per cell. **Emails still go only to `active` subscriptions** (section 5). Episode rows hold no personal data.
- **Cut-offs.** Per horizon, from `model_versions.thresholds` of the cycle's `model_key` (JSONB `{"1": 35.5, "3": 29.5, "6": 25.5, "12": 21.5, "24": 20.0}` for baseline_v2, copied from `release.json` at registration by `mlops/registry.py`). Never hard-coded.
  - If `thresholds` is NULL (e.g. the pipeline's stub model) or a horizon is missing, that horizon is not evaluated. If none is left, the job opens and updates nothing and logs one warning.
- **Exceedance.** A cell exceeds in a cycle when any horizon's `pm25_predicted` (stored value, not truncated) is ≥ that horizon's cut-off.
- **Open** (cell exceeds, no open row): insert an `alerts` row with
  - `severity = 'unhealthy_sensitive'`, `status = 'open'`
  - `first_triggered_at = last_seen_at = issued_at`
  - `pm25_threshold` = the cut-off of the **triggering horizon**, the earliest horizon that exceeds
  - `peak_pm25_predicted`, `peak_target_time`, `horizon_hours` = the highest `pm25_predicted` of the cycle across all horizons, its `target_time` and its horizon
  - `model_key` = the cycle's model; `aqi_table_version` = `shared.aqi.AQI_TABLE_VERSION` (`epa-2024`)
  - `latest_forecast_id` = the forecast row of the triggering horizon.
- **Continue** (cell exceeds, open row exists):
  - Set `last_seen_at = issued_at` and `latest_forecast_id`.
  - Update `peak_pm25_predicted` / `peak_target_time` / `horizon_hours` only if the new cycle's max is higher.
  - `pm25_threshold` and `model_key` keep their values from creation.
- **Resolve** (cell has a forecast this cycle, none exceeds, open row exists): set `status = 'resolved'`, `resolved_at = issued_at` once there have been **3 consecutive successful runs with no exceedance**. Without a new column, this is counted as: this cycle is clear and at least 3 successful `pipeline_runs` have `issued_at > last_seen_at`. Waiting 3 runs stops an episode flapping open and closed every hour.
- **No forecast** for the cell in this cycle (no monitor within 50 km): no change, except that the episode resolves if `last_seen_at` is more than 24 h before `issued_at`.
- A cell that exceeds again after resolving opens a **new** episode (new emails, subject to the 24 h cap in section 5).
- Grid forecasts keep only the newest run (`finish_run`), so `latest_forecast_id` of a grid episode becomes NULL at the next successful run. That is expected; the trigger facts are copied onto the row.
- **Stated limitation:** the cut-offs were tuned on monitor forecasts (decision #30); grid values are IDW blends of monitor forecasts, so grid alerts inherit that approximation. Cells more than 25 km from the nearest usable monitor (`low_confidence_dist_km`) still alert, and the email says the forecast is lower confidence.

## 5. Sending (API-07 #113, OPS-06 #114)

The **alert job** (OPS-06) runs once after each successful pipeline run, in this order: episode engine (section 4), sending, clean-up.

- **Who gets an email.** For every open episode, every `active` subscription of that cell that has no `alert_notifications` row for that episode gets one alert email. The row is inserted before the send; `UNIQUE (subscription_id, alert_id)` makes a second email for the same episode impossible.
  - This covers a newly opened episode and a subscription confirmed while an episode is already open.
  - No email is sent when an episode resolves (no all-clear email).
- **Safety cap.** At most 1 alert email per subscription per 24 h, even if a new episode opens: skip the subscription if it has a `kind = 'alert'`, `status = 'sent'` row with `sent_at` in the last 24 h. Nothing is written for a skipped send, so it goes out on the first run after the cap clears if the episode is still open, and never if it has resolved.
- **Retries.** A failed send leaves the row `status = 'failed'`, `attempts = n`, `error` = a short reason (no address, no token). The next runs retry rows with `status = 'failed'` and `attempts < 3` while the episode is open. After the 3rd failed attempt the row stays `failed` for good. A success sets `status = 'sent'`, `sent_at`.
- **Clean-up.** Delete `pending` rows whose `confirm_expires_at` has passed (48 h after the last confirmation email).
- **Mail backends** (config in `app/core/config.py`; the alert job reads the same settings):

| Setting | Values | Default |
|---|---|---|
| `ALERTS_MAIL_BACKEND` | `console`, `smtp` | `console` |
| `ALERTS_MAIL_FROM` | e.g. `SmokeSense alerts <alerts@…>` | none; required when `smtp` |
| `ALERTS_SMTP_HOST`, `ALERTS_SMTP_PORT` | Mailpit: `mailpit`, `1025` | — |
| `ALERTS_FRONTEND_BASE_URL` | the map's origin, used in email links | — |
| `ALERTS_API_BASE_URL` | the API's origin, used in `List-Unsubscribe` | — |
| `ALERTS_TOKEN_SECRET` | random, ≥ 32 bytes | none; required |

  - `console` logs the message with the recipient masked (`t***@domain`) and tokens in links replaced by `…`, so it is for checking templates, not for clicking through.
  - `smtp` → Mailpit locally (compose), on staging and in the demo: mail is captured in the Mailpit UI and never delivered. A real provider is used only if time allows (scope §4).
  - The from address and base URLs are always config, never hard-coded.
- **Headers and format** of every alert email:
  - `List-Unsubscribe: <{ALERTS_API_BASE_URL}/api/v1/alerts/unsubscribe?token=…>`
  - `List-Unsubscribe-Post: List-Unsubscribe=One-Click`
  - the unsubscribe link in the body
  - `multipart/alternative`: plain text plus simple HTML. No images, no remote content, no tracking pixels, no link tracking.

## 6. Email copy

`{placeholders}` are filled by the template. Times are local, `America/Los_Angeles`, formatted like `Sat, Jul 27, 5 PM PDT`.

- `{place}` is `ZIP {zip}` for a ZIP subscription, or `{query_lat}, {query_lon}` (the stored 2-decimal point) for a point.
- `{map_url}` is `ALERTS_FRONTEND_BASE_URL` with the location; WEB-05 picks the query form, e.g. `/?zip=95928`.

### a. Confirmation email

Subject: `Confirm your SmokeSense smoke alerts for {place}`

```
Hi,

Someone asked SmokeSense to email this address when wildfire smoke is
forecast for {place}.

To turn on the alerts, open this link:
{confirm_url}

The link expires in 48 hours ({expires_local}).

If this wasn't you, ignore this email. Nothing more will be sent unless the
link is used, and the request is deleted after 48 hours.

SmokeSense is a student forecast project, not an official source.
```

### b. Alert email

Subject: `Smoke alert for {place}: unhealthy for sensitive groups expected`

```
SmokeSense's model expects that smoke near {place} may reach levels that are
unhealthy for sensitive groups.

Forecast PM2.5, issued {issued_local}:
{for each horizon that reaches its cut-off, earliest first}
  - In {horizon_hours} h, around {target_local}: {pm25} µg/m³ ({aqi_label})
{end}

{if nearest_monitor_dist_km > low_confidence_dist_km}
The nearest air monitor is {nearest_monitor_dist_km} km away, so this
forecast is lower confidence.
{end}

What this means
Smoke at this level can affect people with heart or lung disease (including
asthma), older adults, children, pregnant people and people who work or
exercise outdoors. Some values above may be below the official "Unhealthy for
Sensitive Groups" level (35.5 µg/m³). The model tends to under-predict heavy
smoke, so we alert at a lower value for longer forecasts.

What you can do
  - Check current conditions before spending time outside.
  - Cut back on hard or long outdoor activity.
  - Keep windows and doors closed when it smells smoky. Use an air purifier
    or set your AC to recirculate if you have one.
  - If you have asthma or heart or lung disease, keep your medicine close
    and follow your care plan.

See the forecast on the map: {map_url}

SmokeSense is a student forecast, not an official source. Check AirNow.gov
and your local air district and public health agency.

You get at most one SmokeSense alert a day.
Unsubscribe: {unsubscribe_url}
```

`{pm25}` is truncated to 0.1 and `{aqi_label}` comes from `shared/aqi.py` (the HTML version may color it with the category color). The HTML version has the same text and links, with no images.

### c. Result pages (WEB-05)

| Page, result | Text |
|---|---|
| Confirm, `confirmed` | **You're signed up.** We'll email you when SmokeSense's model expects smoke unhealthy for sensitive groups at your location, at most once a day. Every email has a one-click unsubscribe link. |
| Confirm, `already_confirmed` | **You're already signed up.** Nothing else to do. |
| Confirm, 410 `token_expired` | **This link has expired.** Confirmation links last 48 hours. Sign up again from the map to get a new one. |
| Confirm, 404 `invalid_token` | **This link isn't valid.** It may have been replaced by a newer sign-up. Sign up again from the map. |
| Unsubscribe, `unsubscribed` | **You're unsubscribed.** Your email address and location have been deleted. You won't get any more SmokeSense alerts. |
| Unsubscribe, 404 `invalid_token` | **This link isn't valid.** Check that you copied the whole link from the email. |
| Either, other error | **Something went wrong.** Please try again in a minute. |

## 7. Privacy and teardown (PM-07, #116)

- **Stored:** email (lower-cased), grid cell, ZIP or a point rounded to 2 decimals, status, token hashes, timestamps, notification outcomes.
- **Not stored:** names, IP addresses, user agents, the exact location, raw tokens.
- **Never logged:**
  - Full email addresses: always masked as `t***@domain`.
  - Tokens, and URLs or request parameters that contain them (CLAUDE.md rule 6).
  - `alert_notifications.error` holds no address or token.
- **Deleted:**
  - Unconfirmed sign-ups after 48 h, when their link expires (alert job).
  - A subscription immediately on unsubscribe.
- **Teardown:**
  - After the recorded demo and before Senior Design Day, delete every row of `alert_notifications` and `alert_subscriptions`, and clear Mailpit.
  - Record the date and row counts in #116.
  - Nothing is kept after 12/11: there is no hosting after Senior Design Day (scope §11).

**Privacy note under the sign-up form** (final text):

> We use your email and the location you choose only to send SmokeSense smoke alerts. We store your email and the forecast area (a 12.5 km grid square, plus your ZIP or a point rounded to about 1 km), never your name or exact location. Every alert has a one-click unsubscribe link, and unsubscribing deletes your data immediately. SmokeSense is a student project: all subscriber data is deleted by December 11, 2026.

## 8. UI half (WEB-05, #115), for Malije to review

- **Sign-up form** (on the location card, under the forecast):
  - Fields: email, plus either a ZIP field or "Use this location", which sends the card's current `lat`/`lon` or `zip`.
  - The privacy note (section 7) and the experimental-estimate line are shown under the form.
- **States:**
  - Submitting: button disabled.
  - Any 202: **"Check your email"**, with the address shown back and "the link expires in 48 hours". This is also what a rate-limited request sees; the UI can't tell, by design.
  - 400 `invalid_query`: inline field error.
  - 404 `out_of_scope` / `zip_not_found`: "SmokeSense only covers California" / "We couldn't find that ZIP".
  - 5xx or network error: "Something went wrong, try again".
- **Token pages** `/alerts/confirm?token=…` and `/alerts/unsubscribe?token=…`:
  - On load they POST once and show the result texts in section 6c.
  - They never act on a GET by themselves beyond that single POST, and never put the token in analytics or logs.
- **In-app warning** on the location card, driven by `cell.active_alert` from `/forecast/point`. When it is not null, show a banner:

  > "Model expects smoke unhealthy for sensitive groups. Peak about {peak_pm25_predicted} µg/m³ around {peak_target_time, local}. Experimental model estimate, not an official warning."

  - Use the category color from `/meta`; don't hard-code thresholds or colors.
  - This is also the fallback if email slips (scope §10).
- Nothing about alerts changes the public statewide map.

## 9. Acceptance per issue

**API-04 #110 (tables)**
- [ ] Alembic migration creates `alert_subscriptions` and `alert_notifications` exactly as in `docs/schema.md`, with every CHECK, FK, unique and partial index; `downgrade` drops them.
- [ ] SQLAlchemy models in `app/models/`; status and kind values in `app/models/values.py`.
- [ ] Tests: a second pending row and a second active row for one email fail; a pending row next to an active one works; a duplicate `(subscription_id, alert_id)` fails; deleting a subscription cascades.

**API-05 #111 (endpoints)**
- [ ] The three POST paths are added to `openapi.yaml` using the existing `Alert*` schemas, with fixtures. The spec tooling (`validate.py`, `fixture_manifest.json`, the contract tests, `sync-api.mjs`) handles non-GET operations, and CI is green.
- [ ] Subscribe returns the same 202 for new, pending, active and rate-limited emails; the 4th request in 24 h sends no email.
- [ ] Confirm: `confirmed`, `already_confirmed`, 410 after 48 h, 404 for unknown or replaced tokens; confirming replaces the previous active row.
- [ ] Unsubscribe: JSON body and RFC 8058 form POST both work; a repeat returns 200; malformed → 404; the row is gone.
- [ ] `cell.active_alert` is filled from the open episode; CORS allows POST for `/api/v1/alerts/*`.
- [ ] No route logs an email or token; tests use `caplog` to check.

**API-06 #112 (episodes)**
- [ ] Cut-offs read from `model_versions.thresholds` of the cycle's model; NULL thresholds → no episodes, one warning.
- [ ] Tests for open / continue (peak only rises) / resolve after 3 clear runs / no forecast + 24 h resolve / re-open makes a new row / shadow rows ignored / every active grid cell evaluated, with or without a subscription (a cell with no subscribers gets an episode and no email).
- [ ] One run over the full grid finishes in seconds on staging (set-based SQL, no per-cell loop).
- [ ] Miaoqing reviews the cut-off handling and the IDW limitation note.

**API-07 #113 (sender)**
- [ ] `console` and `smtp` backends chosen by `ALERTS_MAIL_BACKEND`; Mailpit in docker compose and on staging.
- [ ] Templates render the section 6 copy (text + HTML) with `List-Unsubscribe` and `List-Unsubscribe-Post`; no images or tracking.
- [ ] Console output masks the recipient and tokens.

**OPS-06 #114 (alert job)**
- [ ] Runs once after each successful pipeline run (never after a failed one), in the order episodes → send → clean-up.
- [ ] Exactly one email per subscription per episode, at most one per 24 h, failed sends retried up to 3 attempts.
- [ ] Unconfirmed rows deleted after 48 h.
- [ ] A staging-only way to force a test exceedance for one cell, which never runs in production.

**WEB-05 #115 (UI)**
- [ ] Form, states, token pages and in-app banner as in section 8; texts from section 6c; privacy note under the form.
- [ ] Types come from `npm run gen:api`; MSW mocks for the three endpoints.

**PM-07 #116 (gate, privacy, teardown)**
- [ ] Privacy note shown in the UI.
- [ ] Teardown done and recorded before Senior Design Day.
- [ ] **Done for the 11/24 gate:** a staging demo of subscribe → confirm (link from Mailpit) → a forced test exceedance → exactly one alert email in Mailpit, with nothing extra on the next run → unsubscribe → the row is gone from `alert_subscriptions`.
