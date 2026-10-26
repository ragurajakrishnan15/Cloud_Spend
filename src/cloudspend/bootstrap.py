"""First-run setup for a fresh checkout (e.g. a hosted demo): build the synthetic demo data and model outputs if missing.

Local mode only. Both steps are deterministic (fixed seed), so a hosted copy shows the same data as a local one. Nothing here
touches Snowflake or any network service.
"""

from __future__ import annotations

import logging

from cloudspend.analytics import model_store
from config.settings import GENERATED_DIR

log = logging.getLogger("cloudspend.bootstrap")


def _missing() -> list[str]:
    need = []
    if not ((GENERATED_DIR / "cloud_billing_demo.csv").exists() and (GENERATED_DIR / "budgets_demo.csv").exists()):
        need.append("data")
    if not all((model_store.OUTPUT_DIR / f).exists() for f in model_store.FILES.values()):
        need.append("models")
    return need


def ensure_demo_data() -> list[str]:
    """Create whatever is missing; returns the steps performed (empty when everything already existed)."""
    from cloudspend.analytics import run_models
    from cloudspend.data_generation import generate_billing

    done = []
    for step in _missing():
        if step == "data":
            log.info("generating synthetic demo data")
            if generate_billing.main(["--profile", "demo"]) != 0:
                raise RuntimeError("synthetic data generation failed")
        else:
            log.info("computing model outputs")
            if run_models.main(["--source", "csv"]) != 0:
                raise RuntimeError("model computation failed")
        done.append(step)
    return done
