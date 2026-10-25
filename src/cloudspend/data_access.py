"""Data access for the dashboard. Two interchangeable backends returning the same lower-cased columns:
  - snowflake: reads the REPORTING views (the only objects the app needs)
  - local:     builds equivalent frames from the CSVs with pandas (no credentials needed)
Mode: CLOUDSPEND_DATA_MODE=local|snowflake, default snowflake when credentials exist, else local.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from cloudspend.analytics import model_store
from cloudspend.analytics.local_views import build_budget_variance, build_daily
from cloudspend.ingestion.snowflake_client import get_connection
from config.settings import GENERATED_DIR, SAMPLE_DIR, load_app_snowflake_settings

R = "CLOUDSPEND_AI.REPORTING"
MAX_ROWS = 500_000  # safety cap on any single result set


class DataUnavailableError(RuntimeError):
    """Raised with a user-readable message when no data source can be used."""


@dataclass(frozen=True)
class SourceInfo:
    mode: str                 # 'snowflake' | 'local'
    read_only: bool | None    # None for local
    detail: str


def resolve_mode() -> str:
    forced = (os.environ.get("CLOUDSPEND_DATA_MODE") or "").lower()
    if forced in ("local", "snowflake"):
        return forced
    settings, _ = load_app_snowflake_settings()
    return "snowflake" if settings.is_configured else "local"


def _query(sql: str) -> pd.DataFrame:
    settings, _ = load_app_snowflake_settings()
    with get_connection(settings, database=None, schema=None) as conn:
        cur = conn.cursor()
        try:
            cur.execute("USE WAREHOUSE CLOUDSPEND_WH")
            cur.execute(f"{sql} LIMIT {MAX_ROWS}")
            df = pd.DataFrame(cur.fetchall(), columns=[c[0].lower() for c in cur.description])
        finally:
            cur.close()
    for col in df.columns:  # Decimal -> float for numeric columns
        if df[col].dtype == object and len(df) and df[col].map(lambda v: type(v).__name__).eq("Decimal").all():
            df[col] = df[col].astype(float)
    return df


def _local_files() -> tuple[str, str]:
    for folder, profile in ((GENERATED_DIR, "demo"), (SAMPLE_DIR, "dev")):
        b, g = folder / f"cloud_billing_{profile}.csv", folder / f"budgets_{profile}.csv"
        if b.exists() and g.exists():
            return str(b), str(g)
    raise DataUnavailableError(
        "No local data found. Run: python -m cloudspend.data_generation.generate_billing --profile demo"
    )


def _local_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    b_path, g_path = _local_files()
    daily = build_daily(pd.read_csv(b_path))
    return daily, build_budget_variance(daily, pd.read_csv(g_path))


def load_daily() -> pd.DataFrame:
    if resolve_mode() == "local":
        return _local_frames()[0]
    df = _query(f"SELECT * FROM {R}.VW_DAILY_CLOUD_SPEND")
    df["usage_date"] = pd.to_datetime(df["usage_date"])
    return df


def load_budget_variance() -> pd.DataFrame:
    if resolve_mode() == "local":
        return _local_frames()[1]
    df = _query(f"SELECT * FROM {R}.VW_BUDGET_VARIANCE")
    df["month_start"] = pd.to_datetime(df["month_start"])
    return df


def load_refresh_info() -> SourceInfo:
    """Source description plus last successful refresh time."""
    if resolve_mode() == "local":
        b_path, _ = _local_files()
        ts = datetime.fromtimestamp(os.path.getmtime(b_path)).strftime("%Y-%m-%d %H:%M")
        return SourceInfo("local", None, f"Local CSV ({os.path.basename(b_path)}), file written {ts}")
    _, read_only = load_app_snowflake_settings()
    df = _query(f"SELECT file_name, last_successful_load FROM {R}.VW_DATA_REFRESH")
    if df.empty:
        return SourceInfo("snowflake", read_only, "Snowflake - no successful load recorded")
    r = df.iloc[0]
    return SourceInfo("snowflake", read_only, f"Snowflake - {r['file_name']}, last successful load {r['last_successful_load']} UTC")


def _model_output(view: str, local_key: str) -> pd.DataFrame:
    """Stored model results: Snowflake REPORTING view, or the local files written by run_models."""
    if resolve_mode() == "local":
        return model_store.load_local(local_key)
    return _query(f"SELECT * FROM {R}.{view}")


def load_anomalies() -> pd.DataFrame:
    return _model_output("VW_COST_ANOMALIES", "anomalies")


def load_forecast() -> pd.DataFrame:
    return _model_output("VW_COST_FORECAST", "forecast")


def load_recommendations() -> pd.DataFrame:
    return _model_output("VW_OPTIMIZATION_RECOMMENDATIONS", "recommendations")


def load_model_evaluation() -> pd.DataFrame:
    return _model_output("VW_MODEL_EVALUATION", "evaluation")
