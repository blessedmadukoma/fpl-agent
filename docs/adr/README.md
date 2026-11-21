# Architecture decision records

Each file records one topic: the context, the decision and its consequences.
Most of these records started as code comments. The comment clean-up moved each
reason here, so a reader finds it in one place and reviews it like any other change.

## Rules

- Write clean code first: a clear name, a small function or a test usually says
  what a comment would. The `comment-ratchet` pre-commit hook fails when a file
  has more comment lines than `.comment-ratchet.json` allows.
- Put the reason in the ADR for its topic. Add an entry under "Where this applies"
  with the path, the symbol and the line of code, so `grep` finds the place.
- For a new topic, copy the shape of an existing record and use the next number.
- Docstrings, Go doc comments and tool directives are not code comments. Keep them.

## Records

- [ADR-0001: The Release 1 image holds only the web pages](0001-release-1-image-holds-only-the-web-pages.md)
- [ADR-0002: Langfuse tracing must not leak secrets or stop a run](0002-langfuse-tracing-must-not-leak-secrets-or-stop-a-run.md)
- [ADR-0003: Application settings and allow-lists bound the tool arguments](0003-application-settings-and-allow-lists-bound-tool-arguments.md)
- [ADR-0004: Optimiser objective and settings](0004-optimiser-objective-and-settings.md)
- [ADR-0005: No look-ahead in the GW context and the backtests](0005-no-look-ahead-in-gw-context-and-backtests.md)
- [ADR-0006: Projection constants and their sources](0006-projection-constants-and-their-sources.md)
- [ADR-0007: FPL rules and API behaviour in the code](0007-fpl-rules-and-api-behaviour-in-the-code.md)
- [ADR-0008: Public evaluation exports](0008-public-evaluation-exports.md)
- [ADR-0009: Answer scorers](0009-answer-scorers.md)
- [ADR-0010: Web pages under a strict Content Security Policy](0010-web-pages-under-a-strict-csp.md)
- [ADR-0011: Test design choices](0011-test-design-choices.md)
