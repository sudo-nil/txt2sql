"""Eval runner: execution-accuracy scorer for the text-to-SQL agent.

Usage:
    uv run python -m eval.run              # all tiers
    uv run python -m eval.run --tier traps # one tier only
"""

import sys
import time
from pathlib import Path

import yaml
from tabulate import tabulate

from app import bq, llm
from app.agent import run as agent_run

QUESTIONS_FILE = Path(__file__).parent / "questions.yaml"


def load_questions(tier_filter: str | None = None) -> list[dict]:
    with open(QUESTIONS_FILE) as f:
        questions = yaml.safe_load(f)
    if tier_filter:
        questions = [q for q in questions if q["tier"] == tier_filter]
    return questions


def _normalize_rows(rows: list[dict]) -> list[tuple]:
    """Sort rows deterministically; round floats to avoid BQ/Python precision drift."""
    normalized = []
    for row in rows:
        tup = tuple(
            round(v, 4) if isinstance(v, float) else v
            for _, v in sorted(row.items())
        )
        normalized.append(tup)
    return sorted(normalized, key=lambda r: [str(x) for x in r])


def _results_match(gold: list[dict], generated: list[dict]) -> bool:
    return _normalize_rows(gold) == _normalize_rows(generated)


def eval_one(q: dict, bq_client, llm_client) -> dict:
    result = {
        "id": q["id"],
        "tier": q["tier"],
        "question": q["question"],
        "passed": False,
        "gold_sql": q["gold_sql"].strip(),
        "gen_sql": None,
        "error": None,
        "gold_rows": None,
        "gen_rows": None,
    }
    try:
        gold_rows, _ = bq.execute(bq_client, q["gold_sql"].strip())
        result["gold_rows"] = gold_rows

        agent_result = agent_run(q["question"], bq_client, llm_client)
        result["gen_sql"] = agent_result["sql"]
        result["gen_rows"] = agent_result["rows"]

        result["passed"] = _results_match(gold_rows, agent_result["rows"])
    except Exception as e:
        result["error"] = str(e)
    return result


def _fmt_rows(rows: list[dict] | None, max_rows: int = 3) -> str:
    if rows is None:
        return "  (none)"
    if not rows:
        return "  (empty result)"
    preview = rows[:max_rows]
    lines = [f"  {r}" for r in preview]
    if len(rows) > max_rows:
        lines.append(f"  ... ({len(rows)} rows total)")
    return "\n".join(lines)


def print_scorecard(results: list[dict]) -> None:
    total = len(results)
    passed = sum(r["passed"] for r in results)

    tiers = ["filters", "grouping", "advanced", "traps"]
    tier_rows = []
    for tier in tiers:
        tier_results = [r for r in results if r["tier"] == tier]
        if not tier_results:
            continue
        n = len(tier_results)
        p = sum(r["passed"] for r in tier_results)
        tier_rows.append([tier, f"{p}/{n}", f"{p/n*100:.1f}%"])

    print("\n=== Eval Scorecard ===\n")
    print(f"Overall:  {passed}/{total}  ({passed/total*100:.1f}%)\n")
    print(tabulate(tier_rows, headers=["tier", "passed", "accuracy"], tablefmt="simple"))

    failures = [r for r in results if not r["passed"]]
    if not failures:
        print("\nAll questions passed.")
        return

    print(f"\n{'─'*60}")
    print(f"FAILURES ({len(failures)})")
    print(f"{'─'*60}")
    for r in failures:
        print(f"\n[{r['id']}] {r['tier']}: \"{r['question']}\"")
        if r["error"]:
            print(f"  ERROR: {r['error'][:200]}")
        else:
            print(f"  Generated SQL:\n    " + r["gen_sql"].replace("\n", "\n    "))
            print(f"  Gold result ({len(r['gold_rows'])} row(s)):")
            print(_fmt_rows(r["gold_rows"]))
            print(f"  Got ({len(r['gen_rows'])} row(s)):")
            print(_fmt_rows(r["gen_rows"]))


def main() -> None:
    tier_filter = None
    args = sys.argv[1:]
    if "--tier" in args:
        idx = args.index("--tier")
        tier_filter = args[idx + 1]

    questions = load_questions(tier_filter)
    if not questions:
        print(f"No questions found for tier: {tier_filter}")
        sys.exit(1)

    bq_client = bq.get_client()
    llm_client = llm.get_client()

    label = f"tier={tier_filter}" if tier_filter else "all tiers"
    print(f"Running {len(questions)} question(s) [{label}]...\n")

    results = []
    for i, q in enumerate(questions, 1):
        print(f"[{i}/{len(questions)}] {q['id']} ...", end=" ", flush=True)
        t0 = time.time()
        result = eval_one(q, bq_client, llm_client)
        elapsed = time.time() - t0
        status = "PASS" if result["passed"] else "FAIL"
        if result["error"]:
            status = "ERROR"
        print(f"{status}  ({elapsed:.1f}s)")
        results.append(result)

    print_scorecard(results)


if __name__ == "__main__":
    main()
