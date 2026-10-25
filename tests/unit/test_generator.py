import pandas as pd
import pytest

from cloudspend.data_generation.generate_billing import BILLING_COLUMNS, PROFILES, generate


@pytest.fixture(scope="module")
def dev():
    return generate("dev", seed=42)


def test_schema(dev):
    billing, budgets = dev
    assert list(billing.columns) == BILLING_COLUMNS
    assert list(budgets.columns) == ["budget_month", "department", "service_name", "budget_amount"]


def test_reproducible(dev):
    b2, g2 = generate("dev", seed=42)
    pd.testing.assert_frame_equal(dev[0], b2)
    pd.testing.assert_frame_equal(dev[1], g2)


def test_seed_changes_output(dev):
    other, _ = generate("dev", seed=7)
    assert not dev[0]["total_cost"].equals(other["total_cost"])


def test_row_count_and_unique_ids(dev):
    p = PROFILES["dev"]
    billing, _ = dev
    assert len(billing) == p.n_resources * p.days
    assert billing["record_id"].is_unique
    assert not billing.duplicated(["usage_date", "resource_id"]).any()


def test_nonnegative_costs_and_reconciliation(dev):
    billing, _ = dev
    assert (billing[["usage_units", "unit_cost", "total_cost"]] >= 0).all().all()
    diff = (billing["usage_units"] * billing["unit_cost"] - billing["total_cost"]).abs()
    assert diff.max() <= 0.01


def test_date_range(dev):
    p = PROFILES["dev"]
    d = pd.to_datetime(dev[0]["usage_date"])
    assert d.min() == pd.Timestamp(p.start)
    assert d.nunique() == p.days


def test_injected_anomaly_counts(dev):
    p = PROFILES["dev"]
    billing, _ = dev
    flagged = billing[billing["is_injected_anomaly"]]
    counts = flagged["anomaly_type"].value_counts()
    assert counts["spike"] == p.n_spikes
    assert counts["weekend_spend"] == p.n_weekend
    assert counts["drift"] == p.n_drifts * 7
    assert billing.loc[~billing["is_injected_anomaly"], "anomaly_type"].isna().all()


def test_no_anomalies_in_initial_history(dev):
    billing, _ = dev
    first60 = pd.to_datetime(billing["usage_date"]) < pd.Timestamp(PROFILES["dev"].start) + pd.Timedelta(days=60)
    assert not billing.loc[first60, "is_injected_anomaly"].any()


def test_budget_grain_unique_and_monthly(dev):
    _, budgets = dev
    assert not budgets.duplicated(["budget_month", "department", "service_name"]).any()
    assert (pd.to_datetime(budgets["budget_month"]).dt.day == 1).all()
