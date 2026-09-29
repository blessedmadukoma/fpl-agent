import pandas as pd

from fpl.projections.minutes import flag_category, news_kind


def test_flag_categories():
    assert flag_category("a", None) == "none"
    assert flag_category("d", 75) == "d75"
    assert flag_category("i", 0) == "out"


def test_news_kind_reads_the_return_date():
    deadline = pd.Timestamp("2026-10-10 10:00", tz="UTC")
    assert news_kind("Hamstring injury - Expected back 10 Oct",
                     deadline) == "back_by_deadline"
    assert news_kind("Knee injury - Expected back 7 Nov",
                     deadline) == "back_later"
    assert news_kind("Knee injury - Unknown return date",
                     deadline) == "unknown_return"
    assert news_kind("", deadline) == "none"
