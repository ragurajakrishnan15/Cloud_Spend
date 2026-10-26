"""Measure how often an LLM provider's wording survives the numeric-grounding check.

For each example question the analyst computes its answer deterministically, asks the provider to reword it, and accepts the
wording only if every number matches the evidence ledger. This prints (and optionally writes) the measured acceptance rate, so
prompt changes can be compared on evidence instead of impressions. Requires LLM_PROVIDER + credentials; makes real API calls.

    python scripts/eval_llm_grounding.py --provider anthropic [--runs 3] [--out docs/llm_grounding_eval.md]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "app")]

import config.settings  # noqa: E402,F401  (side effect: loads .env)
from cloudspend.ai.analyst import answer  # noqa: E402
from cloudspend.ai.llm import LLMNotAvailable, get_provider  # noqa: E402
from cloudspend.ai.tools import DataBundle  # noqa: E402
from cloudspend.analytics.spend_metrics import Filters  # noqa: E402

QUESTIONS = [
    "Explain the month-over-month cost increase.",
    "Which departments are furthest over budget?",
    "Summarize the three highest-impact anomalies.",
    "Give me the current forecast and its limitations.",
    "What optimization actions should we review?",
    "How much did we spend in the last complete month?",
    "Investigate the cost increase in depth.",
]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", default=None)
    ap.add_argument("--runs", type=int, default=1, help="repeats per question (LLM output varies)")
    ap.add_argument("--delay", type=float, default=0.0, help="seconds to pause between calls (helps with free-tier rate limits)")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    try:
        provider = get_provider(args.provider)
    except LLMNotAvailable as exc:
        print(f"Cannot run: {exc}")
        return 2
    if provider is None:
        print("Cannot run: no provider selected (set LLM_PROVIDER or pass --provider).")
        return 2

    bundle = DataBundle.load()
    d0, d1 = bundle.data_range()
    defaults = Filters(d0, d1)
    rows, accepted, answered, errors, total = [], 0, 0, 0, 0
    for q in QUESTIONS:
        ok = err = 0
        rejected: list[str] = []
        for _ in range(args.runs):
            a = answer(q, bundle, defaults, provider)
            total += 1
            if a.mode == "llm":
                ok += 1
            elif any("provider error" in w for w in a.warnings):
                err += 1      # the API call failed (rate limit, network): says nothing about grounding
            else:
                rejected += a.warnings
            time.sleep(args.delay)
        accepted, errors = accepted + ok, errors + err
        answered += args.runs - err
        rows.append((q, ok, args.runs - err, err, "; ".join(dict.fromkeys(rejected))[:160]))
    lines = [f"# LLM grounding evaluation ({provider.name}, model {getattr(provider, 'model', 'n/a')})", "",
             "Synthetic data. Acceptance = the reworded answer contained only numbers present in the evidence ledger.", "",
             "| Question | Accepted / answered | Provider errors | Grounding rejections |", "|---|---|---|---|"]
    lines += [f"| {q} | {ok}/{n} | {err} | {note} |" for q, ok, n, err, note in rows]
    rate = f"{accepted / answered:.0%}" if answered else "n/a"
    lines += ["", f"**Grounding acceptance: {accepted}/{answered} answered calls ({rate}).** {errors} of {total} calls failed at the "
              "provider (e.g. rate limits) and are excluded. Rejected or failed answers fall back to the deterministic summary, "
              "so a rejection never shows an ungrounded number to the user."]
    report = "\n".join(lines)
    print(report)
    if args.out:
        args.out.write_text(report + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
