# Step 2 regression suite: unified CallableSymbol covers plain / template /
# partial / pipe via factory methods + strategy registry. Asserts the public
# Symbol-protocol contract, not concrete-class identity.

from __future__ import annotations

import math
import pickle

import pytest

from dracon import DraconLoader, dump
from dracon.symbols import (
    CallableSymbol, BoundSymbol, SymbolKind, auto_symbol,
)


def add(a: int, b: int) -> int:
    return a + b


def double(x):
    return x * 2


def _make_template(loader, body, name="mk"):
    """Wrap a raw YAML body as a template-kind CallableSymbol.

    Uses the low-level compose path so !require declarations are kept in the
    node tree -- they will be processed at invoke time when kwargs supply the
    required values.
    """
    from dracon.loader import compose_config_from_str
    comp = compose_config_from_str(loader.yaml, body)
    return CallableSymbol.from_template(comp.root, loader, name=name)


# ── one class for the whole family ───────────────────────────────────────────

class TestUnifiedClass:
    def test_plain_constructor_unchanged(self):
        sym = CallableSymbol(add, name="add")
        assert isinstance(sym, CallableSymbol)
        assert sym.interface().kind in (SymbolKind.CALLABLE, SymbolKind.TYPE)
        assert sym.invoke(a=1, b=2) == 3

    def test_factory_partial(self):
        sym = CallableSymbol.from_partial("__main__.add", add, {"a": 4})
        assert isinstance(sym, CallableSymbol)
        assert sym.invoke(b=5) == 9

    def test_factory_partial_carries_kwargs(self):
        sym = CallableSymbol.from_partial("__main__.add", add, {"a": 10})
        assert sym.invoke(b=5) == 15

    def test_factory_pipe(self):
        sym = CallableSymbol.from_pipe(
            stages=[double], stage_kwargs=[{}], name="d",
        )
        assert isinstance(sym, CallableSymbol)
        assert sym.interface().kind == SymbolKind.PIPE
        assert sym.invoke(x=3) == 6

    def test_factory_template(self):
        loader = DraconLoader()
        result = loader.loads("""
!define mk: !fn
  !require x: "x"
  out: ${x * 2}
val: !mk
  x: 7
""")
        assert result["val"]["out"] == 14

    def test_template_factory_direct_construction(self):
        loader = DraconLoader()
        sym = _make_template(loader, """
!require x: "x"
out: ${x * 2}
""")
        assert isinstance(sym, CallableSymbol)
        assert sym.interface().kind == SymbolKind.TEMPLATE
        result = sym.invoke(x=4)
        assert result["out"] == 8


# ── pickle / deepcopy parity (explicit risk areas) ───────────────────────────

class TestPicklingDeepcopy:
    def test_partial_pickles(self):
        # callable must be importable for unpickle to round-trip
        sym = CallableSymbol.from_partial("os.path.join", __import__("os").path.join, {"a": "/tmp"})
        loaded = pickle.loads(pickle.dumps(sym))
        assert isinstance(loaded, CallableSymbol)

    def test_partial_deepcopies(self):
        from copy import deepcopy
        sym = CallableSymbol.from_partial(
            "__main__.add", add, {"a": 10},
        )
        clone = deepcopy(sym)
        assert isinstance(clone, CallableSymbol)
        assert clone.invoke(b=5) == 15

    def test_pipe_deepcopies(self):
        from copy import deepcopy
        sym = CallableSymbol.from_pipe(
            stages=[double], stage_kwargs=[{}], name="d",
        )
        clone = deepcopy(sym)
        assert isinstance(clone, CallableSymbol)
        assert clone.invoke(x=3) == 6

    def test_template_deepcopies(self):
        from copy import deepcopy
        loader = DraconLoader()
        sym = _make_template(loader, """
!require x: "x"
out: ${x * 2}
""")
        clone = deepcopy(sym)
        assert isinstance(clone, CallableSymbol)
        result = clone.invoke(x=5)
        assert result["out"] == 10


# ── dump tag preservation ────────────────────────────────────────────────────

class TestDumpTagPreservation:
    def test_partial_dump_tag(self):
        sym = CallableSymbol.from_partial("os.path.join", __import__("os").path.join, {"a": "/tmp"})
        text = dump(sym)
        assert "!fn:os.path.join" in text

    def test_template_dump_tag(self):
        loader = DraconLoader()
        sym = _make_template(loader, """
!require x: "x"
out: ${x}
""")
        text = dump(sym)
        assert "!fn:mk" in text or "!fn" in text

    def test_pipe_dump_tag(self):
        sym = CallableSymbol.from_pipe(
            stages=[double], stage_kwargs=[{}], name="d",
        )
        text = dump(sym)
        assert "!pipe" in text


# ── factory aliases preserved ────────────────────────────────────────────────

class TestFactoryAliases:
    def test_legacy_partial_alias_returns_callable_symbol(self):
        from dracon.partial import DraconPartial
        sym = DraconPartial("math.sqrt", math.sqrt, {})
        assert isinstance(sym, CallableSymbol)

    def test_legacy_pipe_alias_returns_callable_symbol(self):
        from dracon.pipe import DraconPipe
        sym = DraconPipe(stages=[double], stage_kwargs=[{}], name="d")
        assert isinstance(sym, CallableSymbol)

    def test_legacy_callable_alias_returns_callable_symbol(self):
        from dracon.callable import DraconCallable
        from dracon.loader import compose_config_from_str
        loader = DraconLoader()
        comp = compose_config_from_str(loader.yaml, """
!require x: "x"
out: ${x}
""")
        sym = DraconCallable(comp.root, loader, name="mk")
        assert isinstance(sym, CallableSymbol)


# ── BoundSymbol over template (declair-style nesting) ────────────────────────

class TestBoundOverTemplate:
    def test_bind_template_invoke(self):
        loader = DraconLoader()
        sym = _make_template(loader, """
!require x: "x"
!set_default y: 1
out: ${x + y}
""")
        bound = sym.bind(x=10)
        assert isinstance(bound, BoundSymbol)
        result = bound.invoke()
        assert result["out"] == 11
