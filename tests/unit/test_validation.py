import pandas as pd
import pytest

from cloudspend.data_generation.generate_billing import generate
from cloudspend.validation.billing_checks import validate_billing, validate_budgets


@pytest.fixture()
def data():
    b, g = generate("dev", seed=42)
    return b.copy(), g.copy()


def test_clean_data_passes(data):
    b, g = data
    assert validate_billing(b).ok
    assert validate_budgets(g, b).ok


def test_missing_column_is_fatal(data):
    rep = validate_billing(data[0].drop(columns=["total_cost"]))
    assert not rep.ok and "missing columns" in rep.errors[0]


def test_duplicate_ids_detected(data):
    b = data[0]
    b.loc[1, "record_id"] = b.loc[0, "record_id"]
    rep = validate_billing(b)
    assert not rep.ok and rep.invalid_row_count == 2


def test_negative_cost_detected(data):
    b = data[0]
    b.loc[0, "total_cost"] = -1.0
    assert any("negative total_cost" in e for e in validate_billing(b).errors)


def test_cost_mismatch_detected(data):
    b = data[0]
    b.loc[0, "total_cost"] += 5
    assert any("usage_units*unit_cost" in e for e in validate_billing(b).errors)


def test_bad_date_and_category(data):
    b = data[0]
    b["usage_date"] = b["usage_date"].astype(object)
    b.loc[0, "usage_date"] = "not-a-date"
    b.loc[1, "department"] = "Nonexistent"
    errs = " ".join(validate_billing(b).errors)
    assert "unparseable usage_date" in errs and "unknown department" in errs


def test_date_range_bound(data):
    b = data[0]
    rep = validate_billing(b, start="2025-01-01", end="2025-01-31")
    assert any("outside expected range" in e for e in rep.errors)


def test_budget_grain_violation(data):
    g = data[1]
    g = pd.concat([g, g.iloc[[0]]], ignore_index=True)
    assert not validate_budgets(g).ok
