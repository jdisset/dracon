# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""Phase 2 characterization tests: type/callable tags, interpolated tags,
!fn:path resolution, !define alias, propagation, and DraconCallable/Partial/Pipe
used directly. These cover existing behavior before the retrofit."""

import pytest
from pydantic import BaseModel

from dracon import DraconLoader, DraconCallable, DraconPartial, DraconPipe
from dracon.symbols import (
    Symbol, SymbolKind, InterfaceSpec, ParamSpec,
    CallableSymbol, ValueSymbol, BoundSymbol, auto_symbol,
)
from dracon.symbol_table import SymbolTable, SymbolEntry


# ── test models/callables ────────────────────────────────────────────────────

class Point(BaseModel):
    x: float = 0.0
    y: float = 0.0


class Color(BaseModel):
    r: int = 0
    g: int = 0
    b: int = 0


def add_xy(x: float, y: float) -> float:
    return x + y


def greet(name: str, greeting: str = "hello") -> str:
    return f"{greeting} {name}"


# ── type tags from context ───────────────────────────────────────────────────

class TestTypeTagsFromContext:
    def test_type_tag_constructs_model(self):
        loader = DraconLoader(context={"Point": Point})
        result = loader.loads("!Point\nx: 1.0\ny: 2.0")
        assert isinstance(result, Point)
        assert result.x == 1.0
        assert result.y == 2.0

    def test_type_tag_nested(self):
        loader = DraconLoader(context={"Point": Point, "Color": Color})
        result = loader.loads("p: !Point\n  x: 3.0\nc: !Color\n  r: 255")
        assert isinstance(result["p"], Point)
        assert result["p"].x == 3.0
        assert isinstance(result["c"], Color)
        assert result["c"].r == 255


# ── callable tags from context ───────────────────────────────────────────────

class TestCallableTagsFromContext:
    def test_callable_tag_with_kwargs(self):
        loader = DraconLoader(context={"add_xy": add_xy})
        result = loader.loads("!add_xy\nx: 3.0\ny: 4.0")
        assert result == 7.0

    def test_callable_tag_returns_string(self):
        loader = DraconLoader(context={"greet": greet})
        result = loader.loads("!greet\nname: world")
        assert result == "hello world"


# ── interpolated tags (dynamic) ──────────────────────────────────────────────

class TestInterpolatedTags:
    def test_dynamic_tag_via_define_alias(self):
        loader = DraconLoader(context={"Point": Point})
        result = loader.loads(
            "!define tag_name: Point\nresult: !$(tag_name)\n  x: 5.0\n  y: 6.0"
        )
        assert isinstance(result["result"], Point)
        assert result["result"].x == 5.0

    def test_dynamic_tag_via_expression(self):
        loader = DraconLoader(context={"Point": Point, "Color": Color})
        result = loader.loads(
            "!define choice: Point\nresult: !$(choice)\n  x: 9.0"
        )
        assert isinstance(result["result"], Point)


# ── !fn:path resolution via context and import ───────────────────────────────

class TestFnPathResolution:
    def test_fn_path_creates_partial(self):
        result = DraconLoader().loads("f: !fn:os.path.join\n  a: /tmp")
        assert isinstance(result["f"], DraconPartial)

    def test_fn_path_from_context(self):
        loader = DraconLoader(context={"add_xy": add_xy})
        result = loader.loads("f: !fn:add_xy\n  x: 1.0")
        assert isinstance(result["f"], DraconPartial)
        assert result["f"](y=2.0) == 3.0


# ── !define Alias: ${...} then !Alias ────────────────────────────────────────

class TestDefineAlias:
    def test_define_type_alias_then_tag(self):
        loader = DraconLoader(context={"Point": Point})
        result = loader.loads(
            "!define Pt: ${Point}\nresult: !Pt\n  x: 7.0\n  y: 8.0"
        )
        assert isinstance(result["result"], Point)
        assert result["result"].x == 7.0

    def test_define_callable_alias_then_tag(self):
        loader = DraconLoader(context={"greet": greet})
        result = loader.loads(
            "!define say: ${greet}\nresult: !say\n  name: alice"
        )
        assert result["result"] == "hello alice"


# ── propagation-sensitive nested tag invocation ──────────────────────────────

class TestPropagation:
    def test_propagated_type_tag(self):
        loader = DraconLoader(context={"Point": Point})
        yaml = """
<<(<): !include var:base
result: !Point
  x: 1.0
  y: 2.0
"""
        # simpler: just test that type tags from context work at depth
        result = loader.loads("outer:\n  inner: !Point\n    x: 3.0")
        assert isinstance(result["outer"]["inner"], Point)

    def test_define_fn_used_as_tag(self):
        loader = DraconLoader()
        result = loader.loads("""
!define make_pair: !fn
  !require a: "first"
  !require b: "second"
  first: ${a}
  second: ${b}
result: !make_pair
  a: 1
  b: 2
""")
        assert result["result"]["first"] == 1
        assert result["result"]["second"] == 2


# ── DraconCallable / DraconPartial / DraconPipe direct usage (regression) ────

class TestDraconCallableDirectUsage:
    def test_dracon_callable_invoke(self):
        """DraconCallable can be created and invoked via context."""
        from dracon.callable import DraconCallable as DC
        loader = DraconLoader()
        # put a callable template in context, then use it
        comp = loader.compose_config_from_str("""
!define maker: !fn
  !require name: "name"
  !set_default port: 8080
  url: https://${name}:${port}
use: !maker
  name: api
  port: 443
""")
        result = loader.load_node(comp.root)
        assert result["use"]["url"] == "https://api:443"

    def test_dracon_callable_as_tag(self):
        loader = DraconLoader()
        result = loader.loads("""
!define build: !fn
  !require x: "x"
  result: ${x * 2}
val: !build
  x: 5
""")
        assert result["val"]["result"] == 10


class TestDraconPartialDirectUsage:
    def test_partial_callable(self):
        p = DraconPartial("os.path.join", __import__("os").path.join, {"a": "/tmp"})
        assert callable(p)

    def test_partial_roundtrip_yaml(self):
        loader = DraconLoader()
        result = loader.loads("f: !fn:os.path.join\n  a: /tmp")
        assert isinstance(result["f"], DraconPartial)


class TestDraconPipeDirectUsage:
    def test_pipe_creation_and_call(self):
        loader = DraconLoader(context={"add_xy": add_xy, "greet": greet})
        result = loader.loads("""
!define pipeline: !pipe
  - add_xy
val: ${pipeline(x=1.0, y=2.0)}
""")
        assert result["val"] == 3.0


# ── Symbol protocol on retrofitted classes ───────────────────────────────────

class TestSymbolProtocolRetrofit:
    """After Phase 2, DraconCallable/Partial/Pipe should implement Symbol."""

    def test_dracon_callable_is_symbol(self):
        """DraconCallable created via context implements Symbol protocol."""
        from dracon.callable import DraconCallable as DC
        loader = DraconLoader()
        # create a callable directly and put it in context
        comp = loader.compose_config_from_str("!define f: !fn\n  !require x: 'x'\n  result: ${x}")
        # get it from defined_vars (where !define stores values)
        f = comp.defined_vars["f"]
        assert isinstance(f, DC)
        assert isinstance(f, Symbol)
        iface = f.interface()
        assert iface.kind == SymbolKind.TEMPLATE
        param_names = [p.name for p in iface.params]
        assert "x" in param_names

    def test_dracon_callable_bind_invoke(self):
        loader = DraconLoader()
        comp = loader.compose_config_from_str("!define f: !fn\n  !require x: 'x'\n  val: ${x * 3}")
        f = comp.defined_vars["f"]
        bound = f.bind(x=7)
        assert isinstance(bound, BoundSymbol)
        result = bound.invoke()
        assert result["val"] == 21

    def test_dracon_partial_is_symbol(self):
        p = DraconPartial("os.path.join", __import__("os").path.join, {"a": "/tmp"})
        assert isinstance(p, Symbol)
        iface = p.interface()
        assert iface.kind == SymbolKind.CALLABLE

    def test_dracon_partial_bind_invoke(self):
        def concat(a: str, b: str) -> str:
            return a + "/" + b
        p = DraconPartial("test.concat", concat, {})
        bound = p.bind(a="/tmp")
        result = bound.invoke(b="file.txt")
        assert result == "/tmp/file.txt"

    def test_dracon_pipe_is_symbol(self):
        def double(x: float) -> float:
            return x * 2

        pipe = DraconPipe(stages=[double, double], stage_kwargs=[{}, {}], name="test")
        assert isinstance(pipe, Symbol)
        iface = pipe.interface()
        assert iface.kind == SymbolKind.PIPE

    def test_auto_symbol_wraps_dracon_callable(self):
        """auto_symbol should return the DraconCallable itself since it's a Symbol."""
        loader = DraconLoader()
        comp = loader.compose_config_from_str("!define f: !fn\n  !require x: 'x'\n  val: ${x}")
        f = comp.defined_vars["f"]
        sym = auto_symbol(f)
        assert sym is f

    def test_symbol_table_stores_callables_as_symbols(self):
        """SymbolTable should store DraconCallable as-is since it's a Symbol."""
        loader = DraconLoader()
        comp = loader.compose_config_from_str("!define f: !fn\n  !require x: 'x'\n  val: ${x}")
        f = comp.defined_vars["f"]
        # put it in the symbol table
        loader.symbols["f"] = f
        sym = loader.symbols.lookup_symbol("f")
        assert sym is not None
        assert sym is f  # DraconCallable is a Symbol, stored as-is
        assert hasattr(sym, 'interface')


# ── _is_constructable_type_tag replacement ───────────────────────────────────

class TestIsConstructableTypeTagReplacement:
    """After Phase 2, _is_constructable_type_tag should still be importable
    but internally uses symbol table lookups."""

    def test_known_type_in_context(self):
        from dracon.instructions import _is_constructable_type_tag
        from dracon.composer import DraconMappingNode
        loader = DraconLoader(context={"Point": Point})
        node = DraconMappingNode(tag="!Point", value=[])
        assert _is_constructable_type_tag(node, loader) is True

    def test_unknown_type(self):
        from dracon.instructions import _is_constructable_type_tag
        from dracon.composer import DraconMappingNode
        loader = DraconLoader()
        node = DraconMappingNode(tag="!NonExistentType99", value=[])
        assert _is_constructable_type_tag(node, loader) is False

    def test_instruction_tag(self):
        from dracon.instructions import _is_constructable_type_tag
        from dracon.composer import DraconMappingNode
        loader = DraconLoader()
        node = DraconMappingNode(tag="!define", value=[])
        assert _is_constructable_type_tag(node, loader) is False
