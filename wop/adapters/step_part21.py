"""Read the DATA section of a STEP file (ISO 10303-21, "Part 21") into entities, without a library.

A STEP file is text: `#12 = CIRCLE ( 'NONE', #34, 5.0 ) ;`. This module only splits that text into records and
parameters; what the entities mean is read by `wop/adapters/step_files.py`. Parameters come back as Python values:
`Ref` for `#n`, `Enum` for `.T.`, float or int for numbers, str for strings, list for `( ... )`, `Typed` for a typed
value such as `LENGTH_MEASURE(0.01)`, None for `$` and `*`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


class Part21Error(ValueError):
    """The text is not a readable STEP file."""


@dataclass(frozen=True)
class Ref:
    id: int


@dataclass(frozen=True)
class Enum:
    name: str  # without the dots: "T", "F", "MILLI"


@dataclass(frozen=True)
class Typed:
    name: str
    args: list


@dataclass
class Entity:
    """One record. A simple record has one part; a complex record `( A() B() )` has several, in file order."""

    id: int
    parts: dict[str, list] = field(default_factory=dict)

    @property
    def name(self) -> str:
        """The type name of a simple record; the names joined by '+' for a complex one."""
        return "+".join(self.parts)

    @property
    def args(self) -> list:
        """The parameters of a simple record (of the first part of a complex one)."""
        return next(iter(self.parts.values()))

    def has(self, name: str) -> bool:
        return name in self.parts


_TOKEN = re.compile(
    r"""\s*(?:
        (?P<string>'(?:[^']|'')*')
      | (?P<ref>\#\d+)
      | (?P<enum>\.[A-Za-z_0-9]+\.)
      | (?P<number>[+-]?(?:\d+\.?\d*|\.\d+)(?:[Ee][+-]?\d+)?)
      | (?P<keyword>!?[A-Za-z_][A-Za-z_0-9]*)
      | (?P<binary>"[0-9A-Fa-f]*")
      | (?P<punct>[(),$*=])
    )""",
    re.VERBOSE,
)


def _tokens(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    position = 0
    end = len(text)
    while position < end:
        match = _TOKEN.match(text, position)
        if match is None:
            if text[position:].strip() == "":
                break
            raise Part21Error(f"cannot read the text near: {text[position:position + 40]!r}")
        kind = match.lastgroup or ""
        tokens.append((kind, match.group(kind)))
        position = match.end()
    return tokens


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self.tokens = tokens
        self.index = 0

    def peek(self) -> tuple[str, str]:
        return self.tokens[self.index] if self.index < len(self.tokens) else ("", "")

    def take(self, value: str | None = None) -> tuple[str, str]:
        token = self.peek()
        if value is not None and token[1] != value:
            raise Part21Error(f"expected {value!r}, found {token[1]!r}")
        self.index += 1
        return token

    def value(self):
        kind, text = self.take()
        if kind == "punct":
            if text == "(":
                return self.list_rest()
            if text in "$*":
                return None
            raise Part21Error(f"unexpected {text!r}")
        if kind == "ref":
            return Ref(int(text[1:]))
        if kind == "enum":
            return Enum(text[1:-1].upper())
        if kind == "number":
            return float(text) if any(c in text for c in ".Ee") else int(text)
        if kind == "string":
            return text[1:-1].replace("''", "'")
        if kind == "keyword":
            self.take("(")
            return Typed(text.upper(), self.list_rest())
        if kind == "binary":
            return text
        raise Part21Error("the record ends too early")

    def list_rest(self) -> list:
        """The values after an opening bracket up to its closing bracket."""
        values: list = []
        if self.peek()[1] == ")":
            self.take()
            return values
        while True:
            values.append(self.value())
            separator = self.take()[1]
            if separator == ")":
                return values
            if separator != ",":
                raise Part21Error(f"expected ',' or ')', found {separator!r}")


def _strip_comments(text: str) -> str:
    """Remove /* comments */ that are outside strings."""
    out: list[str] = []
    index, end, in_string = 0, len(text), False
    while index < end:
        char = text[index]
        if in_string:
            out.append(char)
            if char == "'":
                in_string = False  # a doubled '' closes and opens again: still correct
            index += 1
        elif char == "'":
            in_string = True
            out.append(char)
            index += 1
        elif text.startswith("/*", index):
            close = text.find("*/", index + 2)
            index = end if close < 0 else close + 2
        else:
            out.append(char)
            index += 1
    return "".join(out)


def _records(data: str) -> list[str]:
    """Split the DATA section at the semicolons that are outside strings."""
    records: list[str] = []
    start, in_string = 0, False
    for index, char in enumerate(data):
        if char == "'":
            in_string = not in_string
        elif char == ";" and not in_string:
            records.append(data[start:index])
            start = index + 1
    return [r for r in records if r.strip()]


def _record(text: str) -> Entity:
    parser = _Parser(_tokens(text))
    kind, ident = parser.take()
    if kind != "ref":
        raise Part21Error(f"a record must start with #number: {text.strip()[:40]!r}")
    parser.take("=")
    entity = Entity(int(ident[1:]))
    if parser.peek()[1] == "(":  # complex record: ( A(...) B(...) )
        parser.take()
        while parser.peek()[1] != ")":
            kind, name = parser.take()
            if kind != "keyword":
                raise Part21Error(f"expected a type name in record {ident}")
            parser.take("(")
            entity.parts[name.upper()] = parser.list_rest()
        parser.take()
    else:
        kind, name = parser.take()
        if kind != "keyword":
            raise Part21Error(f"expected a type name in record {ident}")
        parser.take("(")
        entity.parts[name.upper()] = parser.list_rest()
    return entity


def parse_part21(text: str) -> dict[int, Entity]:
    """The entities of the DATA section by number. Raises Part21Error."""
    text = _strip_comments(text)
    if "ISO-10303-21" not in text[:200].upper():
        raise Part21Error("this is not a STEP file (no ISO-10303-21 header)")
    match = re.search(r"\bDATA\b\s*(?:\([^;]*\))?\s*;", text)
    if match is None:
        raise Part21Error("the STEP file has no DATA section")
    end = re.search(r"\bENDSEC\s*;", text[match.end():])
    data = text[match.end(): match.end() + end.start()] if end else text[match.end():]
    entities: dict[int, Entity] = {}
    for record in _records(data):
        entity = _record(record)
        entities[entity.id] = entity
    return entities
