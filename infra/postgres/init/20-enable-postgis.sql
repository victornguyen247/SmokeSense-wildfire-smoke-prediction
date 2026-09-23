-- Runs once, on a fresh data volume, after the postgis image's own init scripts.
-- The postgis/postgis image already enables the extension in POSTGRES_DB; this
-- makes it explicit and idempotent so the dev DB is never missing it.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;
