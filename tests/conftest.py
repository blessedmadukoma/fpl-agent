"""In-memory Langfuse stand-ins: no credentials, exports or network calls."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest


class FakeObservation:
    def __init__(self, client, parameters):
        self.client = client
        self.parameters = parameters
        self.parent = client.active[-1] if client.active else None
        self.trace_id = (
            self.parent.trace_id if self.parent is not None
            else f"{len(client.observations) + 1:032x}"
        )
        self.attributes = dict(client.attributes)
        self.updates = []
        self.closed = False
        self.error = None

    def __enter__(self):
        self.client.fail("observation.enter", self.parameters.get("as_type"))
        self.client.active.append(self)
        return self

    def __exit__(self, error_type, error, traceback):
        self.exit_arguments = (error_type, error, traceback)
        self.error = error
        self.closed = True
        assert self.client.active.pop() is self
        self.client.fail("observation.exit", self.parameters.get("as_type"))
        return False

    def update(self, **fields):
        self.client.fail("observation.update", self.parameters.get("as_type"))
        self.updates.append(fields)
        return self


class FakeLangfuse:
    def __init__(self):
        self.observations = []
        self.active = []
        self.attributes = {}
        self.flush_count = 0
        self.prompt_calls = []
        self.prompt_error = None
        self.failures = set()
        self.fail_as_type = None
        self.auth_count = 0
        self.authenticated = True
        self.prompt = SimpleNamespace(
            name="fpl-system", version=1, prompt="Local system prompt",
            is_fallback=False,
        )

    def start_as_current_observation(self, **parameters):
        self.fail("observation.create", parameters.get("as_type"))
        observation = FakeObservation(self, parameters)
        self.observations.append(observation)
        return observation

    def fail(self, operation, as_type=None):
        if operation in self.failures and (
            self.fail_as_type is None or self.fail_as_type == as_type
        ):
            raise RuntimeError("test-lf-secret /private/path")

    def get_client(self):
        self.fail("client")
        return self

    def auth_check(self):
        self.auth_count += 1
        self.fail("auth")
        return self.authenticated

    def get_prompt(self, name, **parameters):
        self.prompt_calls.append({"name": name, **parameters})
        if self.prompt_error is not None:
            raise self.prompt_error
        return self.prompt

    def propagate_attributes(self, **attributes):
        self.fail("attributes.create")
        return self._attributes_context(attributes)

    @contextmanager
    def _attributes_context(self, attributes):
        self.fail("attributes.enter")
        previous = self.attributes
        self.attributes = {**previous, **attributes}
        if self.active:
            self.active[-1].attributes.update(attributes)
        try:
            yield
        finally:
            self.attributes = previous
            self.fail("attributes.exit")

    def flush(self):
        self.flush_count += 1
        self.fail("flush")


@pytest.fixture
def fake_langfuse():
    return FakeLangfuse()
