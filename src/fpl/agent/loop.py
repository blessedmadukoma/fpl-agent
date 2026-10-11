import json
import logging
import uuid
from pathlib import Path

from fpl.agent.model import message_client, model_request
from fpl.agent.observability import (
    get_matching_prompt,
    get_tracing_client,
    private_values_for_run,
    safe_attributes,
    safe_flush,
    safe_observation,
    safe_run_metadata,
    safe_update,
    sanitise_trace_data,
)
from fpl.agent.service import run_tool, tool_definitions
from fpl.config import Settings

logger = logging.getLogger(__name__)


def agent_loop(settings: Settings, user_prompt: str, snapshot_dir: Path):
    snapshot_dir = Path(snapshot_dir)
    langfuse = get_tracing_client(settings)
    private_values = ()
    if langfuse is not None:
        try:
            private_values = private_values_for_run(settings, snapshot_dir)
        except Exception:
            logger.warning("Trace redaction setup failed; tracing is disabled for this run.")
            langfuse = None

    try:

        with safe_observation(langfuse, as_type="span", name="fpl-ask") as root_span:
            if root_span is None:
                # Do not emit disconnected child traces after root setup failure.
                langfuse = None
            safe_update(root_span, lambda: {
                "input": sanitise_trace_data(user_prompt, private_values),
            })

            messages = message_client(message=user_prompt)

            local_prompt = messages[0]["content"]

            candidate = get_matching_prompt(langfuse, local_prompt)

            team_tools = tool_definitions()
            allowed_tool_names = {
                definition["function"]["name"]
                for definition in team_tools
            }

            session_id = str(uuid.uuid4())
            metadata = safe_run_metadata(
                snapshot_dir,
                system_prompt=local_prompt,
                session_id=session_id,
                model=settings.ollama_model,
                team_tools=team_tools,
                prompt_name=candidate.name if candidate is not None else None,
                prompt_version=candidate.version if candidate is not None else None,
            ) if langfuse is not None else {}
            safe_update(root_span, metadata=metadata)

            with safe_attributes(langfuse,
                session_id=session_id, metadata=metadata, prompt=candidate,
            ):
                max_model_calls = 4
                for turn in range(max_model_calls):
                    response = model_request(
                        settings, lf_client=langfuse, messages=messages,
                        tools=team_tools, private_values=private_values,
                    )
                    if not response.tool_calls:
                        if response.content is None or not response.content.strip():
                            raise RuntimeError("No valid response from model")

                        messages.append(
                            response.model_dump(
                                include={"role", "content", "tool_calls"},
                                exclude_none=True,
                            )
                        )
                        safe_update(root_span, lambda: {
                            "output": sanitise_trace_data(response.content, private_values),
                        })
                        return response.content

                    messages.append(
                        response.model_dump(
                            include={"role", "content", "tool_calls"},
                            exclude_none=True,
                        )
                    )

                    for call in response.tool_calls:
                        if call.function.name not in allowed_tool_names:
                            raise ValueError(
                                f"Tool '{call.function.name}' is not allowed")

                        arguments = json.loads(call.function.arguments)
                        with safe_observation(langfuse,
                            as_type="tool", name=f"tool-{call.function.name}",
                        ) as tool_span:
                            safe_update(tool_span, lambda: {
                                "input": sanitise_trace_data(arguments, private_values),
                            })
                            result = run_tool(
                                snapshot_dir, call.function.name, arguments)
                            safe_update(tool_span, lambda: {
                                "output": sanitise_trace_data(
                                    result.model_dump(mode="json"), private_values),
                            })

                        messages.append({
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": result.model_dump_json(),
                        })

                raise RuntimeError(
                    "Max model calls reached without a valid response")

    finally:
        safe_flush(langfuse)
