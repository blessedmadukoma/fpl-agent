"""Check versioned 20-case datasets without snapshots or network access."""

import hashlib
import json
from pathlib import Path

import pytest

from fpl.agent.service import TOOL_REGISTRY
from fpl.evals.runner import load_cases


DATASET_ROOT = Path(__file__).resolve().parents[1] / "evals"
CURRENT_MANIFEST = json.loads(
    (DATASET_ROOT / "fpl-agent-v2.manifest.json").read_text(encoding="utf-8")
)
CURRENT_REFERENCES = json.loads(
    (DATASET_ROOT / CURRENT_MANIFEST["references_file"]).read_text(encoding="utf-8")
)
DATASETS = {
    "v1": "20261007_015905_current-check_0d1e87bc-dirty",
    "v2-post-gw6": "20261014_130603_post-gw6-baseline_e28400ad-dirty",
    "v2": CURRENT_MANIFEST["snapshot_id"],
}
DATASET_FILES = {
    "v1": "fpl-agent-v1.jsonl",
    "v2-post-gw6": "archive/fpl-agent-v2-post-gw6.jsonl",
    "v2": "fpl-agent-v2.jsonl",
}
CASES_BY_VERSION = {
    version: load_cases(DATASET_ROOT / DATASET_FILES[version])
    for version in DATASETS
}
VERSIONED_CASES = [
    pytest.param(version, case, id=f"{version}-{case['id']}")
    for version, cases in CASES_BY_VERSION.items()
    for case in cases
]


@pytest.mark.parametrize("version", DATASETS)
def test_dataset_has_twenty_distinct_case_ids(version):
    cases = CASES_BY_VERSION[version]
    assert len(cases) == 20
    assert len({case["id"] for case in cases}) == 20


@pytest.mark.parametrize("version,case", VERSIONED_CASES)
def test_case_has_required_fields_and_the_selected_snapshot(version, case):
    required_fields = {
        "id", "input", "snapshot_id", "expected_tools",
        "expected_arguments", "expected_facts", "answer_kind", "reason",
    }
    assert required_fields <= set(case)
    assert case["snapshot_id"] == DATASETS[version]
    for field in ("id", "input", "reason"):
        assert isinstance(case[field], str)
        assert case[field].strip()
    assert isinstance(case["expected_facts"], dict)
    assert case["expected_facts"]
    assert case["answer_kind"] in {
        "observed", "projection", "refusal", "clarification",
    }


@pytest.mark.parametrize("version,case", VERSIONED_CASES)
def test_expected_tools_and_arguments_match_registered_schemas(version, case):
    expected_tools = case["expected_tools"]
    assert isinstance(expected_tools, list)
    assert len(expected_tools) == len(set(expected_tools))
    assert set(expected_tools) <= set(TOOL_REGISTRY)
    assert set(case["expected_arguments"]) == set(expected_tools)
    for name, arguments in case["expected_arguments"].items():
        input_schema, _ = TOOL_REGISTRY[name]
        input_schema.model_validate(arguments)


@pytest.mark.parametrize("version", DATASETS)
def test_dataset_covers_all_seven_existing_tools(version):
    covered_tools = {
        name for case in CASES_BY_VERSION[version]
        for name in case["expected_tools"]
    }
    assert covered_tools == set(TOOL_REGISTRY)


@pytest.mark.parametrize("version", DATASETS)
def test_cases_without_required_tools_have_manual_behaviour_checks(version):
    for case in CASES_BY_VERSION[version]:
        if not case["expected_tools"]:
            assert case["answer_kind"] in {"refusal", "clarification"}
            assert "manually" in case["reason"]


def test_post_gw6_dataset_tests_fpl_assists_with_supported_tools():
    cases = {case["id"]: case for case in CASES_BY_VERSION["v2-post-gw6"]}
    player = cases["player-fpl-assists"]
    assert player["expected_arguments"]["get_player_summary"] == {
        "element_id": 154, "history_gws": 1,
    }
    assert player["expected_facts"]["history"] == [{"gw": 6, "assists": 2.0}]
    leaders = cases["historical-fpl-assist-leaders"]
    assert leaders["expected_arguments"]["get_historical_leaders"] == {
        "gw": 6, "statistic": "assists", "limit": 3,
    }


def test_provisional_bonus_case_checks_a_tool_limit_not_invented_values():
    case = next(
        case for case in CASES_BY_VERSION["v2-post-gw6"]
        if case["id"] == "unsupported-provisional-bonus-timeline"
    )
    assert case["answer_kind"] == "refusal"
    facts = case["expected_facts"]
    assert facts["provisional_bonus_timeline_available"] is False
    assert facts["player_summary_bonus_field_available"] is False
    assert facts["player_summary_bps_field_available"] is False
    assert facts["must_not_invent_in_match_bonus"] is True


def test_current_dataset_and_references_match_recorded_hashes():
    for filename, expected_hash in (
        (CURRENT_MANIFEST["dataset_file"], CURRENT_MANIFEST["dataset_sha256"]),
        (CURRENT_MANIFEST["references_file"], CURRENT_MANIFEST["references_sha256"]),
        (
            CURRENT_MANIFEST["archived_baseline"]["dataset_file"],
            CURRENT_MANIFEST["archived_baseline"]["dataset_sha256"],
        ),
    ):
        assert hashlib.sha256((DATASET_ROOT / filename).read_bytes()).hexdigest() == expected_hash
    assert CURRENT_REFERENCES["snapshot_id"] == CURRENT_MANIFEST["snapshot_id"]
    assert CURRENT_MANIFEST["case_count"] == len(CASES_BY_VERSION["v2"])


@pytest.mark.parametrize("case", CASES_BY_VERSION["v2"], ids=lambda case: case["id"])
def test_current_case_matches_its_executed_reference(case):
    if case["reference"] is None:
        assert case["expected_tools"] == []
        return
    reference = CURRENT_REFERENCES["tools"][case["reference"]]
    assert case["expected_tools"] == [reference["tool"]]
    assert case["expected_arguments"] == {reference["tool"]: reference["arguments"]}
    assert reference["result"]["snapshot_id"] == CURRENT_MANIFEST["snapshot_id"]
    for row in reference["result"].get("history", []):
        assert row["gw"] in CURRENT_MANIFEST["finished_gws"]
    for field in ("gws", "actual_gws"):
        assert all(
            gw >= CURRENT_MANIFEST["target_gw"]
            for gw in reference["result"].get(field, [])
        )


def test_current_entity_questions_supply_ids_without_a_resolution_tool():
    for case in CASES_BY_VERSION["v2"]:
        for arguments in case["expected_arguments"].values():
            ids = arguments.get("element_ids", [])
            for field in ("element_id", "team_id"):
                if field in arguments:
                    ids = [*ids, arguments[field]]
            assert all(str(entity_id) in case["input"] for entity_id in ids)


def test_current_recommendations_cover_transfer_and_hold_verdicts():
    cases = {case["id"]: case for case in CASES_BY_VERSION["v2"]}
    transfer = cases["recommendation-transfers-and-captain"]["expected_facts"]
    hold = cases["recommendation-high-threshold-hold"]["expected_facts"]
    assert transfer["make_transfers"] is True
    assert transfer["gain"] >= transfer["threshold"]
    assert hold["make_transfers"] is False
    assert hold["gain"] < hold["threshold"]
    assert hold["first_gw_plan"]["buys"] == []
    assert hold["first_gw_plan"]["sells"] == []
