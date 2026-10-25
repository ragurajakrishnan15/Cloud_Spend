import re

import pytest

from cloudspend.ingestion.snowflake_client import SQL_DIR
from cloudspend.ingestion.transform import BUILD_SCRIPTS, CHECK_SCRIPT, render_sql


def test_render_substitutes_placeholders():
    out = render_sql("a '{{SOURCE_FILE}}' b '{{BUDGET_FILE}}'", "x.csv", "y.csv")
    assert out == "a 'x.csv' b 'y.csv'"


@pytest.mark.parametrize("bad", ["x'; DROP TABLE t;--", "a b.csv", "", "../x.csv"])
def test_render_rejects_unsafe_file_names(bad):
    with pytest.raises(ValueError):
        render_sql("{{SOURCE_FILE}}", bad, "ok.csv")


def test_all_scripts_exist_and_have_no_unrendered_placeholders():
    for name in (*BUILD_SCRIPTS, CHECK_SCRIPT):
        text = (SQL_DIR / name).read_text(encoding="utf-8")
        rendered = render_sql(text, "a.csv", "b.csv")
        assert not re.search(r"\{\{\w+\}\}", rendered), name
