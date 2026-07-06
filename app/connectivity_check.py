"""Phase 1 connectivity check: BigQuery + Vertex AI Gemini."""

import sys

from app import bq, llm

PROBE_SQL = f"""
SELECT COUNT(*) AS total
FROM `{bq.CFPB_TABLE}`
LIMIT 1
"""


def main() -> None:
    print("=== Phase 1: Connectivity Check ===\n")

    # BigQuery ping
    bq_client = bq.get_client()
    print(bq.ping(bq_client))

    # Dry-run against CFPB table
    estimated = bq.dry_run(bq_client, PROBE_SQL.strip())
    gb = estimated / 1024**3
    print(f"CFPB dry-run OK: ~{gb:.2f} GB estimated ({estimated:,} bytes)\n")

    # Vertex AI Gemini ping
    llm_client = llm.get_client()
    print(llm.ping(llm_client))

    print("\n=== All checks passed ===")


if __name__ == "__main__":
    main()
