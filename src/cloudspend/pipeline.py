"""End-to-end refresh pipeline: generate -> validate -> (load -> transform + reconcile) -> models.

    python -m cloudspend.pipeline --mode local        # no credentials needed: CSV -> validation -> models -> local files
    python -m cloudspend.pipeline --mode snowflake    # also loads RAW, rebuilds ANALYTICS/REPORTING, reconciles, writes model outputs

Each stage is the same command documented in the README, called in-process. The pipeline stops at the first failing stage and
exits with that stage's code (0 = success, 1 = failure, 2 = configuration / missing input), so a scheduler (cron, GitHub Actions,
a Snowflake task wrapper) can treat a non-zero exit as an alert. Every run appends one JSON line (stage, code, seconds) to
data/generated/pipeline_runs.jsonl; no credentials or row data are logged.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from config.settings import DEFAULT_SEED, GENERATED_DIR

RUN_LOG = GENERATED_DIR / "pipeline_runs.jsonl"


@dataclass
class StageResult:
    name: str
    exit_code: int
    seconds: float


Stage = tuple[str, Callable[[], int]]


def build_stages(mode: str, profile: str, seed: int, out_dir: Path, regenerate: bool, setup: bool) -> list[Stage]:
    from cloudspend.analytics import run_models
    from cloudspend.data_generation import generate_billing
    from cloudspend.ingestion import load_csv, transform
    from cloudspend.validation import billing_checks

    billing, budgets = out_dir / f"cloud_billing_{profile}.csv", out_dir / f"budgets_{profile}.csv"
    stages: list[Stage] = []
    if regenerate or not (billing.exists() and budgets.exists()):
        stages.append(("generate", lambda: generate_billing.main(["--profile", profile, "--seed", str(seed), "--out-dir", str(out_dir)])))
    stages.append(("validate", lambda: billing_checks.main([str(billing), "--budgets-csv", str(budgets)])))
    if mode == "snowflake":
        load_args = ["--billing", str(billing), "--budgets", str(budgets)] + (["--setup"] if setup else [])
        stages.append(("load_raw", lambda: load_csv.main(load_args)))
        stages.append(("transform_and_reconcile", lambda: transform.main(["--billing-file", billing.name, "--budgets-file", budgets.name])))
        stages.append(("models", lambda: run_models.main(["--source", "snowflake"])))
    else:
        stages.append(("models", lambda: run_models.main(["--source", "csv", "--billing-csv", str(billing), "--budgets-csv", str(budgets)])))
    return stages


def run(stages: list[Stage], log_path: Path | None = RUN_LOG) -> tuple[int, list[StageResult]]:
    results: list[StageResult] = []
    code = 0
    for name, fn in stages:
        print(f"\n=== stage: {name} ===")
        t0 = time.perf_counter()
        try:
            rc = int(fn() or 0)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
        except Exception as exc:  # report the type only: messages can echo connection details
            print(f"FAILED: {type(exc).__name__}")
            rc = 1
        results.append(StageResult(name, rc, round(time.perf_counter() - t0, 2)))
        if rc != 0:
            code = rc
            print(f"=== stage '{name}' failed with exit code {rc}; later stages are skipped ===")
            break
    if log_path is not None:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            entry = {"finished_at": datetime.now(UTC).isoformat(timespec="seconds"), "status": "success" if code == 0 else "failed",
                     "stages": [asdict(r) for r in results]}
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        except OSError as exc:
            print(f"warning: could not write run log ({type(exc).__name__})")
    return code, results


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run the CloudSpend refresh pipeline.")
    p.add_argument("--mode", choices=["local", "snowflake"], default="local")
    p.add_argument("--profile", default="demo")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--out-dir", type=Path, default=GENERATED_DIR)
    p.add_argument("--regenerate", action="store_true", help="regenerate the CSVs even if they already exist")
    p.add_argument("--setup", action="store_true", help="snowflake mode: run the database/raw-table DDL first")
    args = p.parse_args(argv)
    stages = build_stages(args.mode, args.profile, args.seed, args.out_dir, args.regenerate, args.setup)
    code, results = run(stages)
    print("\nSummary: " + ", ".join(f"{r.name}={'ok' if r.exit_code == 0 else 'FAIL'} ({r.seconds}s)" for r in results))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
