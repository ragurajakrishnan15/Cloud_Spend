"""Capture dashboard screenshots with Playwright, driving the Microsoft Edge already installed on Windows.

    pip install -e ".[screenshots]"
    streamlit run app/Home.py --server.port 8600 --server.headless true     # in another terminal
    python scripts/capture_screenshots.py [--base-url http://localhost:8600] [--out docs/screenshots]

Screenshots show SYNTHETIC data only. The wait conditions look for real page content so a loading skeleton is never captured.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]

PAGES = [
    # (file name, url path, text that proves the page finished rendering, optional extra wait text)
    ("01_spend_overview", "Spend_Overview", "Largest contributors to change", None),
    ("02_budget_variance", "Budget_Variance", "Drill-down: department", None),
    ("03_anomaly_detection", "Anomaly_Detection", "Flagged records", None),
    ("04_spend_forecasting", "Spend_Forecasting", "Backtest and baseline comparison", None),
    ("05_recommendations", "Optimization_Recommendations", "Inspect one recommendation", None),
    ("06_ai_analyst_budget", "AI_Finance_Analyst?q=" + quote("Which departments are furthest over budget?"), "Period used", None),
    ("07_ai_analyst_qbr", "AI_Finance_Analyst?q=" + quote("Draft a QBR summary for the selected period."),
     "Executive summary", None),
]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default="http://localhost:8600")
    p.add_argument("--out", type=Path, default=ROOT / "docs" / "screenshots")
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=True)
        ctx = browser.new_context(viewport={"width": 1500, "height": 1000}, device_scale_factor=1)
        for name, path, ready_text, _ in PAGES:
            page = ctx.new_page()
            page.goto(f"{args.base_url}/{path}", wait_until="domcontentloaded")
            page.get_by_text(ready_text, exact=False).first.wait_for(state="visible", timeout=90_000)
            page.wait_for_timeout(2500)  # let charts finish drawing
            # Streamlit scrolls inside its main container, so full_page would crop: grow the viewport to the content height.
            height = page.evaluate(
                "() => { const m = document.querySelector('[data-testid=\"stMain\"]'); "
                "return m ? m.scrollHeight : document.body.scrollHeight; }"
            )
            page.set_viewport_size({"width": 1500, "height": min(max(int(height), 900), 6000)})
            page.wait_for_timeout(2000)
            target = args.out / f"{name}.png"
            page.screenshot(path=str(target))
            print("saved", target)
            page.close()
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
