"""DATA-06 live ingestion: a rolling ~72 h window of California data.

One job per source (firms, airnow, nws, purpleair), each runnable standalone:

    python -m ingestion.live <source>

or as a Celery task scheduled by beat (ingestion/tasks.py). Jobs reuse the batch
connectors' normalizers, so a live row is built exactly like a historical one, and
mark every row they write with their ingestion_runs id (migration 0006). Retention
deletes only marked rows. See backend/docs/live-ingestion.md.
"""
