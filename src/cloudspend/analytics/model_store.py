"""Persist model outputs: local CSV files (always) and Snowflake ANALYTICS tables (optional).

Local files live in data/generated/model_outputs/ and use the same columns as the REPORTING views, so the
dashboard's local mode can read them directly.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pandas as pd

from config.settings import GENERATED_DIR

OUTPUT_DIR = GENERATED_DIR / "model_outputs"
FILES = {"anomalies": "anomalies.csv", "forecast": "forecast.csv",
         "recommendations": "recommendations.csv", "evaluation": "evaluation.csv"}


def now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ------------------------------------------------------------------ evaluation rows
def _flatten_anomaly_metrics(metrics: dict, params: dict, run_id: str, created: datetime) -> list[dict]:
    rows = []
    blob = json.dumps({k: v for k, v in params.items() if k != "if_features"}, default=str)
    for method, periods in metrics.items():
        for period, m in periods.items():
            for name in ("precision", "recall", "f1", "false_positive_rate", "detection_rate",
                         "tp", "fp", "fn", "tn", "n_positive", "n_rows"):
                rows.append(_eval_row(run_id, "anomaly", method, period, name, m[name], blob, created))
            for atype, t in m["by_type"].items():
                for name in ("n", "detected", "detection_rate"):
                    rows.append(_eval_row(run_id, "anomaly", method, f"{period}:{atype}", name, t[name], blob, created))
    return rows


def _flatten_forecast_metrics(backtests: dict, params: dict, run_id: str, created: datetime) -> list[dict]:
    rows, blob = [], json.dumps(params, default=str)
    for scope, models in backtests.items():
        for model, m in models.items():
            for name in ("mae", "wape", "interval_coverage", "n_folds"):
                rows.append(_eval_row(run_id, "forecast", model, scope, name, m.get(name), blob, created))
    return rows


def _eval_row(run_id, family, model, scope, metric, value, params, created) -> dict:
    return {"run_id": run_id, "model_family": family, "model_name": model, "model_version": "v1", "scope": scope,
            "metric_name": metric, "metric_value": None if value is None else float(value),
            "parameters": params, "created_at": created}


def evaluation_rows(anomaly_result, forecast_result, run_id: str, created: datetime) -> pd.DataFrame:
    rows = _flatten_anomaly_metrics(anomaly_result.metrics, anomaly_result.params, run_id, created)
    rows += _flatten_forecast_metrics(forecast_result.backtests, forecast_result.params, run_id, created)
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ local files
def save_local(outputs: dict[str, pd.DataFrame]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for key, df in outputs.items():
        df.to_csv(OUTPUT_DIR / FILES[key], index=False)


def load_local(key: str) -> pd.DataFrame:
    path = OUTPUT_DIR / FILES[key]
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


# ------------------------------------------------------------------ Snowflake
def _py(v):
    """Convert pandas/numpy scalars to plain Python values (None for NaN/NaT)."""
    if v is None or (not isinstance(v, (list, dict, str)) and pd.isna(v)):
        return None
    if hasattr(v, "item"):
        return v.item()
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    return v


def replace_table(conn, table: str, columns: list[str], df: pd.DataFrame) -> int:
    """Atomically replace the whole table contents with `df` (DELETE + INSERT in one transaction)."""
    rows = [tuple(_py(v) for v in r) for r in df[columns].itertuples(index=False, name=None)]
    cur = conn.cursor()
    try:
        cur.execute("BEGIN")
        cur.execute(f"DELETE FROM {table}")
        if rows:
            cur.executemany(
                f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))})", rows)
        cur.execute("COMMIT")
    except Exception:
        cur.execute("ROLLBACK")
        raise
    finally:
        cur.close()
    return len(rows)


def write_snowflake(conn, anomalies: pd.DataFrame, forecast: pd.DataFrame, recs: pd.DataFrame,
                    evaluation: pd.DataFrame, created: datetime) -> dict[str, int]:
    """Write all outputs. `anomalies`/`forecast`/`recs`/`evaluation` are the view-shaped frames."""
    cur = conn.cursor()
    cur.execute("USE WAREHOUSE CLOUDSPEND_WH")
    cur.execute("USE SCHEMA CLOUDSPEND_AI.ANALYTICS")
    dep = dict(cur.execute("SELECT DEPARTMENT_NAME, DEPARTMENT_KEY FROM DIM_DEPARTMENT").fetchall())
    svc = dict(cur.execute("SELECT SERVICE_NAME, SERVICE_KEY FROM DIM_SERVICE").fetchall())
    old_status = dict(cur.execute("SELECT RECOMMENDATION_ID, REVIEW_STATUS FROM FACT_OPTIMIZATION_RECOMMENDATION").fetchall())
    cur.close()

    counts = {}
    a = anomalies.assign(created_at=created)
    a_cols = ["record_id", "detection_method", "method_version", "observed_cost", "baseline_cost", "abs_diff",
              "pct_diff", "anomaly_score", "severity", "reason", "created_at"]
    counts["anomalies"] = replace_table(conn, "FACT_COST_ANOMALY", [c.upper() for c in a_cols], a.rename(columns=str.upper))
    f_cols = ["model_name", "model_version", "scope_type", "scope_value", "forecast_date", "forecast_cost",
              "lower_bound", "upper_bound", "trained_through_date", "created_at"]
    f = forecast.assign(created_at=created).rename(columns={"trained_through_date": "trained_through_date"})
    counts["forecast"] = replace_table(conn, "FACT_COST_FORECAST", [c.upper() for c in f_cols], f.rename(columns=str.upper))
    r = recs.assign(
        department_key=recs["department_name"].map(dep), service_key=recs["service_name"].map(svc),
        review_status=[old_status.get(i, s) for i, s in zip(recs["recommendation_id"], recs["review_status"], strict=True)],
        created_at=created)
    r = r.rename(columns={"period_start": "period_start", "evidence": "evidence", "estimated_savings": "estimated_savings"})
    r_cols = ["recommendation_id", "rule_name", "rule_version", "department_key", "service_key", "period_start",
              "period_end", "evidence", "suggested_action", "estimated_savings", "savings_formula", "confidence",
              "review_status", "created_at"]
    counts["recommendations"] = replace_table(
        conn, "FACT_OPTIMIZATION_RECOMMENDATION", [c.upper() for c in r_cols], r.rename(columns=str.upper))
    e_cols = ["run_id", "model_family", "model_name", "model_version", "scope", "metric_name", "metric_value",
              "parameters", "created_at"]
    counts["evaluation"] = replace_table(conn, "MODEL_EVALUATION", [c.upper() for c in e_cols], evaluation.rename(columns=str.upper))
    return counts
