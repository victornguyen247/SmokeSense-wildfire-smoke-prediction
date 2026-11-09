"""OPS-04 hourly forecast pipeline: check ingest -> features -> predict -> interpolate.

See docs/ops/forecast-pipeline.md. Worker-side code like ingestion/: it may import
features/, serving/ and ml/inference, never the reverse.
"""
