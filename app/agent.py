"""Agent: generate → dry-run validate → self-repair → execute loop."""

import re
from typing import Any

from app import bq, llm, schema


def run(
    question: str,
    bq_client,
    llm_client,
    schema_name: str = "cfpb_complaints",
    max_retries: int = 2,
) -> dict[str, Any]:
    """Full agent loop.

    Returns:
        sql: final SQL executed
        rows: result rows as list of dicts
        bytes_scanned: bytes billed by BigQuery
        attempts: number of generation attempts (1 = first try succeeded)
    """
    schema_data = schema.load(schema_name)
    sql = _generate_sql(question, llm_client, schema_data)
    sql = bq.inject_limit(sql)

    last_error: str | None = None
    for attempt in range(1, max_retries + 2):  # attempts: 1..max_retries+1
        try:
            bq.dry_run(bq_client, sql)
            break  # dry-run passed
        except Exception as e:
            last_error = str(e)
            if attempt > max_retries:
                raise RuntimeError(
                    f"SQL failed dry-run after {attempt} attempt(s).\n"
                    f"Last error: {last_error}\n"
                    f"Last SQL:\n{sql}"
                ) from e
            repair_prompt = _build_repair_prompt(question, sql, last_error, schema_data)
            sql = _generate_sql(question, llm_client, schema_data, prompt_override=repair_prompt)
            sql = bq.inject_limit(sql)
    else:
        attempt = max_retries + 1

    rows, bytes_scanned = bq.execute(bq_client, sql)
    return {
        "sql": sql,
        "rows": rows,
        "bytes_scanned": bytes_scanned,
        "attempts": attempt,
    }


def _generate_sql(
    question: str,
    llm_client,
    schema_data: dict,
    *,
    prompt_override: str | None = None,
) -> str:
    prompt = prompt_override or schema.build_prompt(question, schema_data)
    raw = llm.generate(llm_client, prompt)
    return _extract_sql(raw)


def _build_repair_prompt(
    question: str, bad_sql: str, error: str, schema_data: dict
) -> str:
    desc = schema.build_schema_description(schema_data)
    rules = schema.build_rules(schema_data)
    return f"""{desc}

{rules}

The following SQL was generated for the question below but failed a BigQuery dry-run.
Fix the SQL so it is valid. Return only the corrected SQL — no explanation.

Question: {question}

Broken SQL:
{bad_sql}

BigQuery error:
{error}

Corrected SQL:"""


def _extract_sql(text: str) -> str:
    """Strip markdown fences; return the bare SQL starting at SELECT."""
    fenced = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    match = re.search(r"(SELECT\b.*)", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text.strip()
