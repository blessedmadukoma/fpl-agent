import json
import logging
import uuid
from pathlib import Path

from pydantic import TypeAdapter

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
from fpl.agent.schemas import Horizon
from fpl.agent.service import run_tool, tool_definitions
from fpl.config import Settings

logger = logging.getLogger(__name__)


def agent_loop(settings: Settings, user_prompt: str, snapshot_dir: Path,
               tool_calls: list[dict] | None = None,
               run_id: str | None = None,
               case_id: str | None = None,
               trace_context: dict | None = None,
               horizon: int | None = None,
               ):
    if horizon is not None:
        horizon = TypeAdapter(Horizon).validate_python(horizon)
    snapshot_dir = Path(snapshot_dir)
    langfuse = get_tracing_client(settings)
    private_values = ()
    if langfuse is not None:
        try:
            private_values = private_values_for_run(settings, snapshot_dir)
        except Exception:
            logger.warning(
                "Trace redaction setup failed; tracing is disabled for this run.")
            langfuse = None

    try:

        with safe_observation(langfuse, as_type="span", name="fpl-ask") as root_span:
            if root_span is None:
                # Do not emit disconnected child traces after root setup failure.
                langfuse = None
            safe_update(root_span, lambda: {
                "input": sanitise_trace_data(user_prompt, private_values),
            })

            if trace_context is not None and root_span is not None:
                try:
                    trace_id = root_span.trace_id
                except Exception:
                    trace_id = None
                if isinstance(trace_id, str):
                    trace_context["trace_id"] = trace_id

            messages = message_client(message=user_prompt)

            local_prompt = messages[0]["content"]

            candidate = get_matching_prompt(langfuse, local_prompt)

            team_tools = tool_definitions()
            horizon_tools = set()
            if horizon is not None:
                for definition in team_tools:
                    function = definition["function"]
                    properties = function["parameters"].get("properties", {})
                    if "horizon" in properties:
                        properties["horizon"].update(
                            {"enum": [horizon], "default": horizon},
                        )
                        horizon_tools.add(function["name"])
            allowed_tool_names = {
                definition["function"]["name"]
                for definition in team_tools
            }

            session_id = run_id or str(uuid.uuid4())
            metadata = safe_run_metadata(
                snapshot_dir,
                system_prompt=local_prompt,
                session_id=session_id,
                model=settings.ollama_model,
                team_tools=team_tools,
                run_id=run_id,
                case_id=case_id,
                run_kind="evaluation" if case_id is not None else "manual",
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
                        record = {
                            "tool_call_id": call.id,
                            "name": call.function.name,
                            "raw_arguments": call.function.arguments,
                            "arguments": None,
                            "status": "requested",
                        }
                        if tool_calls is not None:
                            tool_calls.append(record)

                        try:
                            if call.function.name not in allowed_tool_names:
                                raise ValueError(
                                    f"Tool '{call.function.name}' is not allowed")

                            arguments = json.loads(call.function.arguments)
                            if (
                                call.function.name in horizon_tools
                                and isinstance(arguments, dict)
                            ):
                                # Explicit application settings outrank model guesses.
                                arguments = {**arguments, "horizon": horizon}
                            record["arguments"] = arguments
                            with safe_observation(langfuse,
                                                  as_type="tool", name=f"tool-{call.function.name}",
                                                  ) as tool_span:
                                safe_update(tool_span, lambda: {
                                    "input": sanitise_trace_data(arguments, private_values),
                                })
                                result = run_tool(
                                    snapshot_dir, call.function.name, arguments)
                                serialised_result = result.model_dump(
                                    mode="json")
                                safe_update(tool_span, lambda: {
                                    "output": sanitise_trace_data(
                                        serialised_result, private_values),
                                })

                            record["result"] = serialised_result
                            record["status"] = "completed"

                            messages.append({
                                "role": "tool",
                                "tool_call_id": call.id,
                                "content": result.model_dump_json(),
                            })
                        except Exception as exc:
                            record["status"] = "error"
                            record["error_type"] = type(exc).__name__
                            raise

                raise RuntimeError(
                    "Max model calls reached without a valid response")

    finally:
        safe_flush(langfuse)
