import re

from fpl.agent.service import TOOL_REGISTRY


def score_tool_selection(case, saved_result):
    required = set(case["expected_tools"])

    if "tool_calls" not in saved_result:
        raise ValueError("Tool calls were not recorded")

    requested = {call["name"] for call in saved_result.get("tool_calls", [])}
    missing_tools = sorted(required - requested)
    score = 1 if not missing_tools else 0
    return {"score": score, "missing_tools": missing_tools}


NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?")
LIST_MARKER_PATTERN = re.compile(r"^\s*\d+\.\s", re.MULTILINE)


def numbers_in_text(text):
    """Turn every number in a text into an int ("62") or a float ("6.2")."""
    return [float(n) if "." in n else int(n) for n in NUMBER_PATTERN.findall(text)]


def numbers_in_tool_result(data):
    """Collect every number in a tool result, including numbers inside text."""
    if isinstance(data, bool):
        return []
    if isinstance(data, (int, float)):
        return [data]
    if isinstance(data, str):
        return numbers_in_text(data)

    numbers = []
    if isinstance(data, dict):
        for value in data.values():
            numbers.extend(numbers_in_tool_result(value))
    elif isinstance(data, list):
        for item in data:
            numbers.extend(numbers_in_tool_result(item))
    return numbers


def is_supported(written, sources):
    """True if one source number can explain this answer number."""
    decimals = len(written.split(".")[1]) if "." in written else 0
    target = float(written)

    for source in sources:
        source = abs(source)
        if isinstance(source, int):
            # A whole number as is cannot explain "10.0" (GW10).
            if decimals == 0 and source == target:
                return True
            # Prices are stored in tenths: 62 means 6.2.
            if round(source / 10, decimals) == target:
                return True
        else:
            # Rounded: 3.7819 can appear as 3.78 or 3.8.
            if round(source, decimals) == target:
                return True
            # A share as a percentage: 0.41 can appear as 41.
            if round(source * 100, decimals) == target:
                return True
    return False


def score_numbers(case, saved_result):
    """Every number in the answer must come from a tool result or the question."""
    answer = saved_result.get("answer")

    # score: None if it does not apply to the specific case i.e. no numbers to score
    if answer is None:
        return {"score": None, "unsupported": []}

    sources = []

    for call in saved_result["tool_calls"]:
        if call["status"] == "completed":
            sources.extend(numbers_in_tool_result(call.get("result")))
    sources.extend(numbers_in_text(saved_result["input"]))

    answer = LIST_MARKER_PATTERN.sub("", answer)
    unsupported = [n for n in NUMBER_PATTERN.findall(
        answer) if not is_supported(n, sources)]

    return {"score": 0 if unsupported else 1, "unsupported": unsupported}


def score_arguments(case, saved_result):
    expected_arguments = case.get("expected_arguments", {})

    if "tool_calls" not in saved_result:
        raise ValueError("Tool calls were not recorded")

    tool_calls = saved_result.get("tool_calls", [])

    calls_by_name = {}
    for call in tool_calls:
        if "name" not in call:
            raise ValueError("Tool call is missing a 'name' field")
        if "arguments" not in call:
            raise ValueError("Tool call is missing an 'arguments' field")
        name = call["name"]
        args = call["arguments"]
        calls_by_name.setdefault(name, []).append(args)

    issues = []

    from pydantic import ValidationError

    for tool_name, expected_fields in expected_arguments.items():
        if tool_name not in calls_by_name:
            issues.append(f"Missing tool call: {tool_name}")
            continue

        entry = TOOL_REGISTRY.get(tool_name)
        if entry is None:
            issues.append(f"Unknown tool: {tool_name}")
            continue

        input_schema, _ = entry

        for call_index, raw_args in enumerate(calls_by_name[tool_name]):
            try:
                validated = input_schema.model_validate(raw_args)
            except ValidationError:
                issues.append(
                    f"Validation error in {tool_name} (call {call_index})"
                )
                continue

            validated_args = validated.model_dump()

            for field, expected_value in expected_fields.items():
                if field not in validated_args:
                    issues.append(
                        f"Missing field '{field}' in {tool_name} (call {call_index})"
                    )
                    continue
                actual_value = validated_args[field]
                if isinstance(expected_value, list) and isinstance(actual_value, list):
                    if sorted(expected_value) != sorted(actual_value):
                        issues.append(
                            f"Mismatch for field '{field}' in {tool_name} (call {call_index}): "
                            f"expected {expected_value}, got {actual_value}"
                        )
                elif actual_value != expected_value:
                    issues.append(
                        f"Mismatch for field '{field}' in {tool_name} (call {call_index}): "
                        f"expected {expected_value}, got {actual_value}"
                    )

    score = 1 if not issues else 0
    return {"score": score, "issues": issues}
