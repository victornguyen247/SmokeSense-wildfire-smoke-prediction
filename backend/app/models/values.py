"""Allowed values for TEXT + CHECK columns (docs/schema.md → Value lists).

Single source for the ORM CHECK constraints and for ingestion/validation code.
Changing a list here also needs a migration that updates the DB constraint.
"""

KINDS = ("city", "zip", "grid_cell", "adhoc")
MONITOR_SOURCES = ("airnow", "purpleair")
LOCATION_TYPES = ("outdoor", "indoor")

# PM2.5 correction. Only LABEL_CORRECTIONS (with qa_flag = 'ok') may be used
# as ML labels or for verification.
CORRECTIONS = ("regulatory", "purpleair_raw", "purpleair_barkjohn")
LABEL_CORRECTIONS = ("regulatory", "purpleair_barkjohn")
DATA_STATUSES = ("preliminary", "validated")

SATELLITES = ("MODIS_Terra", "MODIS_Aqua", "VIIRS_SNPP", "VIIRS_NOAA20", "VIIRS_NOAA21")
FIRMS_PRODUCTS = ("URT", "RT", "NRT", "SP")
CONFIDENCE_LEVELS = ("low", "nominal", "high")
DAYNIGHT = ("D", "N")

SOURCE_SCOPES = ("regulatory", "all_corrected")
MODEL_STATUSES = ("shadow", "production", "retired")
HORIZON_HOURS = (1, 3, 6, 12, 24)
SEVERITIES = ("moderate", "unhealthy_sensitive", "unhealthy", "very_unhealthy", "hazardous")
ALERT_STATUSES = ("open", "resolved")

INGESTION_SOURCES = ("firms", "nws_obs", "nws_fcst", "airdata", "purpleair")
INGESTION_STATUSES = ("running", "success", "partial", "failed")
