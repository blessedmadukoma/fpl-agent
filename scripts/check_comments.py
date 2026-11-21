#!/usr/bin/env python3
"""Comment ratchet: fail when a file has more comment lines than the baseline allows.

Counted: `#`, `//`, `--`, `/* */`, `<!-- -->` and `{# #}` comments in code, web and build files.
Not counted:
- docstrings, and Go doc comments: the comment group directly above a top-level declaration,
  or above a field, method or spec outside a function body when it starts with that name;
- tool directives: `# noqa`, `# type: ignore`, `//go:`, `//nolint`, swag `// @` annotations,
  `-- name:`, `-- +goose`, shebangs, `#cloud-config`, HTML conditional comments and similar;
- Makefile `## help` text, sqlc query files (sqlc copies their comments into the generated Go)
  and generated files.

    python3 scripts/check_comments.py           check against .comment-ratchet.json
    python3 scripts/check_comments.py --update  lower the baseline to the current counts
    python3 scripts/check_comments.py --list    print every counted comment
    python3 scripts/check_comments.py --json    the same as JSON, with offsets

`allow` in .comment-ratchet.json lists extra regexes for comments that tools read.
The baseline only goes down. `--update` refuses to raise any count; `--init` writes the first one.
Decisions that need a reason go to docs/adr/, not into comments.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
import tokenize
from dataclasses import asdict, dataclass
from pathlib import Path

BASELINE = Path(".comment-ratchet.json")

PY_PRAGMA = re.compile(
    r"^#\s*(noqa\b|type:\s*ignore|pragma\b|pyright:|mypy:|fmt:\s*(on|off|skip)|isort:|ruff:|pylint:|///)"
)
GO_DIRECTIVE = re.compile(r"^//(go:|line |export |extern |lint:|\s*nolint|\s*\+build|\s*@[A-Za-z])")
GO_TOP_DECL = re.compile(r"^(func|type|var|const|package)\b")
GO_GENERATED = re.compile(r"^// Code generated .* DO NOT EDIT\.$", re.M)
SQL_DIRECTIVE = re.compile(r"^--\s*(\+goose|\+migrate|name:|sqlc\.)")
HASH_DIRECTIVE = re.compile(
    r"^#(!|cloud-config|\s*(syntax|escape|check)=|\s*shellcheck\s|\s*yaml-language-server:|\s*-\*-)"
)
JS_DIRECTIVE = re.compile(r"^(/\*!|//\s*@ts-|/\*\s*(eslint|global|#__PURE__)|//\s*eslint-)")

HASH_NAMES = {"Makefile", "Dockerfile", ".dockerignore", "Containerfile"}
HASH_SUFFIXES = {".toml", ".yml", ".yaml", ".sh", ".bash", ".mk"}
C_SUFFIXES = {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}
HTML_SUFFIXES = {".html", ".jinja", ".j2"}


@dataclass
class Comment:
    path: str
    line: int
    end_line: int
    start: int
    end: int
    text: str


def language(path: Path) -> str | None:
    name = path.name
    if name.endswith(".min.js") or path == BASELINE:
        return None
    if name.startswith("Dockerfile") or name in HASH_NAMES or path.suffix in HASH_SUFFIXES:
        return "hash"
    return {
        ".py": "python",
        ".go": "go",
        ".sql": "sql",
        ".css": "css",
        **{s: "c" for s in C_SUFFIXES},
        **{s: "html" for s in HTML_SUFFIXES},
    }.get(path.suffix)


def line_starts(src: str) -> list[int]:
    starts = [0]
    for i, ch in enumerate(src):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def make(path: str, src: str, starts: list[int], start: int, end: int) -> Comment:
    line = _line_of(starts, start)
    return Comment(path, line, _line_of(starts, end - 1), start, end, src[start:end])


def _line_of(starts: list[int], offset: int) -> int:
    lo, hi = 0, len(starts)
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if starts[mid] <= offset:
            lo = mid
        else:
            hi = mid
    return lo + 1


def scan_python(path: str, src: str) -> list[Comment]:
    starts = line_starts(src)
    found = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type != tokenize.COMMENT:
            continue
        row, col = tok.start
        if row <= 2 and (tok.string.startswith("#!") or "coding" in tok.string):
            continue
        if PY_PRAGMA.match(tok.string):
            continue
        start = starts[row - 1] + col
        found.append(make(path, src, starts, start, start + len(tok.string)))
    return found


def scan_c_like(path: str, src: str, line_comments: bool, quotes: str) -> list[tuple[int, int]]:
    spans, i, n = [], 0, len(src)
    while i < n:
        ch = src[i]
        if line_comments and src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            spans.append((i, j))
            i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            spans.append((i, j))
            i = j
        elif ch in quotes:
            j = i + 1
            while j < n and src[j] != ch:
                if src[j] == "\\":
                    j += 1
                elif src[j] == "\n" and ch != "`":
                    break
                j += 1
            i = j + 1
        else:
            i += 1
    return spans


def go_body_lines(src: str) -> set[int]:
    body, stack, parens, pending, line, i, n = set(), [], 0, False, 1, 0, len(src)
    while i < n:
        ch = src[i]
        if stack and stack[-1]:
            body.add(line)
        if ch == "\n":
            if pending and parens == 0:
                pending = False
            line += 1
        elif src.startswith("//", i):
            i = src.find("\n", i) - 1 if src.find("\n", i) >= 0 else n
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            line += src.count("\n", i, j)
            i = j - 1
        elif ch in "\"'`":
            j = i + 1
            while j < n and src[j] != ch:
                if src[j] == "\\" and ch != "`":
                    j += 1
                elif src[j] == "\n" and ch != "`":
                    break
                j += 1
            line += src.count("\n", i, j) if ch == "`" else 0
            i = j
        elif src.startswith("func", i) and not (src[i - 1:i].isalnum() or src[i + 4:i + 5].isalnum()):
            pending = True
            i += 3
        elif ch == "(":
            parens += 1
        elif ch == ")":
            parens -= 1
        elif ch == "{":
            type_literal = parens > 0 or re.search(r"\b(interface|struct)\s*$", src[max(0, i - 12):i])
            stack.append(bool(stack and stack[-1]) or (pending and not type_literal))
            if not type_literal:
                pending = False
        elif ch == "}" and stack:
            stack.pop()
        i += 1
    return body


def scan_go(path: str, src: str) -> list[Comment]:
    if GO_GENERATED.search(src):
        return []
    starts = line_starts(src)
    lines = src.split("\n")
    body = go_body_lines(src)
    found = []
    for start, end in scan_c_like(path, src, True, "\"'`"):
        text = src[start:end]
        if GO_DIRECTIVE.match(text):
            continue
        line = _line_of(starts, start)
        if not lines[line - 1][: start - starts[line - 1]].strip() and line not in body:
            nxt = _line_of(starts, end - 1)
            while nxt < len(lines) and lines[nxt].lstrip().startswith("//"):
                nxt += 1
            code = lines[nxt] if nxt < len(lines) else ""
            if code.strip() and not code.lstrip().startswith("}"):
                if start == starts[line - 1] and not code[:1].isspace():
                    continue
                name = re.match(r"\s*([A-Za-z_]\w*)", code)
                head = line
                while head > 1 and lines[head - 2].lstrip().startswith("//"):
                    head -= 1
                first = re.match(r"\s*//\s*([A-Za-z_]\w*)", lines[head - 1])
                if name and first and name.group(1) == first.group(1):
                    continue
        found.append(make(path, src, starts, start, end))
    return found


def scan_sql(path: str, src: str) -> list[Comment]:
    if re.search(r"^\s*--\s*name:", src, re.M):
        return []
    starts = line_starts(src)
    found, i, n = [], 0, len(src)
    while i < n:
        if src.startswith("--", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            if not SQL_DIRECTIVE.match(src[i:j]):
                found.append(make(path, src, starts, i, j))
            i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            found.append(make(path, src, starts, i, j))
            i = j
        elif src[i] == "'":
            j = src.find("'", i + 1)
            while j >= 0 and src.startswith("''", j):
                j = src.find("'", j + 2)
            i = n if j < 0 else j + 1
        else:
            i += 1
    return found


def scan_hash(path: str, src: str) -> list[Comment]:
    starts = line_starts(src)
    is_make = Path(path).name == "Makefile" or path.endswith(".mk")
    found = []
    for k, text in enumerate(src.split("\n")):
        quote, prev = None, " "
        for col, ch in enumerate(text):
            if quote:
                if ch == quote:
                    quote = None
            elif ch in "\"'":
                quote = ch
            elif ch == "#" and (prev.isspace() or col == 0):
                comment = text[col:]
                if k == 0 and HASH_DIRECTIVE.match(comment):
                    break
                if HASH_DIRECTIVE.match(comment) and not comment.startswith("#!"):
                    break
                if is_make and comment.startswith("## ") and col > 0:
                    break
                start = starts[k] + col
                found.append(make(path, src, starts, start, start + len(comment)))
                break
            prev = ch
    return found


def scan_html(path: str, src: str) -> list[Comment]:
    starts = line_starts(src)
    found = []
    for match in re.finditer(r"<!--.*?-->|\{#.*?#\}", src, re.S):
        if re.match(r"<!--\[if|<!\[endif\]", match.group(0)):
            continue
        found.append(make(path, src, starts, match.start(), match.end()))
    return found


def scan(path: Path, allow: list[re.Pattern] = ()) -> list[Comment]:
    return [c for c in _scan(path) if not any(a.match(c.text) for a in allow)]


def _scan(path: Path) -> list[Comment]:
    lang = language(path)
    if lang is None:
        return []
    src = path.read_text(encoding="utf-8", errors="replace")
    rel = path.as_posix()
    if lang == "python":
        return scan_python(rel, src)
    if lang == "go":
        return scan_go(rel, src)
    if lang == "sql":
        return scan_sql(rel, src)
    if lang == "hash":
        return scan_hash(rel, src)
    if lang == "html":
        return scan_html(rel, src)
    starts = line_starts(src)
    spans = scan_c_like(rel, src, lang == "c", "\"'`" if lang == "c" else "\"'")
    comments = [make(rel, src, starts, s, e) for s, e in spans]
    return [c for c in comments if not JS_DIRECTIVE.match(c.text)]


def tracked_files(paths: list[str]) -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", *paths],
        check=True, capture_output=True, text=True,
    ).stdout
    return sorted(Path(p) for p in out.split("\0") if p and Path(p).is_file())


def count_lines(comments: list[Comment]) -> int:
    lines = set()
    for c in comments:
        lines.update(range(c.line, c.end_line + 1))
    return len(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--update", action="store_true")
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    config = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
    allow = [re.compile(a) for a in config.get("allow", [])]
    files = tracked_files(args.paths)
    found = {f.as_posix(): scan(f, allow) for f in files}
    found = {f: c for f, c in found.items() if c}

    if args.json:
        json.dump([asdict(c) for cs in found.values() for c in cs], sys.stdout, indent=1, ensure_ascii=False)
        return 0
    if args.list:
        for cs in found.values():
            for c in cs:
                print(f"{c.path}:{c.line}: {c.text.splitlines()[0]}")
        return 0

    current = {f: count_lines(c) for f, c in sorted(found.items())}
    baseline = config.get("files", {})

    if args.init or args.update:
        raised = {f: n for f, n in current.items() if n > baseline.get(f, 0)}
        if args.update and raised:
            for f, n in raised.items():
                print(f"{f}: {n} comment lines, baseline allows {baseline.get(f, 0)}; delete them instead")
            return 1
        config = {"version": 1, "allow": config.get("allow", []), "files": current}
        BASELINE.write_text(json.dumps(config, indent=2) + "\n")
        print(f"{BASELINE}: {sum(current.values())} comment lines in {len(current)} files")
        return 0

    raised = [f"{f}: {n} comment lines, baseline allows {baseline.get(f, 0)}"
              for f, n in current.items() if n > baseline.get(f, 0)]
    stale = [f"{f}: baseline allows {n}, file has {current.get(f, 0)}; run --update to lower it"
             for f, n in baseline.items() if current.get(f, 0) < n]
    for line in raised + stale:
        print(line)
    if raised:
        print("New comments are not allowed. Put the reason in docs/adr/, a name, a test or a docstring.")
    if raised or stale:
        return 1
    print(f"comment ratchet: {sum(current.values())} comment lines left in {len(current)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
