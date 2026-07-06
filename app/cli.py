"""CLI entry point: python -m app.cli "question"."""

import sys

from tabulate import tabulate

from app import bq, llm
from app.agent import run


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m app.cli \"your question here\"")
        sys.exit(1)

    question = sys.argv[1]
    bq_client = bq.get_client()
    llm_model = llm.get_llm()

    print(f"\nQuestion: {question}\n")
    print("Generating SQL...")

    result = run(question, bq_client, llm_model)
    sql = result["sql"]
    rows = result["rows"]
    bytes_scanned = result["bytes_scanned"]
    attempts = result["attempts"]

    if attempts > 1:
        print(f"(self-repaired after {attempts} attempt(s))")

    print("\n--- SQL (citation) ---")
    print(sql)
    print("----------------------\n")

    if not rows:
        print("(no rows returned)")
    elif len(rows) == 1 and len(rows[0]) == 1:
        val = next(iter(rows[0].values()))
        key = next(iter(rows[0].keys()))
        print(f"{key}: {val:,}" if isinstance(val, int) else f"{key}: {val}")
    else:
        print(tabulate(rows, headers="keys", tablefmt="github"))

    print(f"\n[{bytes_scanned / 1024**2:.2f} MB scanned]")


if __name__ == "__main__":
    main()
