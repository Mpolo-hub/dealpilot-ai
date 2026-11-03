"""Hackathon demo judge access (spec 014).

Only active when DEALPILOT_DEMO_MODE=public. The access store is a separate SQLite file
(spec 014 AR-2); the analytics (DuckDB over Parquet) never open it, and this package never
opens DuckDB or the Parquet files.
"""
