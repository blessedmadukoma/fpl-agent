from pathlib import Path

from openai import OpenAI

from fpl.config import Settings


def load_prompt(prompt_path: Path):
    return prompt_path.read_text(encoding="utf-8").strip()


def message_client(message: str):
    prompt_path = Path(__file__).parent / "prompts" / "system-v1.md"
    system_prompt = load_prompt(prompt_path)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": message}
    ]

    return messages


def model_request(settings: Settings, messages: list[dict], tools: list[dict] | None = None):
    client = OpenAI(
        base_url=settings.ollama_base_url,
        api_key=settings.ollama_api_key
    )

    response = client.chat.completions.create(
        model=settings.ollama_model,
        messages=messages,
        tools=tools,
        stream=False
    )

    return response.choices[0].message
