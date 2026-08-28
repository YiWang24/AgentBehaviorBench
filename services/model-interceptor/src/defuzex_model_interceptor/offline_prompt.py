"""Recover the reply contract an Agent stated in its prompt.

Some frameworks put the contract in the request, where it can simply be read.
Others — LangChain's output parsers above all — state it in the prompt and parse
the reply afterwards, so nothing in the request declares it and a canned sentence
makes the Agent's own parser raise.

Everything here reads only what the Agent itself wrote, and each recogniser
requires enough evidence that it cannot shadow a real declared contract.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping, Sequence

from .offline_schema import arguments_for

# Fixed text emitted by LangChain output parsers ahead of the schema block.
_SCHEMA_SENTINEL = "Here is the output schema"


_FENCED_JSON = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _prompt_text(payload: Mapping[str, Any]) -> str:
    """Concatenate the text the Agent put in front of the model."""

    parts: list[str] = []

    def walk(value: object) -> None:
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            for key in ("content", "text", "input", "messages", "system"):
                if key in value:
                    walk(value[key])

    for key in ("messages", "input", "system", "prompt"):
        if key in payload:
            walk(payload[key])
    return "\n".join(parts)


def _prompt_schema(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    """Recover a JSON schema that the Agent embedded in its prompt.

    LangChain's ``JsonOutputParser`` and ``PydanticOutputParser`` state the
    contract in the prompt rather than in the request: the model is told to emit
    JSON and the reply is parsed afterwards, so nothing in the request body
    declares it. Against a canned text reply those agents fail with
    ``OutputParserException``.

    The instructions those parsers generate are fixed text ending in a fenced
    block that holds the schema, so the schema can be recovered exactly rather
    than guessed. Anything that does not carry both the sentinel and a parsable
    schema object is left alone.
    """

    text = _prompt_text(payload)

    # Two shapes are recognised. LangChain's parsers emit the fixed
    # `_SCHEMA_SENTINEL` sentence followed by a fenced block. Other agents label
    # the schema with a bracketed marker such as `[OUTPUT_SCHEMA]` and follow it
    # with a bare JSON object. In both cases the schema object appears right
    # after the marker, so it can be recovered exactly rather than guessed.
    marker = text.rfind(_SCHEMA_SENTINEL)
    if marker != -1:
        fenced = _FENCED_JSON.search(text, marker)
        if fenced is not None:
            schema = _load_schema(fenced.group(1))
            if schema is not None:
                return schema

    label = _SCHEMA_LABEL.search(text)
    if label is not None:
        for _, _, obj in _json_objects(text[label.end():]):
            if isinstance(obj.get("properties"), dict) or "$defs" in obj or "$ref" in obj:
                return obj

    return None


# A schema block is often introduced by a short label — either bracketed
# (`[OUTPUT_SCHEMA]`) or a phrase ending in a colon (`JSON schema:`). Either way
# the schema object follows immediately, so the marker just locates it.
_SCHEMA_LABEL = re.compile(
    r"(?:\[\s*(?:output[_ ]?schema|json[_ ]?schema|response[_ ]?schema|schema)\s*\]"
    r"|(?:output[_ ]?schema|json[_ ]?schema|response[_ ]?schema)\s*[:：])",
    re.IGNORECASE,
)


def _load_schema(raw: str) -> dict[str, Any] | None:
    try:
        schema = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(schema, dict) and isinstance(schema.get("properties"), dict):
        return schema
    return None


def _structured_content(payload: Mapping[str, Any]) -> str | None:
    """Honour a requested JSON response format so parsing on the Agent side works."""

    response_format = payload.get("response_format")
    if not isinstance(response_format, dict):
        return None
    schema = response_format.get("json_schema")
    if isinstance(schema, dict):
        schema = schema.get("schema", schema)
        return json.dumps(arguments_for(schema), ensure_ascii=False)

    if response_format.get("type") == "json_object":
        # `json_object` mode says a JSON reply is wanted but not which one, so
        # the request alone cannot describe the shape. The prompt is then the
        # only place the Agent stated its contract; an empty object parses but
        # is missing every field the Agent is about to read.
        #
        # A schema stated in the prompt (`[OUTPUT_SCHEMA]`, a fenced LangChain
        # block) is preferred over a bare example, and is synthesised into an
        # *instance* — returning the schema object verbatim would hand the
        # Agent its own contract instead of a value matching it.
        prompt_schema = _prompt_schema(payload)
        if prompt_schema is not None:
            return json.dumps(arguments_for(prompt_schema), ensure_ascii=False)
        example = _prompt_example(payload, require_free_turn=False)
        if example is not None:
            return json.dumps(example, ensure_ascii=False)
        # Nothing stated the shape, but the Agent still asked for JSON, so an
        # empty object at least parses.
        return "{}"

    # Any other `response_format` — `{"type": "text"}` above all — asks for no
    # JSON at all, so the caller falls back to the ordinary text reply.
    return None


def _json_objects(text: str) -> list[tuple[int, int, dict[str, Any]]]:
    """Every balanced `{...}` region in `text` that parses as a JSON object.

    Each entry carries the half-open ``(start, end)`` span the region occupied in
    `text`, so callers can rank examples by where they appear in the prompt and
    exclude the source text an object was already recovered from.
    """

    found: list[tuple[int, int, dict[str, Any]]] = []
    depth = 0
    start = -1
    for index, character in enumerate(text):
        if character == "{":
            if depth == 0:
                start = index
            depth += 1
        elif character == "}" and depth:
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    parsed = json.loads(text[start : index + 1])
                except json.JSONDecodeError:
                    pass
                else:
                    if isinstance(parsed, dict):
                        found.append((start, index + 1, parsed))
                start = -1
    return found


def _prompt_example(
    payload: Mapping[str, Any], *, require_free_turn: bool = True
) -> dict[str, Any] | None:
    """Recover a reply template the Agent wrote into its own prompt.

    Many agents state their contract by example rather than by schema — "return
    JSON in this shape", followed by a literal object — and then parse the reply
    themselves. Nothing in the request declares it, so a canned sentence makes
    the agent's own parser fail, often on a path that loops or aborts.

    Three conditions must all hold, so this cannot shadow a real contract: the
    prompt asks for JSON, it contains a parseable object with more than one key,
    and the request declares neither tools nor a response format. The example is
    returned as written — it is exactly what the Agent said a good reply looks
    like, including any flags it set to keep a loop from running again.

    `require_free_turn` relaxes the last condition for `json_object` mode,
    where a response format is declared but carries no schema.
    """

    text = _prompt_text(payload)
    if "json" not in text.lower():
        return None
    braced = [entry for entry in _json_objects(text) if len(entry[2]) > 1]
    if require_free_turn:
        return braced[-1][2] if braced else None

    # In `json_object` mode the prompt often carries two kinds of object: work
    # quoted back from an earlier turn, and the contract for *this* reply.
    # Prompts state the contract last, immediately before the model answers, so
    # the latest example wins — including one written without its enclosing
    # braces, which is common:
    #
    #     you must provide your response in the following json format:
    #         "next_agent": "one of planner/selector/reporter"
    candidates = [(start, obj) for start, _, obj in braced]
    loose = _brace_less_example(
        text, exclude=[(start, end) for start, end, _ in braced]
    )
    if loose is not None:
        candidates.append(loose)
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


_PAIR = re.compile(r'"([A-Za-z_][A-Za-z0-9_ -]*)"\s*:\s*("(?:[^"\\]|\\.)*"|true|false|null|-?\d+(?:\.\d+)?)')


def _brace_less_example(
    text: str, *, exclude: Sequence[tuple[int, int]] = ()
) -> tuple[int, dict[str, Any]] | None:
    """Recover `"key": value` pairs written without enclosing braces.

    Pairs inside a region already recognised as a braced object are skipped,
    so an object quoted from an earlier turn is not double-counted. Returns the
    offset of the first surviving pair alongside the recovered object, so the
    caller can rank it against braced candidates by position.
    """

    recovered: dict[str, Any] = {}
    offset = -1
    for match in _PAIR.finditer(text):
        start = match.start()
        if any(low <= start < high for low, high in exclude):
            continue
        try:
            value = json.loads(match.group(2))
        except json.JSONDecodeError:
            continue
        if offset < 0:
            offset = start
        recovered[match.group(1)] = value
    if not recovered:
        return None
    return offset, recovered


def _prompt_schema_content(payload: Mapping[str, Any]) -> str | None:
    """Answer a contract the Agent stated in its prompt rather than its request.

    Ranked below a declared tool: an Agent that bound tools is waiting for a
    tool call, and a parser contract only applies to a free-text turn.
    """

    schema = _prompt_schema(payload)
    if schema is not None:
        return json.dumps(arguments_for(schema), ensure_ascii=False)

    example = _prompt_example(payload)
    if example is not None:
        return json.dumps(example, ensure_ascii=False)
    return None


def reply_text(payload: Mapping[str, Any]) -> str | None:
    """Content for a turn that answers in text rather than by calling a tool.

    Only reached once a tool call has been ruled out. Every protocol ranks the
    two the same way: an Agent that bound tools is waiting for a tool call, and a
    schema — declared in the request or stated in the prompt — describes the
    answer it wants after that.
    """

    return _structured_content(payload) or _prompt_schema_content(payload)


__all__ = ["reply_text"]
