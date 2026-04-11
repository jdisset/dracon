"""Tests for dump_to_node as a first-class public API (step 04).

Covers:
- loader.dump_to_node() uses the loader's own context and representer (bug fix)
- loader.dump() and loader.dump_to_node() use the same representer instance
- top-level dump_to_node() accepts context kwarg
- dump_to_node is idempotent on existing Node inputs
- dump(value) equals emit(dump_to_node(value))
"""

from io import StringIO

import pytest
from pydantic import BaseModel
from ruamel.yaml import Node

from dracon import DraconLoader, dump, dump_to_node
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


# --- bug fix regression ---


def test_loader_dump_to_node_uses_loader_context():
    """Regression: DraconLoader.dump_to_node() used to discard loader context."""
    loader = DraconLoader()
    loader.context = _vocab(Gadget=Widget)
    node = loader.dump_to_node(Widget(name="x"))
    assert isinstance(node, Node)
    assert node.tag == '!Gadget'


def test_loader_dump_and_dump_to_node_share_representer_behavior():
    """Both methods must emit the same tag for the same input."""
    loader = DraconLoader()
    loader.context = _vocab(Thing=Widget)
    text = loader.dump(Widget(name="y"))
    node = loader.dump_to_node(Widget(name="y"))
    assert '!Thing' in text
    assert node.tag == '!Thing'


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
