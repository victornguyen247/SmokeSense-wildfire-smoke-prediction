"""Exercise real ORM queries against fixture tables, without the pipeline/PostGIS."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import JSON, Column, MetaData, Table, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.models.predictions import Alert, Forecast, ModelVersion
from app.services.alert_engine import evaluate

START = datetime(2026, 11, 20, tzinfo=UTC)
HORIZONS = (1, 3, 6, 12, 24)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    # Copy column shapes only: PostGIS and PostgreSQL constraints are not portable.
    for model in (Alert, Forecast, ModelVersion):
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
    from sqlalchemy import String

    points = Table("forecast_points", metadata, Column("id", String, primary_key=True))
    subs = Table(
        "alert_subscriptions",
        metadata,
        Column("forecast_point_id", String),
        Column("status", String),
    )
    metadata.create_all(engine)
    with Session(engine) as session:
        session.execute(points.insert(), [{"id": "p"}, {"id": "unused"}])
        session.execute(
            subs.insert(),
            [
                {"forecast_point_id": "p", "status": "active"},
                {"forecast_point_id": "p", "status": "active"},
                {"forecast_point_id": "unused", "status": "pending"},
            ],
        )
        session.add(
            ModelVersion(
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
        )
        session.flush()
        yield session
    engine.dispose()


def run(db, hour, values=None, *, point="p", shadow=False, horizons=HORIZONS):
    when = START + timedelta(hours=hour)
    for h in horizons:
        db.add(
            Forecast(
                id=f"{point}-{hour}-{h}-{shadow}",
                forecast_point_id=point,
                model_key="model/1",
                issued_at=when,
                horizon_hours=h,
                target_time=when + timedelta(hours=h),
                pm25_predicted=(values or {}).get(h, 10.0),
                source="idw",
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
    assert (alert.horizon_hours, alert.pm25_threshold) == (3, 30)
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
        3,
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


def test_shadow_and_unsubscribed_points_ignored(db):
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


def test_invalid_thresholds_fail_without_alerts(db):
    db.get(ModelVersion, "model/1").thresholds = {"1": 30}
    with pytest.raises(ValueError, match="thresholds"):
        run(db, 0, {1: 100})
    assert alerts(db) == []


def test_requires_utc_hour(db):
    with pytest.raises(ValueError, match="UTC"):
        evaluate(db, START.replace(tzinfo=None))
    with pytest.raises(ValueError, match="top"):
        evaluate(db, START + timedelta(minutes=1))
