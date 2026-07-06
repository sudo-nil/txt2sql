"""Unit tests for guardrails and SQL extraction — no network required."""

import pytest

from app.bq import inject_limit, _assert_select_only
from app.agent import _extract_sql


# --- _assert_select_only ---

def test_select_passes():
    _assert_select_only("SELECT 1")  # should not raise


def test_select_multiline_passes():
    _assert_select_only("  SELECT\n  COUNT(*)\n  FROM t")


@pytest.mark.parametrize("bad_sql", [
    "INSERT INTO t VALUES (1)",
    "DELETE FROM t",
    "DROP TABLE t",
    "UPDATE t SET x = 1",
    "CREATE TABLE t (id INT)",
])
def test_dml_rejected(bad_sql):
    with pytest.raises(ValueError, match="Only SELECT"):
        _assert_select_only(bad_sql)


# --- inject_limit ---

def test_inject_limit_adds_when_absent():
    sql = "SELECT * FROM t"
    result = inject_limit(sql)
    assert result.endswith("LIMIT 100")


def test_inject_limit_skips_when_present():
    sql = "SELECT * FROM t LIMIT 50"
    assert inject_limit(sql) == sql


def test_inject_limit_skips_case_insensitive():
    sql = "SELECT * FROM t limit 10"
    assert inject_limit(sql) == sql


def test_inject_limit_strips_trailing_semicolon():
    sql = "SELECT * FROM t;"
    result = inject_limit(sql)
    assert ";" not in result
    assert result.endswith("LIMIT 100")


def test_inject_limit_custom_value():
    sql = "SELECT * FROM t"
    result = inject_limit(sql, limit=25)
    assert result.endswith("LIMIT 25")


# --- _extract_sql ---

def test_extract_plain_sql():
    assert _extract_sql("SELECT 1") == "SELECT 1"


def test_extract_strips_sql_fence():
    raw = "```sql\nSELECT 1\n```"
    assert _extract_sql(raw) == "SELECT 1"


def test_extract_strips_plain_fence():
    raw = "```\nSELECT 1\n```"
    assert _extract_sql(raw) == "SELECT 1"


def test_extract_skips_preamble():
    raw = "Here is the SQL:\nSELECT COUNT(*) FROM t"
    assert _extract_sql(raw) == "SELECT COUNT(*) FROM t"


def test_extract_multiline():
    raw = "Here you go:\nSELECT\n  COUNT(*)\nFROM t\nLIMIT 10"
    assert _extract_sql(raw) == "SELECT\n  COUNT(*)\nFROM t\nLIMIT 10"
