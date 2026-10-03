"""Small persistence helpers for the ingestion connectors (DATA-02/03)."""

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.models import FireDetection, Monitor, Observation, WeatherObservation


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


def point_wkt(latitude: float, longitude: float) -> str:
    """Return a PostGIS-compatible WKT point."""
    return f"SRID=4326;POINT({longitude} {latitude})"


def insert_fire_detections(
    session: Session,
    rows: list[dict],
) -> int:
    """Insert FIRMS detections, skipping records already in the database."""

    written = 0

    for row in rows:
        existing = session.scalar(
            select(FireDetection).where(
                FireDetection.satellite == row["satellite"],
                FireDetection.external_id == row["external_id"],
                FireDetection.detected_at == row["detected_at"],
            )
        )

        if existing:
            continue

        detection = FireDetection(
            external_id=row["external_id"],
            satellite=row["satellite"],
            product=row["product"],
            geom=point_wkt(row["latitude"], row["longitude"]),
            detected_at=row["detected_at"],
            received_at=row["received_at"],
            confidence_raw=row["confidence_raw"],
            confidence_level=row["confidence_level"],
            frp_mw=row["frp_mw"],
            bright_t31_k=row["bright_t31_k"],
            scan_km=row["scan_km"],
            track_km=row["track_km"],
            daynight=row["daynight"],
        )

        session.add(detection)
        written += 1

    return written


def get_or_create_monitor(
    session: Session,
    monitor_data: dict,
) -> Monitor:
    """Find an AirNow monitor or create it if it does not exist."""

    monitor = session.scalar(
        select(Monitor).where(
            Monitor.source == monitor_data["source"],
            Monitor.external_id == monitor_data["external_id"],
        )
    )

    if monitor:
        return monitor

    monitor = Monitor(
        source=monitor_data["source"],
        external_id=monitor_data["external_id"],
        name=monitor_data["name"],
        geom=point_wkt(
            monitor_data["latitude"],
            monitor_data["longitude"],
        ),
        elevation_m=monitor_data["elevation_m"],
        active=monitor_data["active"],
        first_seen_at=monitor_data["first_seen_at"],
        last_seen_at=monitor_data["last_seen_at"],
    )

    session.add(monitor)
    session.flush()

    return monitor


def insert_airnow_observations(
    session: Session,
    rows: list[dict],
) -> int:
    """Insert AirNow monitors and observations idempotently.

    PurpleAir records use the same monitor/observation shape, so the
    PurpleAir connector's output goes through here too.
    """

    written = 0

    for row in rows:
        monitor = get_or_create_monitor(
            session,
            row["monitor"],
        )

        observation_data = row["observation"]

        existing = session.scalar(
            select(Observation).where(
                Observation.monitor_id == monitor.id,
                Observation.valid_at == observation_data["valid_at"],
            )
        )

        if existing:
            continue

        observation = Observation(
            monitor_id=monitor.id,
            valid_at=observation_data["valid_at"],
            received_at=observation_data["received_at"],
            pm25=observation_data["pm25"],
            correction=observation_data["correction"],
            pm25_cf1_a=observation_data["pm25_cf1_a"],
            pm25_cf1_b=observation_data["pm25_cf1_b"],
            rh_pct=observation_data["rh_pct"],
            qa_flag=observation_data["qa_flag"],
            data_status=observation_data["data_status"],
        )

        session.add(observation)
        written += 1

    return written


def insert_weather_observations(
    session: Session,
    rows: list[dict],
) -> int:
    """Insert NCEI weather observations, skipping rows already stored."""

    written = 0

    for row in rows:
        existing = session.scalar(
            select(WeatherObservation).where(
                WeatherObservation.station_id == row["station_id"],
                WeatherObservation.valid_at == row["valid_at"],
            )
        )

        if existing:
            continue

        observation = WeatherObservation(
            station_id=row["station_id"],
            valid_at=row["valid_at"],
            received_at=row["received_at"],
            geom=point_wkt(row["latitude"], row["longitude"]),
            wind_speed_ms=row["wind_speed_ms"],
            wind_dir_deg=row["wind_dir_deg"],
            temp_c=row["temp_c"],
            rh_pct=row["rh_pct"],
            pressure_hpa=row["pressure_hpa"],
            precip_1h_mm=row["precip_1h_mm"],
            qc_flag=row["qc_flag"],
        )

        session.add(observation)
        written += 1

    return written
