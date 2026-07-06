import re
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app import bq, schema
from app import llm as llm_module

MAX_RETRIES = 2


class AgentState(TypedDict):
    question: str
    schema_data: dict
    sql: str | None
    dry_run_error: str | None
    attempts: int
    rows: list[dict] | None
    bytes_scanned: int | None


def run(
    question: str,
    bq_client,
    llm_model,
    schema_name: str = "cfpb_complaints",
    max_retries: int = MAX_RETRIES,
) -> dict[str, Any]:
    """Run the agent graph and return {sql, rows, bytes_scanned, attempts}."""
    schema_data = schema.load(schema_name)
    graph = _build_graph(bq_client, llm_model, max_retries)
    final = graph.invoke({
        "question": question,
        "schema_data": schema_data,
        "sql": None,
        "dry_run_error": None,
        "attempts": 0,
        "rows": None,
        "bytes_scanned": None,
    })
    if final["dry_run_error"] and final["rows"] is None:
        raise RuntimeError(
            f"SQL failed validation after {final['attempts']} attempt(s).\n"
            f"Last error: {final['dry_run_error']}\n"
            f"Last SQL:\n{final['sql']}"
        )
    return {
        "sql": final["sql"],
        "rows": final["rows"],
        "bytes_scanned": final["bytes_scanned"],
        "attempts": final["attempts"],
    }


# ── Graph construction ────────────────────────────────────────────────────────

def _build_graph(bq_client, llm_model, max_retries: int):
    builder = StateGraph(AgentState)

    builder.add_node("generate", _make_generate_node(llm_model))
    builder.add_node("validate", _make_validate_node(bq_client))
    builder.add_node("repair",   _make_repair_node(llm_model))
    builder.add_node("execute",  _make_execute_node(bq_client))

    builder.set_entry_point("generate")
    builder.add_edge("generate", "validate")
    builder.add_conditional_edges(
        "validate",
        lambda state: _route_after_validate(state, max_retries),
    )
    builder.add_edge("repair", "validate")
    builder.add_edge("execute", END)

    return builder.compile()


def _route_after_validate(state: AgentState, max_retries: int) -> str:
    if state["dry_run_error"] is None:
        return "execute"
    if state["attempts"] > max_retries:
        return END
    return "repair"


# ── Node factories ────────────────────────────────────────────────────────────

def _make_generate_node(llm_model):
    def generate(state: AgentState) -> dict:
        prompt = schema.build_prompt(state["question"], state["schema_data"])
        sql = bq.inject_limit(_extract_sql(llm_module.generate(llm_model, prompt)))
        return {"sql": sql, "attempts": state["attempts"] + 1}
    return generate


def _make_validate_node(bq_client):
    def validate(state: AgentState) -> dict:
        try:
            bq.dry_run(bq_client, state["sql"])
            return {"dry_run_error": None}
        except Exception as e:
            return {"dry_run_error": str(e)}
    return validate


def _make_repair_node(llm_model):
    def repair(state: AgentState) -> dict:
        prompt = _build_repair_prompt(
            state["question"], state["sql"], state["dry_run_error"], state["schema_data"]
        )
        sql = bq.inject_limit(_extract_sql(llm_module.generate(llm_model, prompt)))
        return {"sql": sql, "attempts": state["attempts"] + 1}
    return repair


def _make_execute_node(bq_client):
    def execute(state: AgentState) -> dict:
        rows, bytes_scanned = bq.execute(bq_client, state["sql"])
        return {"rows": rows, "bytes_scanned": bytes_scanned}
    return execute


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_sql(text: str) -> str:
    """Strip markdown fences; return the bare SQL starting at SELECT."""
    fenced = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    match = re.search(r"(SELECT\b.*)", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text.strip()


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
