from fpl.agent.service import TOOL_REGISTRY


def score_tool_selection(case, saved_result):
    required = set(case["expected_tools"])

    if "tool_calls" not in saved_result:
        raise ValueError("Tool calls were not recorded")

    requested = {call["name"] for call in saved_result.get("tool_calls", [])}
    missing_tools = sorted(required - requested)
    score = 1 if not missing_tools else 0
    return {"score": score, "missing_tools": missing_tools}


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
