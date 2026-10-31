"""SmokeSense data ingestion.

Every ingestion entry point -- the batch CLI, each connector's main(), the
validate_* scripts and the Celery tasks/worker -- imports this package
first, so HTTP client logging is quieted here once for all of them: httpx
would otherwise log request URLs that carry the AirNow and FIRMS keys.
"""

from app.core.logging import quiet_http_loggers

quiet_http_loggers()
