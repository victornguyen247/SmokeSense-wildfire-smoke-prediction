"""Initial SmokeSense schema

Revision ID: 0001
Revises:
Create Date: 2026-09-25

PM-01 deliverable — initial live-DB schema.

Apply:     make migrate
Roll back: docker compose exec backend alembic downgrade base

Notes for reviewers
───────────────────
1. PostGIS extension is created first — all GEOGRAPHY columns depend on it.
2. Alembic autogenerate does NOT produce GiST indexes or PostGIS column types.
   Every spatial index and geography column below was added by hand.
3. Surrogate primary keys (TEXT id columns) hold UUIDv7 values (time-ordered),
   generated in the application layer until PostgreSQL 18 ships uuidv7().
   Time-series tables use natural composite keys instead.
4. Value lists use TEXT + CHECK rather than Postgres ENUMs — ENUMs are hard to
   evolve in Alembic (can't remove values; adding has transaction caveats).
5. Daily range partitioning on observations, fire_detections,
   weather_observations, and weather_forecasts uses native Postgres
   partitioning — no pg_partman, so the stock postgis/postgis image works.
   This migration creates the create_daily_partitions() SQL function, a
   DEFAULT partition per table, and the first days of partitions. The daily
   Celery maintenance job calls create_daily_partitions() to stay ahead and
   drops expired partitions (see docs/schema.md → Retention Policy).
6. Primary keys and unique indexes on partitioned tables must include the
   partition key — hence fire_detections uses (id, detected_at) and
   (satellite, external_id, detected_at).
7. Verify this migration runs clean on a fresh volume:
       docker compose down -v && make up && make migrate
"""

from alembic import op

# Alembic metadata
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Daily-partitioned tables → (days back, days ahead) of partitions to create.
# Days back = retention window (docs/schema.md), so the first ingestion run's
# backfill lands in real partitions, not DEFAULT. weather_forecasts looks
# further ahead because NWS hourly forecasts run ~7 days out.
PARTITIONED_TABLES = {
    "observations": (3, 3),
    "fire_detections": (7, 3),
    "weather_observations": (3, 3),
    "weather_forecasts": (3, 8),
}


def create_initial_partitions(table: str) -> None:
    """DEFAULT partition (safety net) + daily partitions across the retention window."""
    back, ahead = PARTITIONED_TABLES[table]
    op.execute(f"CREATE TABLE {table}_default PARTITION OF {table} DEFAULT")
    op.execute(
        f"SELECT create_daily_partitions('{table}', current_date - {back}, "
        f"current_date + {ahead})"
    )


# ─────────────────────────────────────────────
# Upgrade
# ─────────────────────────────────────────────

def upgrade() -> None:

    # ── 0. Extensions ──────────────────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    # Creates one partition per UTC day in [p_from, p_to], named
    # <parent>_pYYYYMMDD. Idempotent — the daily Celery job calls it to keep
    # partitions ahead of incoming data.
    op.execute("""
        CREATE OR REPLACE FUNCTION create_daily_partitions(
            p_parent TEXT, p_from DATE, p_to DATE
        ) RETURNS void LANGUAGE plpgsql AS $$
        DECLARE
            d DATE;
        BEGIN
            FOR d IN SELECT generate_series(p_from, p_to, interval '1 day')::date LOOP
                EXECUTE format(
                    'CREATE TABLE IF NOT EXISTS %I PARTITION OF %I FOR VALUES FROM (%L) TO (%L)',
                    p_parent || '_p' || to_char(d, 'YYYYMMDD'),
                    p_parent,
                    d::timestamp AT TIME ZONE 'UTC',
                    (d + 1)::timestamp AT TIME ZONE 'UTC'
                );
            END LOOP;
        END
        $$
    """)

    # ── 1. Reference tables ────────────────────────────────────────────────

    # cities
    op.execute("""
        CREATE TABLE cities (
            id          TEXT        PRIMARY KEY,
            name        TEXT        NOT NULL,
            state       TEXT        NOT NULL CHECK (char_length(state) = 2),
            timezone    TEXT        NOT NULL,
            geom        GEOGRAPHY(POINT, 4326),

            UNIQUE (name, state)
        )
    """)
    op.execute("CREATE INDEX ix_cities_geom ON cities USING gist (geom)")

    # zip_codes
    op.execute("""
        CREATE TABLE zip_codes (
            zcta                TEXT        PRIMARY KEY,
            state               TEXT        NOT NULL,
            geom                GEOGRAPHY(POINT, 4326),
            area_km2            FLOAT,
            forecast_point_id   TEXT        -- FK added after forecast_points exists
        )
    """)
    op.execute("CREATE INDEX ix_zip_codes_geom ON zip_codes USING gist (geom)")

    # forecast_points  (replaces locations)
    op.execute("""
        CREATE TABLE forecast_points (
            id                  TEXT        PRIMARY KEY,
            kind                TEXT        NOT NULL
                                    CHECK (kind IN ('city','zip','grid_cell','adhoc')),
            label               TEXT        NOT NULL,
            h3_cell             TEXT,
            city_id             TEXT        REFERENCES cities(id),
            geom                GEOGRAPHY(POINT, 4326) NOT NULL,
            timezone            TEXT        NOT NULL,
            always_forecast     BOOLEAN     NOT NULL DEFAULT TRUE,
            last_requested_at   TIMESTAMPTZ,
            active              BOOLEAN     NOT NULL DEFAULT TRUE,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_forecast_points_geom      ON forecast_points USING gist (geom)")
    op.execute("CREATE INDEX ix_forecast_points_city_id   ON forecast_points (city_id)")
    op.execute("CREATE INDEX ix_forecast_points_forecast  ON forecast_points (always_forecast, last_requested_at)")

    # now that forecast_points exists, add the FK on zip_codes
    op.execute("""
        ALTER TABLE zip_codes
            ADD CONSTRAINT fk_zip_forecast_point
            FOREIGN KEY (forecast_point_id) REFERENCES forecast_points(id)
    """)

    # monitors
    op.execute("""
        CREATE TABLE monitors (
            id              TEXT        PRIMARY KEY,
            source          TEXT        NOT NULL CHECK (source IN ('airnow','purpleair')),
            external_id     TEXT        NOT NULL,
            name            TEXT,
            city_id         TEXT        REFERENCES cities(id),
            location_type   TEXT        NOT NULL DEFAULT 'outdoor'
                                CHECK (location_type IN ('outdoor','indoor')),
            geom            GEOGRAPHY(POINT, 4326) NOT NULL,
            elevation_m     FLOAT,
            active          BOOLEAN     NOT NULL DEFAULT TRUE,
            first_seen_at   TIMESTAMPTZ NOT NULL,
            last_seen_at    TIMESTAMPTZ,

            UNIQUE (source, external_id)
        )
    """)
    op.execute("CREATE INDEX ix_monitors_geom         ON monitors USING gist (geom)")
    op.execute("CREATE INDEX ix_monitors_source_active ON monitors (source, active, location_type)")

    # ── 2. Live time-series tables (partitioned) ───────────────────────────

    # observations  — partitioned by valid_at (daily)
    op.execute("""
        CREATE TABLE observations (
            monitor_id      TEXT        NOT NULL REFERENCES monitors(id),
            valid_at        TIMESTAMPTZ NOT NULL,
            received_at     TIMESTAMPTZ NOT NULL,
            ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            pm25            FLOAT       NOT NULL CHECK (pm25 >= 0),
            correction      TEXT        NOT NULL
                                CHECK (correction IN
                                    ('regulatory','purpleair_raw','purpleair_barkjohn')),
            pm25_cf1_a      FLOAT       CHECK (pm25_cf1_a >= 0),
            pm25_cf1_b      FLOAT       CHECK (pm25_cf1_b >= 0),
            rh_pct          FLOAT       CHECK (rh_pct BETWEEN 0 AND 100),
            qa_flag         TEXT,
            data_status     TEXT        CHECK (data_status IN ('preliminary','validated')),

            PRIMARY KEY (monitor_id, valid_at)
        ) PARTITION BY RANGE (valid_at)
    """)
    op.execute("CREATE INDEX ix_observations_valid_at ON observations (valid_at DESC)")

    create_initial_partitions("observations")

    # fire_detections  — partitioned by detected_at (daily)
    op.execute("""
        CREATE TABLE fire_detections (
            id                  TEXT        NOT NULL,
            external_id         TEXT        NOT NULL,
            satellite           TEXT        NOT NULL
                                    CHECK (satellite IN (
                                        'MODIS_Terra','MODIS_Aqua',
                                        'VIIRS_SNPP','VIIRS_NOAA20','VIIRS_NOAA21')),
            product             TEXT        NOT NULL
                                    CHECK (product IN ('URT','RT','NRT','SP')),
            geom                GEOGRAPHY(POINT, 4326) NOT NULL,
            detected_at         TIMESTAMPTZ NOT NULL,
            received_at         TIMESTAMPTZ NOT NULL,
            ingested_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            confidence_raw      TEXT        NOT NULL,
            confidence_level    TEXT        NOT NULL
                                    CHECK (confidence_level IN ('low','nominal','high')),
            frp_mw              FLOAT       CHECK (frp_mw >= 0),
            bright_t31_k        FLOAT,
            scan_km             FLOAT       CHECK (scan_km > 0),
            track_km            FLOAT       CHECK (track_km > 0),
            daynight            TEXT        CHECK (daynight IN ('D','N')),

            PRIMARY KEY (id, detected_at)
        ) PARTITION BY RANGE (detected_at)
    """)
    op.execute("CREATE INDEX ix_fire_detections_geom        ON fire_detections USING gist (geom)")
    op.execute("CREATE INDEX ix_fire_detections_detected_at ON fire_detections (detected_at DESC)")
    op.execute("""
        CREATE UNIQUE INDEX uq_fire_detections_dedup
            ON fire_detections (satellite, external_id, detected_at)
    """)

    create_initial_partitions("fire_detections")

    # weather_observations  — partitioned by valid_at (daily)
    op.execute("""
        CREATE TABLE weather_observations (
            station_id      TEXT        NOT NULL,
            valid_at        TIMESTAMPTZ NOT NULL,
            received_at     TIMESTAMPTZ NOT NULL,
            geom            GEOGRAPHY(POINT, 4326) NOT NULL,
            wind_speed_ms   FLOAT       CHECK (wind_speed_ms >= 0),
            wind_dir_deg    FLOAT       CHECK (wind_dir_deg BETWEEN 0 AND 360),
            temp_c          FLOAT,
            rh_pct          FLOAT       CHECK (rh_pct BETWEEN 0 AND 100),
            pressure_hpa    FLOAT       CHECK (pressure_hpa > 800),
            precip_1h_mm    FLOAT       CHECK (precip_1h_mm >= 0),
            qc_flag         TEXT,

            PRIMARY KEY (station_id, valid_at)
        ) PARTITION BY RANGE (valid_at)
    """)
    op.execute("CREATE INDEX ix_weather_obs_valid_at ON weather_observations (valid_at DESC)")
    op.execute("CREATE INDEX ix_weather_obs_geom     ON weather_observations USING gist (geom)")

    create_initial_partitions("weather_observations")

    # weather_forecasts  — partitioned by valid_at (daily)
    op.execute("""
        CREATE TABLE weather_forecasts (
            grid_id             TEXT        NOT NULL,
            issued_at           TIMESTAMPTZ NOT NULL,
            valid_at            TIMESTAMPTZ NOT NULL,
            received_at         TIMESTAMPTZ NOT NULL,
            wind_speed_ms       FLOAT       CHECK (wind_speed_ms >= 0),
            wind_dir_deg        FLOAT       CHECK (wind_dir_deg BETWEEN 0 AND 360),
            temp_c              FLOAT,
            rh_pct              FLOAT       CHECK (rh_pct BETWEEN 0 AND 100),
            precip_prob_pct     FLOAT       CHECK (precip_prob_pct BETWEEN 0 AND 100),

            PRIMARY KEY (grid_id, issued_at, valid_at)
        ) PARTITION BY RANGE (valid_at)
    """)
    op.execute("CREATE INDEX ix_weather_fcst_valid_at ON weather_forecasts (valid_at DESC, issued_at DESC)")

    create_initial_partitions("weather_forecasts")

    # point_weather_map
    op.execute("""
        CREATE TABLE point_weather_map (
            forecast_point_id   TEXT        PRIMARY KEY REFERENCES forecast_points(id),
            station_id          TEXT        NOT NULL,
            station_dist_km     FLOAT       NOT NULL CHECK (station_dist_km > 0),
            grid_id             TEXT        NOT NULL,
            computed_at         TIMESTAMPTZ NOT NULL
        )
    """)

    # ── 3. Durable rollups ─────────────────────────────────────────────────

    # monitor_daily_pm25
    op.execute("""
        CREATE TABLE monitor_daily_pm25 (
            monitor_id      TEXT        NOT NULL REFERENCES monitors(id),
            local_date      DATE        NOT NULL,
            correction      TEXT        NOT NULL
                                CHECK (correction IN ('regulatory','purpleair_barkjohn')),
            mean_pm25       FLOAT       NOT NULL CHECK (mean_pm25 >= 0),
            max_pm25        FLOAT       CHECK (max_pm25 >= 0),
            hours_reported  INT         NOT NULL CHECK (hours_reported BETWEEN 0 AND 24),
            computed_at     TIMESTAMPTZ NOT NULL,

            PRIMARY KEY (monitor_id, local_date, correction)
        )
    """)
    op.execute("CREATE INDEX ix_monitor_daily_local_date ON monitor_daily_pm25 (local_date DESC)")
    op.execute("CREATE INDEX ix_monitor_daily_monitor    ON monitor_daily_pm25 (monitor_id, local_date DESC)")

    # city_monthly_aggregates
    op.execute("""
        CREATE TABLE city_monthly_aggregates (
            id                  TEXT        PRIMARY KEY,
            city_id             TEXT        NOT NULL REFERENCES cities(id),
            year_month          DATE        NOT NULL,
            source_scope        TEXT        NOT NULL
                                    CHECK (source_scope IN ('regulatory','all_corrected')),
            avg_pm25            FLOAT       CHECK (avg_pm25 >= 0),
            max_pm25            FLOAT       CHECK (max_pm25 >= 0),
            p95_pm25            FLOAT       CHECK (p95_pm25 >= 0),
            unhealthy_days      INT         CHECK (unhealthy_days >= 0),
            data_coverage_pct   FLOAT       CHECK (data_coverage_pct BETWEEN 0 AND 100),
            monitor_count       INT         CHECK (monitor_count > 0),
            aqi_table_version   TEXT        NOT NULL,
            computed_at         TIMESTAMPTZ NOT NULL,

            UNIQUE (city_id, year_month, source_scope)
        )
    """)
    op.execute("CREATE INDEX ix_city_monthly_city_month ON city_monthly_aggregates (city_id, year_month DESC)")

    # ── 4. Models and predictions ──────────────────────────────────────────

    # model_versions
    op.execute("""
        CREATE TABLE model_versions (
            model_key               TEXT        PRIMARY KEY,
            model_name              TEXT        NOT NULL,
            version                 TEXT        NOT NULL,
            algorithm               TEXT        NOT NULL,
            artifact_uri            TEXT        NOT NULL,
            artifact_sha256         TEXT        NOT NULL,
            hyperparameters         JSONB,
            feature_list            JSONB       NOT NULL,
            training_data_uri       TEXT,
            training_data_hash      TEXT,
            backtest_metrics        JSONB,
            status                  TEXT        NOT NULL
                                        CHECK (status IN ('shadow','production','retired')),
            notes                   TEXT,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            status_changed_at       TIMESTAMPTZ,

            UNIQUE (model_name, version)
        )
    """)
    # At most one production model per model_name
    op.execute("""
        CREATE UNIQUE INDEX one_production
            ON model_versions (model_name)
            WHERE status = 'production'
    """)

    # forecasts
    op.execute("""
        CREATE TABLE forecasts (
            id                      TEXT        PRIMARY KEY,
            forecast_point_id       TEXT        NOT NULL REFERENCES forecast_points(id),
            model_key               TEXT        NOT NULL REFERENCES model_versions(model_key),
            issued_at               TIMESTAMPTZ NOT NULL,
            horizon_hours           INT         NOT NULL CHECK (horizon_hours IN (1,3,6,12,24)),
            target_time             TIMESTAMPTZ NOT NULL,
            pm25_predicted          FLOAT       NOT NULL CHECK (pm25_predicted >= 0),
            pm25_lower              FLOAT       CHECK (pm25_lower >= 0),
            pm25_upper              FLOAT       CHECK (pm25_upper >= 0),
            nearest_monitor_dist_km FLOAT       CHECK (nearest_monitor_dist_km > 0),
            is_shadow               BOOLEAN     NOT NULL DEFAULT FALSE,
            is_experimental         BOOLEAN     NOT NULL DEFAULT TRUE
                                        CHECK (is_experimental),
            feature_snapshot        JSONB,

            -- target_time must equal issued_at + horizon; DB-enforced, not just documented
            CHECK (target_time = issued_at + make_interval(hours => horizon_hours)),

            UNIQUE (forecast_point_id, model_key, issued_at, horizon_hours)
        )
    """)
    op.execute("CREATE INDEX ix_forecasts_point_issued   ON forecasts (forecast_point_id, issued_at DESC)")
    op.execute("CREATE INDEX ix_forecasts_target_time    ON forecasts (target_time)")

    # forecast_verifications
    op.execute("""
        CREATE TABLE forecast_verifications (
            id                      TEXT        PRIMARY KEY,
            forecast_id             TEXT,       -- nullable: may be NULL after 30-day trim
            forecast_point_id       TEXT        NOT NULL,
            model_key               TEXT        NOT NULL,
            horizon_hours           INT         NOT NULL,
            issued_at               TIMESTAMPTZ NOT NULL,
            target_time             TIMESTAMPTZ NOT NULL,
            pm25_predicted          FLOAT       NOT NULL,
            pm25_observed           FLOAT       NOT NULL CHECK (pm25_observed >= 0),
            label_correction        TEXT        NOT NULL
                                        CHECK (label_correction IN
                                            ('regulatory','purpleair_barkjohn')),
            label_monitor_dist_km   FLOAT       NOT NULL,
            verified_at             TIMESTAMPTZ NOT NULL
        )
    """)
    op.execute("CREATE INDEX ix_fv_model_horizon    ON forecast_verifications (model_key, horizon_hours, target_time DESC)")
    op.execute("CREATE INDEX ix_fv_point_time       ON forecast_verifications (forecast_point_id, target_time DESC)")

    # alerts  — episode model
    op.execute("""
        CREATE TABLE alerts (
            id                      TEXT        PRIMARY KEY,
            forecast_point_id       TEXT        NOT NULL REFERENCES forecast_points(id),
            severity                TEXT        NOT NULL
                                        CHECK (severity IN (
                                            'moderate','unhealthy_sensitive',
                                            'unhealthy','very_unhealthy','hazardous')),
            status                  TEXT        NOT NULL DEFAULT 'open'
                                        CHECK (status IN ('open','resolved')),
            first_triggered_at      TIMESTAMPTZ NOT NULL,
            last_seen_at            TIMESTAMPTZ NOT NULL,
            resolved_at             TIMESTAMPTZ,
            pm25_threshold          FLOAT       NOT NULL,
            aqi_table_version       TEXT        NOT NULL,
            peak_pm25_predicted     FLOAT,
            peak_target_time        TIMESTAMPTZ,
            horizon_hours           INT,
            model_key               TEXT        NOT NULL,
            -- nullable FK: becomes NULL when forecasts row is trimmed at 30 days
            latest_forecast_id      TEXT        REFERENCES forecasts(id) ON DELETE SET NULL,
            is_experimental         BOOLEAN     NOT NULL DEFAULT TRUE
                                        CHECK (is_experimental)
        )
    """)
    op.execute("CREATE INDEX ix_alerts_point_triggered  ON alerts (forecast_point_id, first_triggered_at DESC)")
    op.execute("CREATE INDEX ix_alerts_latest_forecast  ON alerts (latest_forecast_id)")
    # Enforce at most one open alert per (point, severity)
    op.execute("""
        CREATE UNIQUE INDEX one_open_alert
            ON alerts (forecast_point_id, severity)
            WHERE status = 'open'
    """)

    # ── 5. Operations ──────────────────────────────────────────────────────

    # ingestion_runs
    op.execute("""
        CREATE TABLE ingestion_runs (
            id              TEXT        PRIMARY KEY,
            source          TEXT        NOT NULL
                                CHECK (source IN (
                                    'firms','nws_obs','nws_fcst','airdata','purpleair')),
            started_at      TIMESTAMPTZ NOT NULL,
            finished_at     TIMESTAMPTZ,
            status          TEXT        NOT NULL DEFAULT 'running'
                                CHECK (status IN ('running','success','partial','failed')),
            rows_fetched    INT         CHECK (rows_fetched >= 0),
            rows_written    INT         CHECK (rows_written >= 0),
            watermark       TIMESTAMPTZ,
            raw_path        TEXT,
            error           TEXT
        )
    """)
    op.execute("CREATE INDEX ix_ingestion_source_started  ON ingestion_runs (source, started_at DESC)")
    op.execute("CREATE INDEX ix_ingestion_status_started  ON ingestion_runs (status, started_at DESC)")

    # ── 6. Partition maintenance ───────────────────────────────────────────
    # Not scheduled here. The daily Celery maintenance task, after building
    # monitor_daily_pm25 and running forecast_verifications, must:
    #   1. SELECT create_daily_partitions('<table>', current_date, current_date + N)
    #      with N = days ahead from PARTITIONED_TABLES, so new days never land in DEFAULT
    #      (Postgres refuses to create a partition whose range already has rows
    #      in the DEFAULT partition).
    #   2. DROP TABLE <table>_pYYYYMMDD for days older than the retention window.


def downgrade() -> None:
    # Drop in reverse FK dependency order. CASCADE on a partitioned parent also
    # drops its daily and DEFAULT partitions.

    op.execute("DROP TABLE IF EXISTS ingestion_runs CASCADE")
    op.execute("DROP TABLE IF EXISTS alerts CASCADE")
    op.execute("DROP TABLE IF EXISTS forecast_verifications CASCADE")
    op.execute("DROP TABLE IF EXISTS forecasts CASCADE")
    op.execute("DROP TABLE IF EXISTS model_versions CASCADE")
    op.execute("DROP TABLE IF EXISTS city_monthly_aggregates CASCADE")
    op.execute("DROP TABLE IF EXISTS monitor_daily_pm25 CASCADE")
    op.execute("DROP TABLE IF EXISTS point_weather_map CASCADE")
    op.execute("DROP TABLE IF EXISTS weather_forecasts CASCADE")
    op.execute("DROP TABLE IF EXISTS weather_observations CASCADE")
    op.execute("DROP TABLE IF EXISTS fire_detections CASCADE")
    op.execute("DROP TABLE IF EXISTS observations CASCADE")
    op.execute("DROP TABLE IF EXISTS monitors CASCADE")
    op.execute("DROP TABLE IF EXISTS zip_codes CASCADE")
    op.execute("DROP TABLE IF EXISTS forecast_points CASCADE")
    op.execute("DROP TABLE IF EXISTS cities CASCADE")
    op.execute("DROP FUNCTION IF EXISTS create_daily_partitions(TEXT, DATE, DATE)")