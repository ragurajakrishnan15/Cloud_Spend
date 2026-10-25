import math

import pytest

from cloudspend.ai.ledger import Ledger


@pytest.fixture()
def ledger():
    L = Ledger()
    L.add("total", "Total cost", 1_234_567.89, "usd", "t")
    L.add("chg", "Change", -51.0, "usd", "t")
    L.add("pct", "Change %", 0.1234, "pct", "t")
    L.add("growth", "Growth points", 80.0, "pctpts", "t")
    L.add("n", "Records", 111, "count", "t")
    L.add("wape", "WAPE", 0.025, "pct", "t")
    return L


def test_add_skips_missing_values_and_validates_units():
    L = Ledger()
    L.add("a", "x", None, "usd", "s")
    L.add("b", "x", math.nan, "usd", "s")
    assert len(L) == 0
    with pytest.raises(ValueError):
        L.add("c", "x", 1, "bogus", "s")


def test_formatting(ledger):
    assert ledger.fmt("total") == "$1,234,568"
    assert ledger.fmt("chg") == "-$51" and ledger.fmt_signed("chg") == "-$51"
    assert ledger.fmt_signed("pct") == "+12.3%" and ledger.fmt("pct") == "12.3%"
    assert ledger.fmt("growth") == "80.0%" and ledger.fmt("n") == "111"


def test_grounded_text_passes(ledger):
    text = ("Total spend was $1,234,568 (about $1.23M), down $51 and up 12.3% on a rolling basis; "
            "111 records. ETS WAPE 2.5%. Growth reached 80.0% in 2025-11 (Q3 2025) with `rec-abc123`.")
    assert ledger.ungrounded_numbers(text) == []


def test_ungrounded_numbers_are_reported(ledger):
    bad = ledger.ungrounded_numbers("Spend was $9,999, savings of $42,000 and growth of 55.5% across 321 resources.")
    assert set(bad) == {"$9,999", "$42,000", "55.5%", "321"}


def test_rounding_tolerance_and_scale_suffixes(ledger):
    assert ledger.ungrounded_numbers("$1.2M") == []        # 1.2M within half a unit of the last digit
    assert ledger.ungrounded_numbers("$1.3M") == ["$1.3M"]
    assert ledger.ungrounded_numbers("$1,234,000") != []   # displayed to the dollar: must be exact


def test_percent_matches_fraction_or_points(ledger):
    assert ledger.ungrounded_numbers("12% and 80%") == []
    assert ledger.ungrounded_numbers("13%") == ["13%"]


def test_small_integers_allowed_but_large_must_match(ledger):
    assert ledger.ungrounded_numbers("the top 3 of 7 items") == []
    assert ledger.ungrounded_numbers("there were 15 items") == ["15"]


def test_sign_is_ignored_when_matching(ledger):
    assert ledger.ungrounded_numbers("fell by $51 and -12.3%") == []


def test_merge_with_prefix(ledger):
    other = Ledger()
    other.merge(ledger, prefix="spend.")
    assert other.has("spend.total") and other.fmt("spend.n") == "111"
