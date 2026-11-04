"""Private, optional Langfuse tracing that does not control FPL execution."""

import hashlib
import json
import logging
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from pathlib import Path

from langfuse import get_client, propagate_attributes

from fpl.config import PROJECT_ROOT, Settings, load_settings
from fpl.evals.snapshot_files import git_metadata, read_manifest

logger = logging.getLogger(__name__)
PROMPT_NAME = "fpl-system"
PROMPT_VERSION = 3
FILTERED = "[filtered: unexpected tracing data]"


def smoke_test():
    """Explicitly check configuration, authentication and smoke-trace export."""
    settings = load_settings()
    if not settings.langfuse_tracing_enabled:
        raise RuntimeError(
            "Tracing is disabled; enable it before the smoke test.")
    langfuse = get_tracing_client(settings)
    if langfuse is None:
        raise RuntimeError(
            "Langfuse is unavailable; check the tracing configuration.")
    try:
        authenticated = langfuse.auth_check()
    except Exception:
        raise RuntimeError("Langfuse authentication check failed.") from None
    if not authenticated:
        raise RuntimeError(
            "Authentication failed. Please check your credentials and host.")
    with safe_observation(langfuse, strict=True,
                          as_type="span", name="fpl.trace-smoke") as span:
        if span is None:
            raise RuntimeError("Langfuse smoke observation could not start.")
        # This diagnostic must fail on recording errors, unlike normal FPL runs.
        try:
            span.update(input="hello", output="connection works")
        except Exception:
            raise RuntimeError(
                "Langfuse smoke trace could not be recorded.") from None
    try:
        langfuse.flush()
    except Exception:
        raise RuntimeError(
            "Langfuse smoke trace could not be flushed.") from None
    print("Langfuse smoke test flushed; verify fpl.trace-smoke in the dashboard.")


PRIVATE_KEYS = frozenset({
    "team_name", "entry_id", "api_key", "secret_key", "public_key",
    "ollama_api_key", "langfuse_public_key", "langfuse_secret_key",
    "snapshot_dir", "database_path", "data_dir", "raw_dir", "cache_dir",
})


def collect_private_values(*sources):
    """Collect selected private values, longest first; do not pass whole payloads."""
    collected = []

    def _walk(value):
        if isinstance(value, (str, Path, int)) and not isinstance(value, bool):
            if str(value):
                collected.append(str(value))
        elif isinstance(value, dict):
            for nested in value.values():
                _walk(nested)
        elif isinstance(value, (list, tuple, set, frozenset)):
            for item in value:
                _walk(item)

    for source in sources:
        _walk(source)

    return tuple(sorted(set(collected), key=lambda value: (-len(value), value)))


def private_values_for_run(settings: Settings, snapshot_dir: Path) -> tuple[str, ...]:
    """Select credentials, local paths and frozen team identifiers for redaction."""
    try:
        payload = json.loads(
            (snapshot_dir / "team.json").read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            payload = {}
    except (OSError, ValueError):
        payload = {}
        logger.warning(
            "Frozen team details unavailable for tracing redaction.")

    # 'ollama' is the documented, non-secret placeholder for a local endpoint.
    ollama_key = settings.ollama_api_key if settings.ollama_api_key != "ollama" else ""
    return collect_private_values(
        ollama_key, settings.langfuse_public_key, settings.langfuse_secret_key,
        settings.entry_id, payload.get("entry_id"), payload.get("team_name"),
        snapshot_dir.resolve(), settings.data_dir.resolve(), PROJECT_ROOT,
        Path.home(),
    )


def read_trace_manifest(snapshot_dir: Path) -> dict:
    """Read optional tracing metadata; tool execution still validates the snapshot."""
    try:
        return read_manifest(snapshot_dir)
    except (OSError, ValueError, TypeError, AttributeError):
        logger.warning("Snapshot manifest unavailable for trace metadata.")
        return {}


def _sanitise_value(value, private_values):
    """Strip private keys and redact known private values, recursively."""
    if isinstance(value, dict):
        cleaned = {}
        for key, nested in value.items():
            if isinstance(key, str) and key.lower() in PRIVATE_KEYS:
                continue
            if key == "content" and value.get("role") == "tool":
                if isinstance(nested, str):
                    nested = _filter_json_text(
                        nested, private_values, "[filtered: unparseable tool content]")
                elif isinstance(nested, (dict, list)):
                    nested = _sanitise_value(nested, private_values)
                else:
                    nested = FILTERED
            elif key == "arguments" and isinstance(nested, str):
                nested = _filter_json_text(
                    nested, private_values, "[filtered: unparseable tool arguments]")
            else:
                nested = _sanitise_value(nested, private_values)
            cleaned[key] = nested
        return cleaned

    if isinstance(value, (list, tuple)):
        return [_sanitise_value(item, private_values) for item in value]

    if isinstance(value, str):
        return _redact_private_values(value, private_values)

    if value is None or isinstance(value, (int, float, bool)):
        return value
    return FILTERED


def _redact_private_values(text, private_values):
    """Redact known private values from a free-text string."""
    for secret in private_values:
        if secret and secret in text:
            text = text.replace(secret, "[REDACTED]")
    return text


def _filter_json_text(text, private_values, placeholder):
    """Parse JSON text, filter it, and re-serialise it."""
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return placeholder

    if isinstance(parsed, (dict, list)):
        return json.dumps(_sanitise_value(parsed, private_values))
    return placeholder


def sanitise_trace_data(value, private_values=()):
    """Filter a tracing copy without changing the application data."""
    return _sanitise_value(deepcopy(value), collect_private_values(private_values))


def sanitise_messages(messages: list, private_values=None):
    """Return a deep-copied, sanitised list of messages.

    Private fields are stripped and known private values redacted, so the
    original ``messages`` (and the data sent to Ollama) are never mutated.
    """
    private_values = collect_private_values(private_values or ())
    return [
        sanitise_trace_data(message, private_values)
        if isinstance(message, dict) else {"content": FILTERED}
        for message in messages
    ]


def build_run_metadata(manifest, system_prompt, team_tools, session_id,
                       model, run_kind="manual", case_id=None,
                       run_id: str | None = None,
                       prompt_name=None, prompt_version=None,
                       prompt_hash=None):
    """Build reproducibility metadata for a single question/run."""
    git = git_metadata() or {}

    if prompt_hash is None:
        prompt_hash = hashlib.sha256(
            (system_prompt or "").encode("utf-8")
        ).hexdigest()

    tools_hash = hashlib.sha256(
        json.dumps(
            team_tools,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    try:
        db_hash = manifest["files"]["database"]["sha256"]
    except (KeyError, TypeError):
        db_hash = "unknown"

    dirty = git.get("dirty", None)
    if dirty is None:
        code_dirty = "unknown"
    else:
        code_dirty = "true" if bool(dirty) else "false"

    metadata = {
        "source": "snapshot",
        "snapshot_id": str(manifest.get("snapshot_id", "unknown")),
        "db_hash": str(db_hash),
        "season": str(manifest.get("season", "unknown")),
        "gw": str(manifest.get("gw", "unknown")),
        "code_commit": str(git.get("commit") or "unknown"),
        "code_dirty": code_dirty,
        "model": str(model),
        "provider": "ollama",
        "prompt_name": str(prompt_name if prompt_name is not None else "unknown"),
        "prompt_version": str(
            prompt_version if prompt_version is not None else "unknown"),
        "prompt_hash": prompt_hash,
        "tools_hash": tools_hash,
        "session_id": str(session_id),
        "run_kind": str(run_kind),
    }

    if run_id is not None:
        metadata["run_id"] = str(run_id)
    if case_id is not None:
        metadata["case_id"] = str(case_id)

    return metadata


def validate_prompt(local_prompt, candidate):
    """Keep the prompt reference only when its text matches local inference text."""
    text = getattr(candidate, "prompt", None)
    if (not isinstance(text, str) or getattr(candidate, "is_fallback", False)
            or text.strip() != local_prompt.strip()):
        logger.warning(
            "Langfuse prompt does not match local text; skipping its trace link.")
        return None
    return candidate


def get_matching_prompt(lf_client, local_prompt):
    """Fetch one pinned reference; lookup failure never replaces the local prompt."""
    if lf_client is None:
        return None
    try:
        candidate = lf_client.get_prompt(
            PROMPT_NAME, version=PROMPT_VERSION, type="text",
            max_retries=0, fetch_timeout_seconds=2,
        )
    except Exception:
        # Do not log exception text: HTTP errors can contain credentials or paths.
        logger.warning(
            "Langfuse prompt lookup failed; using the local prompt without a link.")
        return None
    return validate_prompt(local_prompt, candidate)


def get_tracing_client(settings):
    """Initialise optional tracing; authentication checks belong to smoke_test."""
    if not settings.langfuse_tracing_enabled:
        return None

    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        logger.warning("Langfuse credentials missing; tracing is disabled.")
        return None
    try:
        return get_client()
    except Exception:
        # Do not log exception text: initialisation errors can leak credentials.
        logger.warning(
            "Langfuse client initialisation failed; tracing is disabled.")
        return None


@contextmanager
def _safe_context(create_manager, operation, strict=False):
    """Guard SDK entry/exit without suppressing failures in the caller's work."""
    manager = None
    value = None
    try:
        candidate = create_manager()
        value = candidate.__enter__()
        manager = candidate
    except Exception:
        logger.warning(
            "Langfuse %s setup failed; continuing without it.", operation)
        if strict:
            raise RuntimeError(f"Langfuse {operation} setup failed.") from None

    # Keep yield outside the setup handler: model/tool errors are not SDK errors.
    caller_failed = False
    try:
        yield value
    except BaseException as error:
        caller_failed = True
        if operation == "observation":
            safe_update(value, level="ERROR",
                        status_message=type(error).__name__)
        raise
    finally:
        if manager is not None:
            try:
                # Do not let the SDK auto-capture raw exceptions or tracebacks.
                manager.__exit__(None, None, None)
            except Exception:
                logger.warning("Langfuse %s cleanup failed; traces may be incomplete.",
                               operation)
                if strict and not caller_failed:
                    raise RuntimeError(
                        f"Langfuse {operation} cleanup failed.") from None


def safe_observation(client, *, strict=False, **parameters):
    """Return a guarded SDK context, yielding None when tracing is unavailable."""
    if client is None:
        return nullcontext()
    return _safe_context(
        lambda: client.start_as_current_observation(**parameters), "observation", strict)


def safe_update(span, build_fields=None, **fields):
    """Protect both lazy payload preparation and recording; never log raw failures."""
    if span is None:
        return
    try:
        if build_fields is not None:
            fields = {**fields, **build_fields()}
        span.update(**fields)
    except Exception:
        logger.warning(
            "Langfuse observation update failed; continuing without it.")


def safe_attributes(client, **attributes):
    """Guard the SDK propagation context, including its entry and exit."""
    if client is None:
        return nullcontext()
    return _safe_context(lambda: propagate_attributes(**attributes), "attributes")


def safe_run_metadata(snapshot_dir, **fields):
    """Metadata preparation is optional and must not stop the agent."""
    try:
        return build_run_metadata(read_trace_manifest(snapshot_dir), **fields)
    except Exception:
        logger.warning(
            "Trace metadata preparation failed; continuing without it.")
        return {}


def safe_flush(client):
    """Flush buffered events, warning on failure without stopping the answer."""
    if client is None:
        return
    try:
        client.flush()
    except Exception:
        logger.warning("Langfuse flush failed; traces may be incomplete.")
