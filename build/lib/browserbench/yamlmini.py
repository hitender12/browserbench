"""A minimal YAML-subset parser (stdlib only).

Supported, and nothing more:
- mappings keyed by ``name: value`` with indentation-based nesting
- block sequences (``- item``), including sequences of mappings
- scalars: plain strings, single/double-quoted strings, ints, floats,
  booleans (true/false), null (~ / null / empty value)
- ``#`` comments and blank lines

This exists so task definitions can be authored in YAML without pulling
in PyYAML. Anything outside this subset raises ``YamlMiniError`` with a
clear message; authors should use JSON for complex specs.
"""

from __future__ import annotations


class YamlMiniError(ValueError):
    pass


def _scalar(text: str):
    text = text.strip()
    if text == "" or text in ("~", "null", "Null", "NULL"):
        return None
    if text in ("true", "True", "TRUE"):
        return True
    if text in ("false", "False", "FALSE"):
        return False
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text[1:-1]
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def _strip_comment(line: str) -> str:
    # A '#' starts a comment only when preceded by whitespace (or at line start),
    # so values like "http://x/#frag" survive.
    for i, ch in enumerate(line):
        if ch == "#" and (i == 0 or line[i - 1] in (" ", "\t")):
            return line[:i].rstrip()
    return line.rstrip()


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def parse(text: str):
    """Parse a YAML-subset document into Python data."""
    lines = []
    for raw in text.splitlines():
        stripped = _strip_comment(raw)
        if not stripped.strip():
            continue
        lines.append((len(stripped) - len(stripped.lstrip(" ")), stripped.strip()))
    if not lines:
        return None
    value, consumed = _parse_block(lines, 0, lines[0][0])
    if consumed != len(lines):
        raise YamlMiniError(f"unexpected content at line {consumed + 1}: {lines[consumed][1]!r}")
    return value


def _parse_block(lines, start, indent):
    """Parse one block (mapping or sequence) starting at `start`."""
    if lines[start][1].startswith("- ") or lines[start][1] == "-":
        return _parse_sequence(lines, start, indent)
    return _parse_mapping(lines, start, indent)


def _parse_sequence(lines, start, indent):
    items = []
    i = start
    while i < len(lines):
        line_indent, content = lines[i]
        if line_indent != indent or not (content.startswith("- ") or content == "-"):
            break
        if content == "-":
            items.append(None)
            i += 1
            continue
        after_dash = content[2:]
        dash_col = indent + 2
        if ":" in after_dash and not after_dash.startswith(('"', "'")):
            # "- key: value" — a mapping whose first pair is inline.
            sub = [(dash_col, after_dash)] + lines[i + 1:]
            value, consumed = _parse_mapping(sub, 0, dash_col)
            items.append(value)
            i += consumed
        else:
            items.append(_scalar(after_dash))
            i += 1
    return items, i - start


def _parse_mapping(lines, start, indent):
    result = {}
    i = start
    while i < len(lines):
        line_indent, content = lines[i]
        if line_indent != indent:
            break
        if content.startswith("- "):
            break
        if ":" not in content:
            raise YamlMiniError(f"expected 'key: value' at line {i + 1}: {content!r}")
        key, _, rest = content.partition(":")
        key = key.strip()
        rest = rest.strip()
        if not key:
            raise YamlMiniError(f"empty key at line {i + 1}")
        if rest == "":
            # Nested block on the following lines, or an empty value.
            if i + 1 < len(lines) and lines[i + 1][0] > indent:
                value, consumed = _parse_block(lines, i + 1, lines[i + 1][0])
                result[key] = value
                i += consumed + 1  # +1 for the key line itself
            else:
                result[key] = None
                i += 1
        else:
            result[key] = _scalar(rest)
            i += 1
    return result, i - start


def load_file(path: str):
    with open(path, "r", encoding="utf-8") as fh:
        return parse(fh.read())
