import pandas as pd

from cloudspend.reporting.bi_export import EXTRACTS, export


def test_export_writes_every_extract_with_matching_totals(bundle, tmp_path):
    counts = export(bundle, tmp_path)
    assert set(counts) == set(EXTRACTS) | {"qbr_quarters.csv"}
    for name in counts:
        assert (tmp_path / name).exists()
    daily = pd.read_csv(tmp_path / "daily_spend.csv")
    assert round(daily["total_cost"].sum(), 2) == round(bundle.daily["total_cost"].sum(), 2)   # extract reconciles to source
    assert counts["daily_spend.csv"] == len(bundle.daily)
    assert daily["usage_date"].iloc[0] == "2025-01-01"                                         # ISO dates for BI tools


def test_export_handles_missing_model_outputs(bare_bundle, tmp_path):
    counts = export(bare_bundle, tmp_path)
    assert counts["cost_anomalies.csv"] == 0 and counts["daily_spend.csv"] > 0
