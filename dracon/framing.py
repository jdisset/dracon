# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""Line-framing utilities: dracon as a wire format.

Small, composable helpers that turn a dracon document into one line of
text suitable for JSONLines-style streams, log replay, IPC pipes, and
other stream-of-documents use cases.

- :func:`dump_line` quotes a value and emits a single newline-terminated
  flow-style YAML document.
- :func:`loads_line` parses a single line back, stripping surrounding
  whitespace and CRLF line endings.
- :func:`document_stream` iterates constructed documents from an async
  byte stream.
- :class:`NotLineableError` fires when a value can't be expressed on one
  line (e.g. a top-level literal scalar with an embedded newline).
"""

from __future__ import annotations

import asyncio
import io
from collections.abc import AsyncIterator, Mapping
from typing import Any

from ruamel.yaml import Node
from ruamel.yaml.nodes import MappingNode, SequenceNode

from dracon.diagnostics import DraconError
from dracon.loader import DraconLoader
from dracon.symbol_table import SymbolTable

__all__ = [
    "NotLineableError",
    "document_stream",
    "dump_line",
    "loads_line",
]


class NotLineableError(DraconError):
    """Raised when a value cannot be represented as a single line of YAML.

    Flow-style emission normally collapses to one line, but a value whose
    tree carries an unescapable block-style scalar (e.g. ``style='|'``
    with an embedded newline) produces multi-line output even in flow
    mode. Downstream wire protocols cannot silently corrupt the frame;
    this exception fires loudly instead.
    """


_DOC_END = "\n...\n"


def _flow_loader() -> DraconLoader:
    """Fresh loader configured for single-line flow-style emission.

    Intentionally not cached: the loader carries per-dump state (alias
    tracking, vocabulary binding) and reusing one across calls would
    leak. Construction is cheap.
    """
    loader = DraconLoader()
    loader.yaml.default_flow_style = True
    loader.yaml.representer.full_module_path = False
    return loader


def _bind_context(
    loader: DraconLoader, context: SymbolTable | Mapping[str, Any] | None
) -> None:
    if context is None:
        return
    if isinstance(context, SymbolTable):
        loader.context = context
    else:
        loader.context.update(dict(context))


def _force_flow(node: Node) -> None:
    """Recursively stamp ``flow_style=True`` on composite nodes.

    Needed because :meth:`DraconLoader.dump_to_node` may return a node
    tree built during load with ``flow_style=False`` baked in; ruamel
    honors the per-node setting and ignores ``default_flow_style`` for
    pre-built trees.
    """
    if isinstance(node, MappingNode):
        node.flow_style = True
        for k, v in node.value:
            _force_flow(k)
            _force_flow(v)
    elif isinstance(node, SequenceNode):
        node.flow_style = True
        for item in node.value:
            _force_flow(item)


def _emit_single_line(node: Node, loader: DraconLoader) -> str:
    """Emit ``node`` as flow YAML and collapse to single line, or fail."""
    _force_flow(node)
    buf = io.StringIO()
    loader.yaml.dump(node, buf)
    text = buf.getvalue()
    # ruamel marks bare-scalar documents with a trailing '...' end marker;
    # strip it so the output is a true single line.
    if text.endswith(_DOC_END):
        text = text[: -len(_DOC_END)]
    text = text.rstrip("\n")
    if "\n" in text:
        raise NotLineableError(
            f"value cannot be expressed on one line: produced multi-line flow output:\n{text!r}"
        )
    return text


def _quote(loader: DraconLoader, data: Any) -> Node:
    """Full vocabulary-aware quotation of ``data`` into a Node.

    Unlike :meth:`DraconLoader.dump_to_node`, this always routes through
    :meth:`DraconRepresenter.represent_data`, so wrapper types like
    :class:`DeferredNode` get their canonical tagging pass even when they
    are themselves ``Node`` instances.
    """
    representer = loader.yaml.representer
    prev_vocab = representer._vocabulary
    representer._vocabulary = loader.context
    try:
        return representer.represent_data(data)
    finally:
        representer._vocabulary = prev_vocab
        representer.represented_objects = {}
        representer.object_keeper = []
        representer.alias_key = None


def dump_line(
    data: Any,
    context: SymbolTable | Mapping[str, Any] | None = None,
) -> bytes:
    """Quote and emit ``data`` as a single newline-terminated YAML line.

    The output is flow-style YAML with a trailing ``\\n``. Suitable for
    line-delimited streams. Raises :class:`NotLineableError` if the value
    cannot be single-lined.
    """
    loader = _flow_loader()
    _bind_context(loader, context)
    text = _emit_single_line(_quote(loader, data), loader)
    return (text + "\n").encode("utf-8")


def loads_line(
    line: bytes | str,
    context: SymbolTable | Mapping[str, Any] | None = None,
) -> Any:
    """Parse one framed line back into a constructed value.

    Strips CRLF and surrounding whitespace. Empty lines return ``None``
    so streams can filter them out without special-casing.
    """
    if isinstance(line, bytes):
        line = line.decode("utf-8")
    stripped = line.strip()
    if not stripped:
        return None
    loader = DraconLoader()
    _bind_context(loader, context)
    return loader.loads(stripped)


async def _aiter_lines(
    reader: AsyncIterator[bytes] | asyncio.StreamReader,
) -> AsyncIterator[bytes]:
    """Normalise a StreamReader or generic AsyncIterator[bytes] to an iterator."""
    if hasattr(reader, "readline"):
        while True:
            raw = await reader.readline()  # type: ignore[union-attr]
            if not raw:
                return
            yield raw
    else:
        async for raw in reader:  # type: ignore[union-attr]
            yield raw


async def document_stream(
    reader: AsyncIterator[bytes] | asyncio.StreamReader,
    context: SymbolTable | Mapping[str, Any] | None = None,
) -> AsyncIterator[Any]:
    """Iterate typed documents from a byte stream of framed lines.

    Accepts either an :class:`asyncio.StreamReader` (uses ``readline``)
    or any ``AsyncIterator[bytes]`` yielding one frame per item. Empty
    lines are silently skipped; the iterator stops on EOF.
    """
    async for raw in _aiter_lines(reader):
        value = loads_line(raw, context=context)
        if value is not None:
            yield value
