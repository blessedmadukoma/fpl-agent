import json
from pathlib import Path

from fpl.agent.model import message_client, model_request
from fpl.agent.service import run_tool, tool_definitions
from fpl.config import Settings


def agent_loop(settings: Settings, user_prompt: str, snapshot_dir: Path):
    # initial history
    messages = message_client(message=user_prompt)

    team_tools = tool_definitions()
    allowed_tool_names = {
        definition["function"]["name"]
        for definition in team_tools
    }

    max_model_calls = 4
    for turn in range(max_model_calls):
        response = model_request(
            settings, messages=messages, tools=team_tools)
        if not response.tool_calls:
            if response.content is None or not response.content.strip():
                raise RuntimeError("No valid response from model")

            # append the assistant message
            messages.append(
                response.model_dump(
                    include={"role", "content", "tool_calls"},
                    exclude_none=True,
                )
            )
            return response.content

        # append the assistant message
        messages.append(
            response.model_dump(
                include={"role", "content", "tool_calls"},
                exclude_none=True,
            )
        )

        for call in response.tool_calls:
            if call.function.name not in allowed_tool_names:
                raise ValueError(f"Tool '{call.function.name}' is not allowed")

            # call = response.tool_calls[tool]
            arguments = json.loads(call.function.arguments)
            # snapshot = "data/evals/snapshots/20261007_015905_current-check_0d1e87bc-dirty"

            # parse its arguments, execute it via run_tool, append the result with it's call ID
            result = run_tool(snapshot_dir, call.function.name, arguments)

            # send the updated history again
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": result.model_dump_json(),
            })

    # answer = model_request(settings, messages=messages, tools=team_tools)

    raise RuntimeError("Max model calls reached without a valid response")
