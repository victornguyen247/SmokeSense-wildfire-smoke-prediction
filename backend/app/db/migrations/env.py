"""Alembic environment.

Connects with the same URL the app uses (app.core.config.settings), so there
is no second copy of DB credentials in alembic.ini.
"""

from logging.config import fileConfig

from alembic import context
from geoalchemy2 import alembic_helpers
from sqlalchemy import engine_from_config, pool, text

from app.core.config import settings
from app.models import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Autogenerate compares the DB against these models (app/models/).
# Note: Alembic does not compare CHECK constraints or server defaults —
# changes to those must be written into the migration by hand.
target_metadata = Base.metadata

# Objects autogenerate must never try to create or drop:
# PostGIS's own table in public and the daily/DEFAULT partitions of
# partitioned tables (managed by create_daily_partitions() and the Celery job).
POSTGIS_TABLES = {"spatial_ref_sys"}
PARTITIONED_TABLES = ("observations", "fire_detections", "weather_observations", "weather_forecasts")


def include_object(obj, name, type_, reflected, compare_to):
    if type_ == "table" and name in POSTGIS_TABLES:
        return False
    if type_ == "table" and reflected and name.startswith(
        tuple(f"{t}_" for t in PARTITIONED_TABLES)
    ):
        return False
    return True


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it (`alembic upgrade head --sql`)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        include_object=include_object,
        render_item=alembic_helpers.render_item,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # The postgis/postgis image puts the tiger geocoder schema on the DB's
        # search_path; reflection follows search_path, so autogenerate would
        # see (and try to drop) tiger's tables. Our tables all live in public.
        connection.execute(text("SET search_path TO public"))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            # Renders geoalchemy2 Geography types correctly in new revisions
            render_item=alembic_helpers.render_item,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
