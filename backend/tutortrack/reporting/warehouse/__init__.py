"""Data warehouse export (E26-T09, FR-26-5; Enterprise).

Nightly, incremental exports of the reporting facts and dimensions (``datasets``) as
gzipped CSV with a JSON manifest of the documented schemas, to a destination the
organisation configures (``destinations``): TutorTrack's own object storage (download),
the organisation's S3 bucket, BigQuery or Snowflake. Each destination has a Temporal
Schedule that runs ``WarehouseExportWorkflow`` (``processes``).
"""
