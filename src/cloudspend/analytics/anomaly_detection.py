"""Cost anomaly detection at resource-day grain: two methods, chronological evaluation.

Method A  rolling_median_mad   robust z-score against the resource's own same-day-type history.
Method B  isolation_forest     Isolation Forest on baseline-relative features.

Rules that keep the evaluation honest:
  * baselines use only PAST observations (shift(1)); the current day never contaminates its own baseline
  * weekday and weekend days are compared with their own kind (handles the weekly seasonality)
  * ground-truth labels are never features; they enter only in `evaluate`
  * thresholds are chosen on the chronological training period; metrics are reported on the later holdout
  * both methods flag cost INCREASES only (the injected anomalies are all increases)
A flag means "unusual relative to a baseline", not "confirmed problem".
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

LABEL_COLUMNS = ("is_injected_anomaly", "anomaly_type")
METHOD_STAT = "rolling_median_mad"
METHOD_IF = "isolation_forest"
METHOD_VERSION = "v1"
MAD_SCALE = 1.4826  # makes MAD comparable to a standard deviation for normal data


@dataclass(frozen=True)
class BaselineConfig:
    window_weekday: int = 20    # previous same-type observations (~4 weeks of weekdays)
    window_weekend: int = 8     # previous weekend observations (~4 weeks)
    min_periods: int = 5        # minimum history before a day can be scored
    mad_floor_pct: float = 0.05  # dispersion is at least 5% of the median (avoids tiny-MAD blow-ups)


@dataclass(frozen=True)
class PipelineConfig:
    baseline: BaselineConfig = BaselineConfig()
    train_fraction: float = 0.6
    z_grid: tuple[float, ...] = (2.5, 3.0, 3.5, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 15.0, 20.0, 30.0, 50.0)
    if_quantile_grid: tuple[float, ...] = (0.90, 0.95, 0.97, 0.98, 0.99, 0.995, 0.998)
    if_estimators: int = 200
    seed: int = 42


# ---------------------------------------------------------------- baseline & features
def add_baseline(records: pd.DataFrame, cfg: BaselineConfig = BaselineConfig()) -> pd.DataFrame:
    """Add is_weekend, baseline_median, baseline_mad, robust_z, ratio. Sorted by resource, date."""
    df = records.sort_values(["resource_id", "usage_date"]).copy()
    df["usage_date"] = pd.to_datetime(df["usage_date"])
    df["is_weekend"] = df["usage_date"].dt.dayofweek >= 5
    df["baseline_median"] = np.nan
    df["baseline_mad"] = np.nan

    def mad(x: np.ndarray) -> float:
        return float(np.median(np.abs(x - np.median(x))))

    for weekend, window in ((False, cfg.window_weekday), (True, cfg.window_weekend)):
        idx = df.index[df["is_weekend"] == weekend]
        grouped = df.loc[idx].groupby("resource_id")["total_cost"]
        df.loc[idx, "baseline_median"] = grouped.transform(
            lambda s, w=window: s.shift(1).rolling(w, min_periods=cfg.min_periods).median()
        )
        df.loc[idx, "baseline_mad"] = grouped.transform(
            lambda s, w=window: s.shift(1).rolling(w, min_periods=cfg.min_periods).apply(mad, raw=True)
        )
    dispersion = np.maximum(MAD_SCALE * df["baseline_mad"], cfg.mad_floor_pct * df["baseline_median"])
    df["robust_z"] = (df["total_cost"] - df["baseline_median"]) / dispersion.replace(0, np.nan)
    df["ratio"] = df["total_cost"] / df["baseline_median"].replace(0, np.nan)
    return df


def build_iforest_features(df: pd.DataFrame) -> pd.DataFrame:
    """Features for Method B. `df` must come from add_baseline. Contains no label columns."""
    g = df.groupby("resource_id")["total_cost"]
    prev, lag7 = g.shift(1), g.shift(7)
    eps = 1e-9
    feats = pd.DataFrame(index=df.index)
    feats["log_ratio_baseline"] = np.log((df["total_cost"] + eps) / (df["baseline_median"] + eps))
    feats["robust_z"] = df["robust_z"].clip(-10, 50)
    feats["log_ratio_prev_day"] = np.log((df["total_cost"] + eps) / (prev + eps))
    feats["log_ratio_lag7"] = np.log((df["total_cost"] + eps) / (lag7 + eps))
    feats["is_weekend"] = df["is_weekend"].astype(int)
    feats["day_of_week"] = df["usage_date"].dt.dayofweek
    feats["log_cost"] = np.log1p(df["total_cost"])
    for col, prefix in (("environment_name", "env"), ("service_name", "svc")):
        feats = feats.join(pd.get_dummies(df[col], prefix=prefix, dtype=int))
    assert not set(LABEL_COLUMNS) & set(feats.columns)
    return feats


# ---------------------------------------------------------------- evaluation helpers
def chronological_split(dates: pd.Series, train_fraction: float) -> pd.Timestamp:
    """First date of the holdout period."""
    lo, hi = dates.min(), dates.max()
    return lo + pd.Timedelta(days=int((hi - lo).days * train_fraction))


def _safe_div(a: float, b: float) -> float | None:
    return None if b == 0 else a / b


def evaluate(y_true: pd.Series, y_pred: pd.Series, anomaly_type: pd.Series | None = None) -> dict:
    y_true, y_pred = y_true.astype(bool), y_pred.astype(bool)
    tp = int((y_true & y_pred).sum())
    fp = int((~y_true & y_pred).sum())
    fn = int((y_true & ~y_pred).sum())
    tn = int((~y_true & ~y_pred).sum())
    precision, recall = _safe_div(tp, tp + fp), _safe_div(tp, tp + fn)
    f1 = None if precision is None or recall is None or (precision + recall) == 0 else (
        2 * precision * recall / (precision + recall))
    out = {
        "n_rows": int(len(y_true)), "n_positive": int(y_true.sum()),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": precision, "recall": recall, "f1": f1,
        "detection_rate": recall, "false_positive_rate": _safe_div(fp, fp + tn), "by_type": {},
    }
    if anomaly_type is not None:
        for t in sorted(anomaly_type[y_true].dropna().unique()):
            m = y_true & (anomaly_type == t)
            out["by_type"][t] = {"n": int(m.sum()), "detected": int((m & y_pred).sum()),
                                 "detection_rate": _safe_div(int((m & y_pred).sum()), int(m.sum()))}
    return out


def best_threshold(y_true: pd.Series, score: pd.Series, candidates) -> float:
    """Candidate with the highest F1 on the given (training) data; ties go to the higher threshold."""
    best, best_f1 = None, -1.0
    for c in sorted(candidates):
        f1 = evaluate(y_true, score >= c)["f1"] or 0.0
        if f1 >= best_f1:
            best, best_f1 = c, f1
    return float(best)


# ---------------------------------------------------------------- pipeline
@dataclass
class AnomalyResult:
    scored: pd.DataFrame      # one row per scoreable record with scores and flags (no labels)
    metrics: dict             # {method: {"train": {...}, "holdout": {...}}}
    params: dict


def run_pipeline(records: pd.DataFrame, labels: pd.DataFrame, cfg: PipelineConfig = PipelineConfig()) -> AnomalyResult:
    """records: model inputs only. labels: record_id + is_injected_anomaly + anomaly_type (evaluation only)."""
    if set(LABEL_COLUMNS) & set(records.columns):
        raise ValueError("records must not contain ground-truth label columns")
    df = add_baseline(records, cfg.baseline)
    df = df[df["baseline_median"].notna() & df["robust_z"].notna()].copy()
    split = chronological_split(df["usage_date"], cfg.train_fraction)
    df["period"] = np.where(df["usage_date"] < split, "train", "holdout")
    lab = labels.set_index("record_id")
    y = df["record_id"].map(lab["is_injected_anomaly"]).astype(bool)
    types = df["record_id"].map(lab["anomaly_type"])
    train = (df["period"] == "train").to_numpy()
    above = (df["total_cost"] > df["baseline_median"]).to_numpy()

    # Method A: pick the z threshold on train, apply everywhere
    z = df["robust_z"].where(above, -np.inf)
    z_thr = best_threshold(y[train], z[train], cfg.z_grid)
    df["stat_score"], df["stat_flag"] = df["robust_z"], (z >= z_thr)

    # Method B: fit unsupervised on train features, calibrate the score threshold on train
    feats = build_iforest_features(df)
    model = IsolationForest(n_estimators=cfg.if_estimators, contamination="auto", random_state=cfg.seed)
    model.fit(feats[train])
    df["if_score"] = -model.score_samples(feats)  # higher = more anomalous
    train_scores = df.loc[train, "if_score"]
    candidates = [float(train_scores.quantile(q)) for q in cfg.if_quantile_grid]
    if_in = df["if_score"].where(above, -np.inf)
    if_thr = best_threshold(y[train], if_in[train], candidates)
    df["if_flag"] = (if_in >= if_thr)

    metrics: dict = {}
    for method, flag in ((METHOD_STAT, "stat_flag"), (METHOD_IF, "if_flag")):
        metrics[method] = {
            period: evaluate(y[df["period"] == period], df.loc[df["period"] == period, flag],
                             types[df["period"] == period])
            for period in ("train", "holdout")
        }
    params = {
        "split_date": str(split.date()), "train_fraction": cfg.train_fraction,
        "stat_z_threshold": z_thr, "if_score_threshold": if_thr, "seed": cfg.seed,
        "baseline": asdict(cfg.baseline), "if_estimators": cfg.if_estimators,
        "if_features": list(feats.columns), "direction": "increase_only",
        "n_scored": int(len(df)),
    }
    return AnomalyResult(df.drop(columns=[c for c in LABEL_COLUMNS if c in df.columns]), metrics, params)


# ---------------------------------------------------------------- output rows
def severity(ratio: float) -> str:
    """Documented rule: observed/baseline >= 3 -> high, >= 1.75 -> medium, otherwise low."""
    return "high" if ratio >= 3 else "medium" if ratio >= 1.75 else "low"


def to_anomaly_rows(result: AnomalyResult) -> pd.DataFrame:
    """One row per (flagged record, method), shaped like FACT_COST_ANOMALY."""
    p, df = result.params, result.scored
    rows = []
    for method, flag, score, thr, why in (
        (METHOD_STAT, "stat_flag", "stat_score", p["stat_z_threshold"],
         "robust z={s:.1f} (threshold {t:.1f}) vs median of previous same-day-type observations"),
        (METHOD_IF, "if_flag", "if_score", p["if_score_threshold"],
         "isolation-forest score {s:.3f} (threshold {t:.3f}); cost above its baseline"),
    ):
        f = df[df[flag]]
        for r in f.itertuples():
            s = getattr(r, score)
            diff = r.total_cost - r.baseline_median
            pct = diff / r.baseline_median
            rows.append({
                "record_id": r.record_id, "detection_method": method, "method_version": METHOD_VERSION,
                "observed_cost": round(float(r.total_cost), 2), "baseline_cost": round(float(r.baseline_median), 2),
                "abs_diff": round(float(diff), 2), "pct_diff": float(pct), "anomaly_score": float(s),
                "severity": severity(r.total_cost / r.baseline_median),
                "reason": f"Cost ${r.total_cost:,.2f} is {pct:+.0%} vs baseline ${r.baseline_median:,.2f}; "
                          + why.format(s=s, t=thr),
            })
    cols = ["record_id", "detection_method", "method_version", "observed_cost", "baseline_cost", "abs_diff",
            "pct_diff", "anomaly_score", "severity", "reason"]
    return pd.DataFrame(rows, columns=cols)
