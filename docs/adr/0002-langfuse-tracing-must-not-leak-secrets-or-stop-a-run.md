# ADR-0002: Langfuse tracing must not leak secrets or stop a run

- Status: Accepted
- Date: 2026-11-21
- Source: code comments, moved here by the comment clean-up

## Context

The agent sends traces to Langfuse. SDK and HTTP errors can contain credentials and file paths. A tracing failure must not stop an FPL answer, but the smoke test must show every recording error.

## Decision

In normal runs, tracing is best-effort. The code logs a fixed message, never the exception text. The SDK may not capture raw exceptions or tracebacks. When the root trace fails, the run sends no child traces. Only `smoke_test` fails on a recording error. The value `ollama` is the documented placeholder key for a local endpoint, so it is not redacted.

### Where this applies

Each entry gives the file, the symbol and the line of code that the reason was attached to. The reason under it is in its original words.

- `src/fpl/agent/loop.py` › `agent_loop` › `langfuse = None`
  - Do not emit disconnected child traces after root setup failure.
- `src/fpl/agent/observability.py` › `smoke_test` › `try:`
  - This diagnostic must fail on recording errors, unlike normal FPL runs.
- `src/fpl/agent/observability.py` › `private_values_for_run` › `ollama_key = settings.ollama_api_key if settings.ollama_api_key != ...`
  - 'ollama' is the documented, non-secret placeholder for a local endpoint.
- `src/fpl/agent/observability.py` › `get_matching_prompt` › `logger.warning(`
  - Do not log exception text: HTTP errors can contain credentials or paths.
- `src/fpl/agent/observability.py` › `get_tracing_client` › `logger.warning(`
  - Do not log exception text: initialisation errors can leak credentials.
- `src/fpl/agent/observability.py` › `_safe_context` › `caller_failed = False`
  - Keep yield outside the setup handler: model/tool errors are not SDK errors.
- `src/fpl/agent/observability.py` › `_safe_context` › `manager.__exit__(None, None, None)`
  - Do not let the SDK auto-capture raw exceptions or tracebacks.

## Consequences

- A tracing problem shows only as a generic warning. To find the cause, run `make trace-smoke`.
- A new call into the Langfuse SDK must go through the same safe wrappers.
