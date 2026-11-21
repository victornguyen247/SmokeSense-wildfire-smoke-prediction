"""Episode cases run on SQLite and, when configured, the migrated *_test PostGIS DB."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    MetaData,
    String,
    Table,
    create_engine,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.models.predictions import Alert, Forecast, ModelVersion
from app.models.operations import PipelineRun
from app.services.alert_engine import evaluate

START = datetime(2026, 11, 20, tzinfo=UTC)
HORIZONS = (1, 3, 6, 12, 24)


@pytest.fixture(params=["sqlite", "postgres"])
def db(request):
    if request.param == "postgres":
        factory = request.getfixturevalue("live_db")
        with factory() as session:
            session.execute(
                text("""
                INSERT INTO forecast_points (id, kind, label, geom, timezone, active)
                VALUES ('p', 'grid_cell', 'p', ST_Point(-121, 39, 4326)::geography, 'UTC', true),
                       ('unused', 'grid_cell', 'unused', ST_Point(-121, 39, 4326)::geography, 'UTC', false),
                       ('monitor', 'adhoc', 'other', ST_Point(-121, 39, 4326)::geography, 'UTC', true)
            """)
            )
            session.add(make_model())
            session.flush()
            yield session
        return
    engine = create_engine("sqlite://")
    metadata = MetaData()
    # Copy column shapes only: PostGIS and PostgreSQL constraints are not portable.
    for model in (Alert, Forecast, ModelVersion, PipelineRun):
        Table(
            model.__tablename__,
            metadata,
            *[
                Column(
                    c.name,
                    JSON() if isinstance(c.type, JSONB) else c.type,
                    primary_key=c.primary_key,
                    nullable=c.nullable,
                )
                for c in model.__table__.columns
            ],
        )
    points = Table(
        "forecast_points",
        metadata,
        Column("id", String, primary_key=True),
        Column("kind", String),
        Column("active", Boolean),
    )
    metadata.create_all(engine)
    with Session(engine) as session:
        session.execute(
            points.insert(),
            [
                {"id": "p", "kind": "grid_cell", "active": True},
                {"id": "unused", "kind": "grid_cell", "active": False},
                {"id": "monitor", "kind": "monitor", "active": True},
            ],
        )
        session.add(make_model())
        session.flush()
        yield session
    engine.dispose()


def make_model():
    return ModelVersion(
        model_key="model/1",
        model_name="model",
        version="1",
        algorithm="test",
        artifact_uri="unused",
        artifact_sha256="unused",
        feature_list=[],
        thresholds={str(h): 30.0 for h in HORIZONS},
        status="production",
        created_at=START,
    )


def run(
    db,
    hour,
    values=None,
    *,
    point="p",
    shadow=False,
    horizons=HORIZONS,
    source="idw",
    model="model/1",
):
    when = START + timedelta(hours=hour)
    if db.get(PipelineRun, str(hour)) is None:
        db.add(
            PipelineRun(
                id=str(hour),
                issued_at=when,
                started_at=when,
                finished_at=when,
                status="success",
                model_key="model/1",
                stages={},
            )
        )
    for h in horizons:
        db.add(
            Forecast(
                id=f"{point}-{hour}-{h}-{shadow}",
                forecast_point_id=point,
                model_key=model,
                issued_at=when,
                horizon_hours=h,
                target_time=when + timedelta(hours=h),
                pm25_predicted=(values or {}).get(h, 10.0),
                source=source,
                nearest_monitor_dist_km=30,
                is_shadow=shadow,
            )
        )
    db.flush()
    return evaluate(db, when)


def alerts(db):
    return db.scalars(select(Alert).order_by(Alert.first_triggered_at)).all()


def test_opens_earliest_threshold_and_full_run_peak(db):
    opened = run(db, 0, {3: 30, 12: 70})
    (alert,) = alerts(db)
    assert [(c.alert_id, c.forecast_point_id) for c in opened] == [(alert.id, "p")]
    assert (alert.horizon_hours, alert.pm25_threshold) == (12, 30)
    assert (alert.peak_pm25_predicted, alert.peak_target_time.hour) == (70, 12)
    assert alert.aqi_table_version == "epa-2024"
    assert alert.latest_forecast_id == "p-0-3-False"
    assert evaluate(db, START) == []
    assert len(alerts(db)) == 1


def test_updates_peak_but_preserves_trigger(db):
    run(db, 0, {3: 40})
    assert run(db, 1, {1: 80}) == []
    (alert,) = alerts(db)
    assert (alert.horizon_hours, alert.pm25_threshold, alert.model_key) == (
        1,
        30,
        "model/1",
    )
    assert alert.peak_pm25_predicted == 80
    assert alert.latest_forecast_id == "p-1-1-False"
    assert run(db, 2, {6: 35}) == []
    assert alert.peak_pm25_predicted == 80


def test_three_clean_runs_then_reopen(db):
    run(db, 0, {1: 40})
    for hour in (1, 2):
        assert run(db, hour) == []
        assert alerts(db)[0].status == "open"
    assert run(db, 3) == []
    (alert,) = alerts(db)
    assert alert.status == "resolved"
    assert alert.resolved_at.replace(tzinfo=UTC) == START + timedelta(hours=3)
    assert evaluate(db, START + timedelta(hours=3)) == []
    assert len(run(db, 4, {1: 40})) == 1
    assert len(alerts(db)) == 2


def test_flapping_six_hours_stays_one_episode(db):
    for hour in range(7):
        changes = run(db, hour, {1: 30} if hour % 2 == 0 else {})
        assert len(changes) == (1 if hour == 0 else 0)
    (alert,) = alerts(db)
    assert alert.status == "open"


def test_shadow_and_inactive_points_ignored(db):
    assert run(db, 0, {1: 100}, shadow=True) == []
    assert run(db, 1, {1: 100}, point="unused") == []
    assert alerts(db) == []


def test_threshold_change_used_without_code_change(db):
    assert run(db, 0, {24: 25}) == []
    model = db.get(ModelVersion, "model/1")
    model.thresholds = {str(h): 20.0 for h in HORIZONS}
    assert len(run(db, 1, {24: 25})) == 1
    assert alerts(db)[0].pm25_threshold == 20


def test_retired_model_forecasts_ignored(db):
    db.get(ModelVersion, "model/1").status = "retired"
    assert run(db, 0, {1: 100}) == []
    assert alerts(db) == []


def test_repeat_update_and_clean_run_are_idempotent(db):
    run(db, 0, {1: 40})
    run(db, 1, {3: 60})
    (alert,) = alerts(db)
    state = (alert.last_seen_at, alert.latest_forecast_id, alert.peak_pm25_predicted)
    assert evaluate(db, START + timedelta(hours=1)) == []
    assert (
        alert.last_seen_at,
        alert.latest_forecast_id,
        alert.peak_pm25_predicted,
    ) == state
    run(db, 2)
    assert evaluate(db, START + timedelta(hours=2)) == []
    assert alert.status == "open"
    assert (
        alert.last_seen_at,
        alert.latest_forecast_id,
        alert.peak_pm25_predicted,
    ) == state


def test_caller_can_roll_back_episode(db):
    db.commit()
    assert len(run(db, 0, {1: 40})) == 1
    db.rollback()
    assert alerts(db) == []


def test_missing_or_partial_run_does_not_resolve(db):
    run(db, 0, {1: 40})
    assert evaluate(db, START + timedelta(hours=3)) == []
    assert run(db, 3, horizons=(1,)) == []
    assert alerts(db)[0].status == "open"


def test_missing_horizons_skipped(db):
    db.get(ModelVersion, "model/1").thresholds = {"1": 30}
    assert len(run(db, 0, {1: 100})) == 1


def test_requires_utc_hour(db):
    with pytest.raises(ValueError, match="UTC"):
        evaluate(db, START.replace(tzinfo=None))
    with pytest.raises(ValueError, match="top"):
        evaluate(db, START + timedelta(minutes=1))


@pytest.mark.parametrize("thresholds", [None, {}, {"1": None}, {"1": -1}, {"1": True}])
def test_no_usable_thresholds_warn_once_and_leave_episode(db, caplog, thresholds):
    run(db, 0, {1: 40})
    db.get(ModelVersion, "model/1").thresholds = thresholds
    with caplog.at_level("WARNING", logger="app.services.alert_engine"):
        assert run(db, 25) == []
    assert len(caplog.records) == 1
    assert alerts(db)[0].status == "open"


def test_failed_hours_do_not_count_as_clear(db):
    run(db, 0, {1: 40})
    for hour in (1, 2):
        when = START + timedelta(hours=hour)
        db.add(
            PipelineRun(
                id=str(hour),
                issued_at=when,
                started_at=when,
                finished_at=when,
                status="failed",
                model_key="model/1",
                stages={},
            )
        )
    run(db, 3)
    assert alerts(db)[0].status == "open"
    run(db, 5)
    assert alerts(db)[0].status == "open"
    run(db, 8)
    assert alerts(db)[0].status == "resolved"


def test_missing_forecast_resolves_only_after_24_hours(db):
    run(db, 0, {1: 40})
    run(db, 24, horizons=())
    assert alerts(db)[0].status == "open"
    run(db, 25, horizons=())
    assert alerts(db)[0].status == "resolved"
    assert evaluate(db, START + timedelta(hours=25)) == []


def test_inactive_cell_with_open_episode_still_evaluated(db):
    run(db, 0, {1: 40})
    db.execute(text("UPDATE forecast_points SET active = false WHERE id = 'p'"))
    run(db, 1, {6: 90})
    (alert,) = alerts(db)
    assert (alert.peak_pm25_predicted, alert.horizon_hours) == (90, 6)


def test_non_grid_points_skipped(db):
    assert run(db, 0, {1: 100}, point="monitor") == []
    assert alerts(db) == []


def test_failed_current_cycle_no_op(db):
    when = START
    db.add(
        PipelineRun(
            id="0",
            issued_at=when,
            started_at=when,
            finished_at=when,
            status="failed",
            model_key="model/1",
            stages={},
        )
    )
    assert run(db, 0, {1: 100}) == []


def test_non_idw_forecasts_skipped(db):
    assert run(db, 0, {1: 100}, source="fallback") == []
    assert alerts(db) == []


def test_only_successful_cycles_model_used(db):
    other = make_model()
    other.model_key = "other/1"
    other.model_name = "other"
    db.add(other)
    assert run(db, 0, {1: 100}, model="other/1") == []
    assert alerts(db) == []


def test_reads_are_batched(db):
    from sqlalchemy import event

    # Insert first, then count just the evaluator's SELECT statements.
    run(db, 0, {1: 40})
    reads = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            reads.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        evaluate(db, START)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert len(reads) == 5


def test_postgres_open_index_and_point_lock(db):
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("PostgreSQL row-lock / partial-index test")
    from sqlalchemy.exc import IntegrityError, OperationalError

    # Commit setup, then leave the evaluator transaction open while another
    # connection tries to evaluate the same cycle.
    db.commit()
    run(db, 0, {1: 40})
    with Session(db.get_bind()) as other:
        other.execute(text("SET LOCAL lock_timeout = '100ms'"))
        with pytest.raises(OperationalError):
            other.execute(
                text("SELECT id FROM forecast_points WHERE id = 'p' FOR UPDATE")
            )
        other.rollback()
    db.commit()
    assert evaluate(db, START) == []
    (original,) = alerts(db)
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(
            Alert(
                id="duplicate",
                forecast_point_id="p",
                severity=original.severity,
                status="open",
                first_triggered_at=START,
                last_seen_at=START,
                pm25_threshold=30,
                aqi_table_version="epa-2024",
                model_key="model/1",
            )
        )
        db.flush()
    assert len(alerts(db)) == 1
