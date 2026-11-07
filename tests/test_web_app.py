"""Serve the pages from the committed exports."""

from fastapi.testclient import TestClient

from fpl.web.app import app

client = TestClient(app)


def test_answer_page_shows_the_case():
    response = client.get("/answers/step19e-glm-5-3-cloud-t0-r1/ambiguous-player-name")

    assert response.status_code == 200
    assert "Asked during eval run step19e-glm-5-3-cloud-t0-r1" in response.text
    assert response.headers["content-security-policy"].startswith("default-src 'self'")


def test_unknown_answer_is_not_found():
    assert client.get("/answers/step19e-glm-5-3-cloud-t0-r1/no-such-case").status_code == 404


def test_evals_page_adds_up_the_runs():
    response = client.get("/evals")

    assert "step19e-glm-5-3-cloud-t0-r1 · glm-5.3:cloud" in response.text
    assert "USD 0.0099 per case" in response.text
    assert response.text.count('<tbody class="group">') == 42
    assert "3 runs of 20 cases" in response.text


def test_history_filters_the_cases():
    response = client.get("/history", params={"status": "error"})

    assert "35 questions" in response.text


def test_history_returns_only_the_results_to_htmx():
    response = client.get("/history", params={"q": "captain"}, headers={"HX-Request": "true"})

    assert "182 questions" in response.text
    assert "<html" not in response.text


def test_pages_answer_head_requests_with_the_security_headers():
    response = client.head("/evals")

    assert response.status_code == 200
    assert response.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"
    assert response.headers["content-security-policy"].startswith("default-src 'self'")


def test_health_check():
    assert client.get("/healthz").text == "ok"
