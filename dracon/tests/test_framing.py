# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""Tests for line-framing utilities (v5 step 06).

Covers:
- ``dump_line`` / ``loads_line`` one-document-per-line framing
- ``document_stream`` async iteration over a byte stream
- ``NotLineableError`` guardrail when a value cannot be single-lined
- ``make_mapping_node`` / ``make_sequence_node`` / ``make_scalar_node``
  DraconDumpable construction helpers
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from dracon import DraconLoader
from dracon.deferred import DeferredNode, make_deferred
from dracon.framing import NotLineableError, document_stream, dump_line, loads_line
from dracon.nodes import (
    DEFAULT_MAP_TAG,
    DEFAULT_SCALAR_TAG,
    DEFAULT_SEQ_TAG,
    DraconMappingNode,
    DraconScalarNode,
    DraconSequenceNode,
    make_mapping_node,
    make_scalar_node,
    make_sequence_node,
)
from dracon.representer import DraconDumpable
from dracon.symbol_table import SymbolEntry, SymbolTable
from dracon.symbols import CallableSymbol


# ── shared fixtures ────────────────────────────────────────────────────────


class Point(BaseModel):
    x: int = 0
    y: int = 0


def _vocab() -> SymbolTable:
    tbl = SymbolTable()
    tbl.define(SymbolEntry(name="Point", symbol=CallableSymbol(Point, name="Point")))
    return tbl


# ── dump_line / loads_line ─────────────────────────────────────────────────


class TestDumpLine:
    def test_includes_terminating_newline(self):
        out = dump_line(42)
        assert out.endswith(b"\n")

    def test_output_is_single_line(self):
        assert dump_line(42).count(b"\n") == 1
        assert dump_line("hi").count(b"\n") == 1
        assert dump_line([1, 2, 3]).count(b"\n") == 1
        assert dump_line({"a": 1, "b": 2}).count(b"\n") == 1

    def test_round_trips_primitives(self):
        for v in [None, True, False, 0, 1, -1, 1.5, "hello", "with spaces"]:
            assert loads_line(dump_line(v)) == v

    def test_round_trips_sequence(self):
        assert loads_line(dump_line([1, 2, 3])) == [1, 2, 3]

    def test_round_trips_mapping(self):
        back = loads_line(dump_line({"a": 1, "b": 2}))
        assert dict(back) == {"a": 1, "b": 2}

    def test_round_trips_pydantic_model(self):
        vocab = _vocab()
        line = dump_line(Point(x=3, y=4), context=vocab)
        assert b"!Point" in line
        back = loads_line(line, context=vocab)
        assert back == Point(x=3, y=4)

    def test_round_trips_deferred_node(self):
        # a DeferredNode carries a node tree; it should survive line framing
        deferred = make_deferred(value={"answer": 42})
        assert isinstance(deferred, DeferredNode)
        line = dump_line(deferred)
        assert line.endswith(b"\n")
        back = loads_line(line)
        assert isinstance(back, DeferredNode)

    def test_raises_not_lineable_on_multi_line_output(self):
        # a top-level block-style literal scalar forces multi-line output
        literal = DraconScalarNode(
            tag=DEFAULT_SCALAR_TAG, value="hello\nworld", style="|"
        )
        with pytest.raises(NotLineableError):
            dump_line(literal)


class TestLoadsLine:
    def test_strips_newline_and_whitespace(self):
        assert loads_line(b"42\n") == 42
        assert loads_line(b"42\r\n") == 42
        assert loads_line(b"  42  \n") == 42
        assert loads_line("42") == 42

    def test_handles_empty_line_as_none(self):
        # empty line = no YAML document; return None so streams can filter
        assert loads_line(b"") is None
        assert loads_line(b"   \n") is None


# ── document_stream ────────────────────────────────────────────────────────


async def _collect(reader):
    return [doc async for doc in document_stream(reader)]


class _AsyncBytes:
    """Minimal AsyncIterator[bytes] over an in-memory buffer."""

    def __init__(self, lines: list[bytes]):
        self._lines = lines
        self._idx = 0

    def __aiter__(self):
        return self

    async def __anext__(self) -> bytes:
        if self._idx >= len(self._lines):
            raise StopAsyncIteration
        line = self._lines[self._idx]
        self._idx += 1
        return line


class TestDocumentStream:
    def test_yields_all_documents(self):
        lines = [dump_line(1), dump_line("two"), dump_line([3, 4])]
        docs = asyncio.run(_collect(_AsyncBytes(lines)))
        assert docs == [1, "two", [3, 4]]

    def test_skips_empty_lines(self):
        lines = [dump_line(1), b"\n", dump_line(2), b"  \n", dump_line(3)]
        docs = asyncio.run(_collect(_AsyncBytes(lines)))
        assert docs == [1, 2, 3]

    def test_stops_on_eof(self):
        lines = [dump_line(1)]
        docs = asyncio.run(_collect(_AsyncBytes(lines)))
        assert docs == [1]

    def test_works_with_stream_reader(self):
        async def _run():
            reader = asyncio.StreamReader()
            payload = dump_line(1) + dump_line("two")
            reader.feed_data(payload)
            reader.feed_eof()
            return [doc async for doc in document_stream(reader)]

        assert asyncio.run(_run()) == [1, "two"]


# ── node constructor helpers ───────────────────────────────────────────────


class TestMakeNodeHelpers:
    def test_make_scalar_node_default_tag(self):
        node = make_scalar_node("hi")
        assert isinstance(node, DraconScalarNode)
        assert node.tag == DEFAULT_SCALAR_TAG
        assert node.value == "hi"

    def test_make_scalar_node_with_explicit_tag(self):
        node = make_scalar_node("x", tag="!MyScalar")
        assert node.tag == "!MyScalar"

    def test_make_sequence_node_default_tag(self):
        items = [make_scalar_node("a"), make_scalar_node("b")]
        node = make_sequence_node(items)
        assert isinstance(node, DraconSequenceNode)
        assert node.tag == DEFAULT_SEQ_TAG
        assert list(node.value) == items

    def test_make_sequence_node_flow_style(self):
        node = make_sequence_node([], flow_style=True)
        assert node.flow_style is True

    def test_make_mapping_node_default_tag(self):
        pairs = [(make_scalar_node("k"), make_scalar_node("v"))]
        node = make_mapping_node(pairs)
        assert isinstance(node, DraconMappingNode)
        assert node.tag == DEFAULT_MAP_TAG
        assert len(node.value) == 1

    def test_make_mapping_node_explicit_tag(self):
        pairs = [(make_scalar_node("k"), make_scalar_node("v"))]
        node = make_mapping_node(pairs, tag="!Custom")
        assert node.tag == "!Custom"

    def test_helpers_power_dracon_dumpable(self):
        # a DraconDumpable implementation can build its node tree via
        # the helpers without touching ruamel details directly
        class Tagged(DraconDumpable):
            def __init__(self, name: str, value: int):
                self.name = name
                self.value = value

            def dracon_dump_to_node(self, representer):
                return make_mapping_node(
                    [
                        (make_scalar_node("name"), make_scalar_node(self.name)),
                        (make_scalar_node("value"), make_scalar_node(str(self.value))),
                    ],
                    tag="!Tagged",
                )

        loader = DraconLoader()
        text = loader.dump(Tagged("hello", 7))
        assert "!Tagged" in text
        assert "hello" in text
        assert "7" in text
