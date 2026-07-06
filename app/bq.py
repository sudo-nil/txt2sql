"""BigQuery client: connectivity check, dry-run, and query execution."""

import os
import re
from typing import Any

from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv()

CFPB_TABLE = "bigquery-public-data.cfpb_complaints.complaint_database"
MAX_BYTES_BILLED = 10 * 1024**3  # 10 GB hard cap


def get_client() -> bigquery.Client:
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    return bigquery.Client(project=project)


def ping(client: bigquery.Client) -> str:
    """Run SELECT 1 to verify connectivity."""
    row = next(iter(client.query("SELECT 1 AS ok").result()))
    return f"BigQuery ping OK: {dict(row)}"


def dry_run(client: bigquery.Client, sql: str) -> int:
    """Return estimated bytes billed; raise on syntax/schema errors."""
    job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
    job = client.query(sql, job_config=job_config)
    return job.total_bytes_processed


def execute(client: bigquery.Client, sql: str) -> tuple[list[dict[str, Any]], int]:
    """Run sql, return (rows, bytes_billed). Enforces SELECT-only and byte cap."""
    _assert_select_only(sql)
    job_config = bigquery.QueryJobConfig(
        maximum_bytes_billed=MAX_BYTES_BILLED,
    )
    job = client.query(sql, job_config=job_config)
    rows = [dict(row) for row in job.result()]
    return rows, job.total_bytes_processed


def inject_limit(sql: str, limit: int = 100) -> str:
    """Append LIMIT if no LIMIT clause is present anywhere in the SQL."""
    if re.search(r"\bLIMIT\b", sql, re.IGNORECASE):
        return sql
    return sql.rstrip().rstrip(";") + f"\nLIMIT {limit}"


def _assert_select_only(sql: str) -> None:
    first = sql.strip().split()[0].upper()
    if first != "SELECT":
        raise ValueError(f"Only SELECT statements are allowed; got: {first}")
