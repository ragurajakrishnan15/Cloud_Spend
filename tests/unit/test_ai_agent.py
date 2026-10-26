"""Multi-step investigation agent: adaptive plan, bounded steps, trace, grounding and failure handling."""

from datetime import date

from cloudspend.ai import tools as tools_mod
from cloudspend.ai.agent import investigate
from cloudspend.ai.analyst import answer
from cloudspend.ai.intents import Intent, classify
from cloudspend.analytics.spend_metrics import Filters

MAR = Filters(date(2025, 3, 1), date(2025, 3, 31))
JAN = Filters(date(2025, 1, 1), date(2025, 1, 31))   # no previous period in the data
FEB = Filters(date(2025, 2, 1), date(2025, 2, 28))   # spend fell
MEMBERS = {"departments": ["Eng", "Ops"], "services": ["Compute", "Storage"], "environments": ["production", "development"],
           "regions": ["eu", "us"]}


def _tools(ans):
    return [(s.tool, s.status) for s in ans.trace]


def test_investigate_is_routed_from_natural_language():
    for q in ("Investigate the cost increase", "Give me a deep dive on March", "What's the root cause of the spend jump?",
              "Walk me through the spend"):
        assert classify(q, MEMBERS, (date(2025, 1, 1), date(2025, 3, 31)), []).name == "investigate"
    # existing single-step questions keep their routing
    assert classify("Explain the month-over-month cost increase.", MEMBERS, (date(2025, 1, 1), date(2025, 3, 31)), []).name == "cost_change"


def test_material_increase_triggers_drilldown_and_cross_checks(bundle):
    ans = answer("Investigate the spend increase", bundle, MAR)
    assert ans.status == "ok" and ans.intent == "investigate"
    ran = [t for t, s in _tools(ans) if s != "skipped"]
    # summary -> drivers (service, department) -> drill into the top service -> budget -> anomalies -> cross-check -> forecast -> recs
    assert ran[0] == "get_spend_summary"
    assert ran.count("get_top_cost_drivers") == 3
    assert ran.count("get_anomalies") == 1  # anomalies are all in February, so no cross-check call is needed in March
    assert "get_forecast" in ran
    assert all(t in tools_mod.TOOLS for t in ran)           # only approved tools can appear
    assert [s.n for s in ans.trace] == list(range(1, len(ans.trace) + 1))
    assert any("Drill down" in s.reason for s in ans.trace)
    assert "### Headline" in ans.text and "### What moved" in ans.text


def test_cross_check_runs_when_top_driver_service_has_flags(bundle):
    bundle.anomalies = bundle.anomalies.assign(usage_date="2025-03-10")   # put the flags inside the investigated month
    ans = answer("Investigate the spend increase", bundle, MAR)
    calls = [s for s in ans.trace if s.tool == "get_anomalies" and s.status != "skipped"]
    assert len(calls) == 2
    assert "largest cost driver" in calls[1].reason and "services=Compute" in calls[1].arguments
    assert "**Cross-check:**" in ans.text and "not an established cause" in ans.text


def test_small_move_skips_the_driver_drilldown(bundle, monkeypatch):
    monkeypatch.setattr("cloudspend.ai.agent.SIGNIFICANT_CHANGE_PCT", 0.5)   # March's +10.7% now counts as small
    ans = answer("Investigate the spend", bundle, MAR)
    skipped = [s for s in ans.trace if s.status == "skipped"]
    assert any(s.tool == "get_top_cost_drivers" and "less than" in s.reason for s in skipped)
    assert not any(s.tool == "get_top_cost_drivers" and s.status != "skipped" for s in ans.trace)


def test_missing_previous_period_skips_drivers_with_a_stated_reason(bundle):
    ans = answer("Investigate January", bundle, JAN)
    assert any(s.tool == "get_top_cost_drivers" and s.status == "skipped" and "previous period" in s.reason for s in ans.trace)
    assert "No driver breakdown was run" in ans.text


def test_decrease_is_still_investigated_and_not_called_an_increase(bundle):
    ans = answer("Investigate the spend increase", bundle, FEB)
    assert ans.status == "ok"
    assert ans.ledger.get("s1.change_amount").value < 0
    assert "spend did not increase in this period" in ans.text                          # the question's premise is corrected


def test_every_step_is_traced_and_ledger_is_namespaced(bundle):
    ans = answer("Investigate the spend increase", bundle, MAR)
    live = [s for s in ans.trace if s.status != "skipped"]
    assert len(live) == len(ans.results)
    ids = [f.id for f in ans.ledger.figures()]
    assert ids and all(i.startswith("s") and "." in i for i in ids)
    assert len(set(ids)) == len(ids)


def test_step_budget_is_enforced_and_disclosed(bundle):
    ans = investigate("Investigate", bundle, MAR, Intent("investigate"), max_steps=2)
    assert sum(1 for s in ans.trace if s.status != "skipped") == 2
    assert any("step budget" in s.reason for s in ans.trace if s.status == "skipped")
    assert any("step budget" in x for x in ans.limitations)


def test_a_failing_step_does_not_abort_the_investigation(bundle, monkeypatch):
    real = tools_mod.TOOLS["get_forecast"]

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setitem(tools_mod.TOOLS, "get_forecast", boom)
    ans = answer("Investigate the spend increase", bundle, MAR)
    monkeypatch.setitem(tools_mod.TOOLS, "get_forecast", real)
    assert ans.status == "ok"
    assert ("get_forecast", "error") in _tools(ans)
    assert any("get_forecast" in x for x in ans.limitations)
    assert "### Headline" in ans.text


def test_no_matching_spend_returns_no_data(bundle):
    ans = answer("Investigate Ops in the development environment", bundle, MAR)   # Ops only runs in production
    assert ans.status == "no_data" and "nothing to investigate" in ans.text


def test_llm_wording_accepted_only_when_grounded(bundle):
    class Good:
        name = "fake"

        def complete(self, system, user):
            return "Spend rose in March and the analysis is below."

    class Bad(Good):
        def complete(self, system, user):
            return "Spend rose by $999,999 in March."

    good = answer("Investigate the spend increase", bundle, MAR, Good())
    assert good.mode == "llm" and "Spend rose" in good.text
    bad = answer("Investigate the spend increase", bundle, MAR, Bad())
    assert bad.mode == "deterministic" and bad.warnings and "### Headline" in bad.text
