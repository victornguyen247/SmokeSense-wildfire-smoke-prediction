"""OPS-04 hourly forecast pipeline: stub stages end to end, idempotent re-runs,
failure handling and the /meta staleness fields. Needs the *_test database."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

from ingestion.live.common import floor_hour, utc_now
from pipeline import runner, settings
from pipeline.stages import STAGE_ORDER, StageError, resolve
from pipeline.status import forecast_status

HOUR = floor_hour(utc_now())


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("PIPELINE_WORK_DIR", str(tmp_path / "work"))
    for name in ("PIPELINE_FEATURES_STAGE", "PIPELINE_PREDICT_STAGE", "PIPELINE_INTERPOLATE_STAGE",
                 "PIPELINE_STALE_AFTER_MINUTES"):
        monkeypatch.delenv(name, raising=False)


def seed(s, *, ingest_fresh=True):
    """One monitor with a reading, plus a grid cell ~10 km away."""
    s.execute(text("""
        INSERT INTO monitors (id, source, external_id, aqs_code, location_type, geom, active, first_seen_at)
        VALUES ('m1', 'airnow', 'e1', '060010001', 'outdoor', 'SRID=4326;POINT(-122.0 37.0)', true, :t)
    """), {"t": HOUR})
    s.execute(text("""
        INSERT INTO forecast_points (id, kind, label, geom, timezone, monitor_id)
        VALUES ('fp-m1', 'monitor', 'M1', 'SRID=4326;POINT(-122.0 37.0)', 'America/Los_Angeles', 'm1')
    """))
    s.execute(text("""
        INSERT INTO forecast_points (id, kind, label, geom, timezone)
        VALUES ('fp-g1', 'grid_cell', 'G1', 'SRID=4326;POINT(-122.1 37.0)', 'America/Los_Angeles')
    """))
    s.execute(text("""
        INSERT INTO observations (monitor_id, valid_at, received_at, pm25, correction)
        VALUES ('m1', :v, :t, 40.0, 'regulatory')
    """), {"v": HOUR - timedelta(hours=2), "t": HOUR})
    if ingest_fresh:
        s.execute(text("""
            INSERT INTO ingestion_runs (id, source, started_at, finished_at, status)
            VALUES ('i1', 'airdata', :t, :t, 'success'), ('i2', 'nws_obs', :t, :t, 'success')
        """), {"t": utc_now()})
    s.commit()


def forecasts(s):
    return s.execute(text(
        "SELECT forecast_point_id, horizon_hours, pm25_predicted, source, model_key FROM forecasts "
        "ORDER BY forecast_point_id, horizon_hours")).all()


def test_stub_run_writes_monitor_and_grid_forecasts(live_db):
    with live_db() as s:
        seed(s)
    result = runner.run_all(live_db, HOUR)

    assert result["status"] == "success", result
    assert set(result["stages"]) == set(STAGE_ORDER)  # JSONB does not keep key order
    with live_db() as s:
        rows = forecasts(s)
        run = s.execute(text("SELECT status, model_key, finished_at, stages FROM pipeline_runs")).one()
    assert [(r[0], r[1], r[2], r[3]) for r in rows if r[0] == "fp-m1"] == [
        ("fp-m1", h, 40.0, "persistence") for h in (1, 3, 6, 12, 24)]
    assert {r[3] for r in rows if r[0] == "fp-g1"} == {"idw"}
    assert len(rows) == 10
    assert run.status == "success" and run.model_key == settings.STUB_MODEL_KEY and run.finished_at
    assert run.stages["predict"]["rows_out"] == 5 and run.stages["interpolate"]["rows_out"] == 5
    assert run.stages["features"]["rows_out"] == 1


def test_rerunning_the_same_hour_overwrites(live_db):
    with live_db() as s:
        seed(s)
    runner.run_all(live_db, HOUR)
    with live_db() as s:
        s.execute(text("UPDATE observations SET pm25 = 55.0"))
        s.commit()
    runner.run_all(live_db, HOUR + timedelta(minutes=30))  # same hour

    with live_db() as s:
        rows = forecasts(s)
        n_runs = s.execute(text("SELECT count(*) FROM pipeline_runs WHERE status = 'success'")).scalar()
    assert len(rows) == 10 and {r[2] for r in rows} == {55.0}
    assert n_runs == 2  # the audit log keeps both runs; the forecasts are not duplicated


def test_success_trims_old_grid_rows_and_month_old_monitor_rows(live_db):
    with live_db() as s:
        seed(s)
    runner.run_all(live_db, HOUR - timedelta(hours=1))
    with live_db() as s:  # a monitor row from 31 days ago, which retention must drop
        s.execute(text("""
            INSERT INTO forecasts (id, forecast_point_id, model_key, issued_at, horizon_hours,
                target_time, pm25_predicted, source, nearest_monitor_dist_km)
            VALUES ('old', 'fp-m1', :k, :t, 1, :t + interval '1 hour', 1, 'persistence', 0)
        """), {"k": settings.STUB_MODEL_KEY, "t": HOUR - timedelta(days=31)})
        s.commit()

    runner.run_all(live_db, HOUR)

    with live_db() as s:
        grid = s.execute(text(
            "SELECT DISTINCT issued_at FROM forecasts WHERE forecast_point_id = 'fp-g1'")).scalars().all()
        monitor = s.execute(text(
            "SELECT count(*), count(DISTINCT issued_at) FROM forecasts WHERE forecast_point_id = 'fp-m1'")).one()
    assert grid == [HOUR]  # only the newest run's grid rows
    assert tuple(monitor) == (10, 2)  # both runs kept, the 31-day-old row gone


def test_failed_run_trims_nothing(live_db):
    with live_db() as s:
        seed(s)
    runner.run_all(live_db, HOUR - timedelta(hours=1))
    with live_db() as s:
        s.execute(text("DELETE FROM ingestion_runs"))
        s.commit()
    assert runner.run_all(live_db, HOUR)["status"] == "failed"
    with live_db() as s:
        assert len(forecasts(s)) == 10


def test_stale_nws_only_warns_and_missing_lag_does_not_block(live_db, caplog):
    with live_db() as s:
        seed(s)
        s.execute(text("UPDATE ingestion_runs SET finished_at = finished_at - interval '10 hours' "
                       "WHERE source = 'nws_obs'"))
        s.execute(text("DELETE FROM observations"))
        s.execute(text("INSERT INTO observations (monitor_id, valid_at, received_at, pm25, correction) "
                       "VALUES ('m1', :v, :v, 40.0, 'regulatory')"), {"v": HOUR - timedelta(hours=3)})
        s.commit()
    with caplog.at_level("WARNING", logger="pipeline"):
        result = runner.run_all(live_db, HOUR)
    assert result["status"] == "success", result
    text_ = " ".join(r.message for r in caplog.records)
    assert "NWS observations are stale" in text_ and "no AirNow reading" in text_


def test_abandoned_runs_are_closed_by_the_next_start(live_db, caplog):
    with live_db() as s:
        s.execute(text("INSERT INTO pipeline_runs (id, issued_at, started_at, status) "
                       "VALUES ('old', :t, :t, 'running'), ('new', :n, :n, 'running')"),
                  {"t": HOUR - timedelta(hours=2), "n": utc_now() - timedelta(minutes=2)})
        s.commit()
    with caplog.at_level("ERROR", logger="pipeline"):
        runner.start_run(live_db, HOUR)
    with live_db() as s:
        rows = dict(s.execute(text("SELECT id, status FROM pipeline_runs WHERE id IN ('old','new')")).all())
    assert rows == {"old": "failed", "new": "running"}  # only the long-dead one
    assert any("abandoned" in r.message for r in caplog.records)


def test_celery_chain_marks_a_failed_run_failed(live_db, monkeypatch):
    """The real chain + link_error (run eagerly): a failing stage ends in pipeline.fail."""
    import pipeline.tasks as tasks
    from ingestion.tasks import celery_app

    with live_db() as s:
        seed(s, ingest_fresh=False)  # check_ingest will fail
    monkeypatch.setattr(tasks, "SessionLocal", live_db)
    monkeypatch.setattr(celery_app.conf, "task_always_eager", True)
    monkeypatch.setattr(celery_app.conf, "task_eager_propagates", False)
    for t in tasks.STAGE_TASKS.values():
        monkeypatch.setattr(t, "max_retries", 0)

    tasks.hourly.apply(args=[HOUR.isoformat()])

    with live_db() as s:
        row = s.execute(text("SELECT status, error FROM pipeline_runs")).one()
    assert row.status == "failed" and row.error.startswith("check_ingest: ")


def test_stale_ingest_fails_the_run_and_keeps_the_last_good_forecast(live_db):
    with live_db() as s:
        seed(s)
    assert runner.run_all(live_db, HOUR - timedelta(hours=1))["status"] == "success"
    with live_db() as s:
        s.execute(text("UPDATE ingestion_runs SET finished_at = finished_at - interval '10 hours'"))
        s.commit()

    result = runner.run_all(live_db, HOUR)

    assert result["status"] == "failed"
    assert result["error"].startswith("check_ingest: ") and "airnow" in result["error"]
    assert result["stages"]["check_ingest"]["status"] == "failed"
    assert "features" not in result["stages"]
    with live_db() as s:
        assert len(forecasts(s)) == 10  # nothing deleted
        status = forecast_status(s, now=HOUR + timedelta(minutes=40))
    assert status["latest_issued_at"] == (HOUR - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_failed_stage_is_logged_at_error(live_db, caplog):
    with live_db() as s:
        seed(s, ingest_fresh=False)
    with caplog.at_level("ERROR", logger="pipeline"):
        runner.run_all(live_db, HOUR)
    assert any("FAILED at check_ingest" in r.message for r in caplog.records)


def test_a_failed_stage_can_be_retried_alone(live_db):
    with live_db() as s:
        seed(s)
    run_id = runner.start_run(live_db, HOUR)
    for stage in ("check_ingest", "features"):
        runner.run_stage(live_db, run_id, stage)
    with live_db() as s:  # predict fails once (as a flaky stage would) ...
        s.execute(text("ALTER TABLE forecasts RENAME TO forecasts_x"))
        s.commit()
    with pytest.raises(Exception):
        runner.run_stage(live_db, run_id, "predict")
    with live_db() as s:
        s.execute(text("ALTER TABLE forecasts_x RENAME TO forecasts"))
        s.commit()
    # ... and its retry, without re-running the stages before it, finishes the run.
    runner.run_stage(live_db, run_id, "predict", attempt=1)
    runner.run_stage(live_db, run_id, "interpolate")
    runner.finish_run(live_db, run_id)
    with live_db() as s:
        stages = s.execute(text("SELECT stages FROM pipeline_runs")).scalar()
        assert len(forecasts(s)) == 10
    assert stages["predict"]["attempts"] == 2 and stages["features"]["attempts"] == 1


def test_forecast_status(live_db, monkeypatch):
    with live_db() as s:
        none = forecast_status(s, now=HOUR)
        assert none["forecast_stale"] is True and none["latest_issued_at"] is None
        s.execute(text("""
            INSERT INTO pipeline_runs (id, issued_at, started_at, finished_at, status, model_key)
            VALUES ('a', :t, :t, :t, 'success', 'm/v1'), ('b', :t2, :t2, :t2, 'failed', 'm/v2')
        """), {"t": HOUR, "t2": HOUR + timedelta(hours=1)})
        s.commit()
        fresh = forecast_status(s, now=HOUR + timedelta(minutes=100))
        old = forecast_status(s, now=HOUR + timedelta(minutes=151))
        monkeypatch.setenv("PIPELINE_STALE_AFTER_MINUTES", "30")
        tight = forecast_status(s, now=HOUR + timedelta(minutes=31))
    assert fresh == {"model_key": "m/v1", "latest_issued_at": HOUR.strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "forecast_age_minutes": 100, "forecast_stale_after_minutes": 150,
                     "forecast_stale": False}  # the later failed run does not count
    assert old["forecast_stale"] is True and tight["forecast_stale"] is True
    assert tight["forecast_stale_after_minutes"] == 30


def test_stage_choice_is_config(monkeypatch):
    assert resolve("features").__name__ == "features_stub"
    monkeypatch.setenv("PIPELINE_FEATURES_STAGE", "real")
    assert resolve("features").__name__ == "features_real"
    monkeypatch.setenv("PIPELINE_PREDICT_STAGE", "pipeline.stages:predict_stub")
    assert resolve("predict").__name__ == "predict_stub"
    monkeypatch.setenv("PIPELINE_PREDICT_STAGE", "nope")
    with pytest.raises(StageError, match="unknown implementation"):
        resolve("predict")


def test_celery_wiring():
    from ingestion.tasks import celery_app
    import pipeline.tasks  # noqa: F401  (a worker imports it through `include`)

    entry = celery_app.conf.beat_schedule["pipeline-hourly"]
    assert entry["task"] == "pipeline.hourly"
    assert "live-airnow" in celery_app.conf.beat_schedule  # ingestion schedule intact
    for stage in STAGE_ORDER:
        task = celery_app.tasks[f"pipeline.stage.{stage}"]
        assert task.max_retries == settings.max_retries()
    assert {"pipeline.hourly", "pipeline.finish", "pipeline.fail"} <= set(celery_app.tasks)


def test_real_predict_writes_the_models_forecasts(live_db, monkeypatch):
    """predict=real hands the features to the registry's InferenceService and upserts its rows."""
    import pandas as pd
    from pipeline import stages

    with live_db() as s:
        seed(s)
        s.execute(text("""
            INSERT INTO model_versions (model_key, model_name, version, algorithm, artifact_uri,
                artifact_sha256, feature_list, status)
            VALUES ('baseline/v2', 'baseline', 'v2', 'xgboost', 'file://x', 'x', '[]'::jsonb, 'production')
        """))
        s.commit()
    seen = {}

    class FakeService:
        def predict(self, features):
            seen["columns"] = list(features.columns)
            rows = [features.assign(horizon_hours=h) for h in (1, 3, 6, 12, 24)]
            out = pd.concat(rows, ignore_index=True)
            out["pm25_predicted"] = out["pm25_lag_1h"] * 2
            out["target_time"] = out["issued_at"] + pd.to_timedelta(out["horizon_hours"], unit="h")
            out["source"], out["model_key"] = "v2", "baseline/v2"
            return out[["forecast_point_id", "horizon_hours", "pm25_predicted", "source",
                        "model_key", "issued_at", "target_time"]]

    monkeypatch.setattr(stages, "load_service", FakeService)
    monkeypatch.setenv("PIPELINE_PREDICT_STAGE", "real")

    result = runner.run_all(live_db, HOUR)

    assert result["status"] == "success", result
    assert seen["columns"] == ["forecast_point_id", "issued_at", "pm25_lag_1h"]
    with live_db() as s:
        rows = forecasts(s)
        model_key = s.execute(text("SELECT model_key FROM pipeline_runs")).scalar()
    assert [(r[2], r[3], r[4]) for r in rows if r[0] == "fp-m1"] == [(80.0, "v2", "baseline/v2")] * 5
    assert {r[3] for r in rows if r[0] == "fp-g1"} == {"idw"} and model_key == "baseline/v2"
