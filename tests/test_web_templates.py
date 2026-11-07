"""Render each page template with example data."""

import re

import pytest
from fixtures.web.pages import answer_page, evals_page, history_page

from fpl.web.templating import templates


def render(name, page):
    return templates.env.get_template(name).render(page=page)


def test_evals_page_shows_the_latest_run_and_the_groups():
    html = render("evals.html", evals_page())

    assert "18 / 20" in html
    assert "USD 0.0099 per case" in html
    assert "3 runs of 20 cases" in html
    assert "step19d-glm-5-3-cloud-t0-r3" in html
    assert "not reviewed" in html and "not scored" in html
    assert 'href="/answers/step19e-glm-5-3-cloud-t0-r1/ambiguous-player-name"' in html


def test_history_fragment_holds_only_the_results():
    full = render("history.html", history_page())
    fragment = render("history_results.html", history_page())

    assert full.count('id="history-count"') == 1
    assert "<html" not in fragment
    assert 'hx-swap-oob="true"' in fragment
    assert 'href="/history?page=2"' in fragment


def test_answer_page_renders_markdown_and_escapes_html():
    page = answer_page()
    page.case.answer = "**Bold** <script>alert(1)</script>"
    page.case.question = "<b>Question</b>"

    html = render("answer.html", page)

    assert "<strong>Bold</strong>" in html
    assert "<script>alert" not in html
    assert "&lt;b&gt;Question" in html


def test_answer_page_shows_a_failed_run():
    html = render("answer.html", answer_page("step19-gpt-oss-120b-cloud-t0-r1", "player-history"))

    assert "No answer. The run stopped with ValidationError." in html


@pytest.mark.parametrize("name, page", [
    ("evals.html", evals_page()),
    ("history.html", history_page()),
    ("answer.html", answer_page()),
])
def test_pages_need_no_inline_script_or_style(name, page):
    html = render(name, page)

    assert not re.search(r"<script(?![^>]*\bsrc=)", html)
    assert " style=" not in html
