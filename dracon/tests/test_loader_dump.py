"""Tests for dump_to_node as a first-class public API (step 04).

Bug-fix regressions live in test_roundtrip_property.py; this file covers
the first-class API shape.
"""

from io import StringIO

from pydantic import BaseModel
from ruamel.yaml import Node

from dracon import DraconLoader, dump_to_node
from dracon.symbol_table import SymbolEntry, SymbolTable
from dracon.symbols import CallableSymbol


class Widget(BaseModel):
    name: str
    value: int = 0


def _vocab(**entries) -> SymbolTable:
    tbl = SymbolTable()
    for name, value in entries.items():
        tbl.define(SymbolEntry(name=name, symbol=CallableSymbol(value, name=name)))
    return tbl


def test_loader_dump_to_node_respects_full_module_path_fallback():
    loader = DraconLoader()
    loader.yaml.representer.full_module_path = False
    node = loader.dump_to_node(Widget(name="z"))
    assert node.tag == '!Widget'


# --- first-class API ---


def test_dump_to_node_returns_node():
    node = dump_to_node(Widget(name="a"))
    assert isinstance(node, Node)


def test_dump_to_node_uses_vocabulary_from_context_kwarg():
    tbl = _vocab(Shortname=Widget)
    node = dump_to_node(Widget(name="b"), context=tbl)
    assert node.tag == '!Shortname'


def test_dump_to_node_without_vocabulary_falls_back_to_qualname():
    node = dump_to_node(Widget(name="c"))
    assert node.tag == f'!{Widget.__module__}.Widget'


def test_dump_to_node_idempotent_on_node_input():
    first = dump_to_node(Widget(name="d"))
    second = dump_to_node(first)
    assert second is first


def test_dump_equivalent_to_emit_of_dump_to_node():
    """dump(value) must equal yaml-emit(dump_to_node(value)) for the same loader."""
    loader = DraconLoader()
    loader.context = _vocab(Emitted=Widget)
    w = Widget(name="e", value=3)
    text = loader.dump(w)
    node = loader.dump_to_node(w)
    buf = StringIO()
    loader.yaml.dump(node, buf)
    assert text == buf.getvalue()


def test_top_level_dump_to_node_accepts_plain_dict_context():
    # dict context has no SymbolTable vocabulary semantics, but must not error
    node = dump_to_node(Widget(name="f"), context={'anything': 1})
    assert isinstance(node, Node)
