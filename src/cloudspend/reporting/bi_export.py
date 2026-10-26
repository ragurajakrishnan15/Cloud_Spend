"""Export the REPORTING data as flat CSV extracts for BI tools that cannot (or should not) connect to Snowflake directly,
e.g. Tableau Public, or a quick Tableau / Looker Studio prototype. Same data, grain and column names the dashboard uses.

    python -m cloudspend.reporting.bi_export [--out-dir data/generated/bi_extracts]

Reads through `cloudspend.data_access`, so it uses Snowflake REPORTING views when configured and the local CSV mode otherwise.
All data is synthetic.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from cloudspend.ai.tools import DataBundle, quarter_table
from config.settings import GENERATED_DIR

DEFAULT_OUT = GENERATED_DIR / "bi_extracts"

# extract file -> (DataBundle attribute | None, grain)
EXTRACTS = {
    "daily_spend.csv": ("daily", "day x department x service x environment x region"),
    "budget_variance.csv": ("budget_variance", "month x department x service (budgets exist only at this grain)"),
    "cost_anomalies.csv": ("anomalies", "flagged record x detection method"),
    "cost_forecast.csv": ("forecast", "forecast date x model x scope"),
    "optimization_recommendations.csv": ("recommendations", "recommendation"),
    "model_evaluation.csv": ("evaluation", "run x model x scope x metric"),
}


def export(bundle: DataBundle, out_dir: Path = DEFAULT_OUT) -> dict[str, int]:
    """Write one CSV per extract (plus qbr_quarters.csv); returns {file: row_count}. Empty model outputs are still written
    (header only when the columns are known) so a BI workbook can be built before models have run."""
    out_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    frames: dict[str, pd.DataFrame] = {name: getattr(bundle, attr) for name, (attr, _) in EXTRACTS.items()}
    frames["qbr_quarters.csv"] = quarter_table(bundle)
    for name, df in frames.items():
        df.to_csv(out_dir / name, index=False, date_format="%Y-%m-%d")
        counts[name] = len(df)
    return counts


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Export BI-tool CSV extracts (synthetic data).")
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = p.parse_args(argv)
    counts = export(DataBundle.load(), args.out_dir)
    for name, n in counts.items():
        print(f"  {name:36s} {n:>8,} rows")
    print(f"extracts written to {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
