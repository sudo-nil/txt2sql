# txt2sql

A text-to-SQL agent that answers natural-language questions about U.S. consumer-finance complaints by generating and executing BigQuery SQL. Every answer includes the exact SQL used as a verifiable citation.

**Data source:** `bigquery-public-data.cfpb_complaints.complaint_database` — queried in place, never copied.

---

## Prerequisites

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/) (or plain pip + venv)
- A GCP project with these APIs enabled:
  - BigQuery API
  - Vertex AI API
- [Google Cloud SDK](https://cloud.google.com/sdk/docs/install) (`gcloud`) for ADC auth

---

## Setup

```bash
git clone <repo>
cd txt2sql

# Install dependencies
uv sync

# Copy the env template and fill in your project ID
cp .env.example .env
```

Edit `.env`:

```
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GOOGLE_CLOUD_LOCATION=us-central1        # or any region with Gemini access
GEMINI_MODEL=gemini-2.5-flash            # or gemini-2.5-pro for higher quality
```

### Authenticate with ADC

Both BigQuery and Vertex AI use the same Application Default Credentials — one login covers both:

```bash
gcloud auth application-default login
```

Verify connectivity (BigQuery + Gemini):

```bash
uv run python -m app.connectivity_check
```

Expected output:
```
BigQuery ping OK: {'ok': 1}
CFPB dry-run OK: ~X.XX GB estimated (N bytes)
Gemini ping OK: GEMINI OK

=== All checks passed ===
```

---

## Usage

```bash
uv run python -m app.cli "how many mortgage complaints were there in 2023?"
```

```
Question: how many mortgage complaints were there in 2023?

Generating SQL...

--- SQL (citation) ---
SELECT COUNT(*) AS complaint_count
FROM `bigquery-public-data.cfpb_complaints.complaint_database`
WHERE product = 'Mortgage'
  AND date_received BETWEEN '2023-01-01' AND '2023-12-31'
LIMIT 100
----------------------

complaint_count: 5,745

[186.40 MB scanned]
```

The SQL is always printed before the result so it can be independently verified.

---

## Evaluation

The eval harness measures **execution accuracy**: it runs both the gold SQL and the agent-generated SQL on BigQuery, then compares result sets (order-insensitive).

```bash
# Full suite (9 questions across 4 tiers)
uv run python -m eval.run

# One tier only
uv run python -m eval.run --tier traps
uv run python -m eval.run --tier filters
uv run python -m eval.run --tier grouping
uv run python -m eval.run --tier advanced
```

Sample scorecard:
```
Overall:  9/9  (100.0%)

tier      passed    accuracy
--------  --------  ----------
filters   2/2       100.0%
grouping  2/2       100.0%
advanced  2/2       100.0%
traps     3/3       100.0%
```

### Adding eval questions

Edit `eval/questions.yaml`. Each record:

```yaml
- id: my_question_1
  tier: filters          # filters | grouping | advanced | traps
  question: "..."
  gold_sql: |
    SELECT ...
    FROM `bigquery-public-data.cfpb_complaints.complaint_database`
    WHERE date_received <= '2024-12-31'   # pin to avoid live-table drift
```

---

## Project structure

```
schemas/
  cfpb_complaints.yaml   # table schema, domain rules, value hints, few-shot examples
app/
  bq.py                  # BigQuery client, dry-run, execute, guardrails
  llm.py                 # Vertex AI Gemini client (swappable LLM interface)
  schema.py              # YAML loader, prompt assembler
  agent.py               # generate → dry-run → self-repair → execute loop
  cli.py                 # python -m app.cli "question"
  connectivity_check.py  # Phase 1 smoke test
eval/
  questions.yaml         # gold Q&A pairs with tiers
  run.py                 # execution-accuracy scorer
tests/
  test_guardrails.py     # unit tests for SELECT-only guard, LIMIT injection, SQL extraction
```

### Adding a new dataset

Drop a new YAML in `schemas/` following the same structure as `cfpb_complaints.yaml`, then call:

```python
agent.run(question, bq_client, llm_client, schema_name="your_schema_name")
```

No Python changes required.

---

## Guardrails

| Guardrail | Where | Behaviour |
|---|---|---|
| SELECT-only | `bq.py` | Rejects any non-SELECT statement before execution |
| Byte cap | `bq.py` | Hard limit of 10 GB per query; BigQuery cancels overruns |
| LIMIT injection | `bq.py` | Appends `LIMIT 100` if no LIMIT clause is present |
| Dry-run before execute | `agent.py` | Every generated SQL is syntax/schema-checked at zero cost before running |
| Self-repair | `agent.py` | On dry-run failure, feeds the error back to the model; retries up to 2× |

---

## Failure modes

The CFPB dataset has three structural traps that cause naive text-to-SQL agents to silently return wrong answers. The agent handles all three via rules injected into every prompt.

### 1. Company name casing

**The trap:** Company names are stored as ALL-CAPS legal names — `"WELLS FARGO & COMPANY"`, `"EQUIFAX, INC."`. A model that generates `WHERE company_name = 'Wells Fargo'` returns zero rows with no error.

**How the agent handles it:** The schema rules mandate `UPPER(company_name) LIKE '%KEYWORD%'` for any plain-language company reference. The few-shot examples demonstrate this pattern explicitly.

**What still fails:** Ambiguous names with multiple legal entities (e.g. "Bank of America" maps to several distinct legal names). A `LIKE` match covers the common case but may over- or under-count for heavily-franchised companies.

---

### 2. Taxonomy drift (April 2017)

**The trap:** Product and issue labels changed in April 2017. "Credit reporting" became "Credit reporting, credit repair services, or other personal consumer reports". A query using the old exact label misses all post-2017 complaints; the new label misses pre-2017 ones.

**How the agent handles it:** The schema rules instruct the model to prefer `LIKE '%Credit reporting%'` over exact equality for generic product references. The `value_hints` section in `schemas/cfpb_complaints.yaml` lists both pre- and post-2017 labels so the model can construct OR conditions when needed.

**What still fails:** Issue-level taxonomy drift is not fully enumerated in the hints. Queries that filter on specific `issue` values may silently miss one era of data.

---

### 3. Narrative null guard

**The trap:** `consumer_complaint_narrative` is NULL for roughly 75% of rows — consumers must opt in to share their text. A query like `WHERE LOWER(consumer_complaint_narrative) LIKE '%fraud%'` silently excludes the ~75% of rows where the field is NULL, which is the correct behaviour, but a model that omits `IS NOT NULL` returns the same count by accident — masking the fact that it's only searching opted-in rows.

**How the agent handles it:** The schema rules explicitly require `consumer_complaint_narrative IS NOT NULL` in any query that filters or searches the narrative field. The column description in `schemas/cfpb_complaints.yaml` flags it as opt-in and mostly null.

**What still fails:** The model can't know what fraction of complaints *would* have mentioned a keyword if all consumers had opted in. Narrative-based counts are always a lower bound on true prevalence.
