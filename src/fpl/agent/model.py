from pathlib import Path

from langfuse import Langfuse
from openai import Omit, OpenAI, omit
from openai.types.chat.chat_completion_message_param import ChatCompletionMessageParam
from openai.types.chat.chat_completion_tool_union_param import (
    ChatCompletionToolUnionParam,
)

from fpl.agent.observability import (
    PROMPT_VERSION,
    safe_observation,
    safe_update,
    sanitise_messages,
    sanitise_trace_data,
)
from fpl.config import Settings

SYSTEM_PROMPT_PATH = Path(__file__).parent / "prompts" / \
    f"system-v{PROMPT_VERSION}.md"


def load_prompt(prompt_path: Path):
    return prompt_path.read_text(encoding="utf-8").strip()


def message_client(message: str) -> list[ChatCompletionMessageParam]:
    system_prompt = load_prompt(SYSTEM_PROMPT_PATH)

    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": message}
    ]

    return messages


def model_request(settings: Settings, lf_client: Langfuse | None, messages: list[ChatCompletionMessageParam],
                  tools: list[ChatCompletionToolUnionParam] | Omit = omit, private_values: tuple[str, ...] = ()):
    client = OpenAI(
        base_url=settings.ollama_base_url,
        api_key=settings.ollama_api_key
    )

    with safe_observation(lf_client, as_type="generation", name="ollama.request",
                          model=settings.ollama_model) as generation_span:
        safe_update(generation_span, lambda: {
            "input": {
                "messages": sanitise_messages(messages, private_values),
                "tools": sanitise_trace_data(tools, private_values),
            },
        })

        response = client.chat.completions.create(
            model=settings.ollama_model,
            messages=(messages),
            tools=tools,
            stream=False,
            temperature=settings.temperature
        )

        safe_update(generation_span, lambda: {
            "output": sanitise_trace_data(response.choices[0].message.model_dump(
                include={"content", "tool_calls"},
                mode="json",
                exclude_none=True,
            ), private_values),
        })

        response_usage = response.usage
        if response_usage is not None:
            safe_update(generation_span, lambda: {
                "usage_details": {
                    "input": response_usage.prompt_tokens,
                    "output": response_usage.completion_tokens,
                },
            })

    return response.choices[0].message
