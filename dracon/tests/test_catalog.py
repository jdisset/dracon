# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""Tests for catalog, symbols CLI, __scope__, and error improvements."""

import json
import os
import tempfile
from pathlib import Path

import pytest
from pydantic import BaseModel

import dracon
from dracon import (
    DraconLoader,
    DraconCallable,
    DraconPartial,
    DraconPipe,
)
from dracon.symbols import (
    SymbolKind,
    InterfaceSpec,
    ValueSymbol,
    CallableSymbol,
    auto_symbol,
)
from dracon.symbol_table import SymbolEntry, SymbolTable

CONFIGS = Path(__file__).parent / "configs"


# ── SymbolTable query API ────────────────────────────────────────────────────


class TestSymbolTableQueryAPI:
    """SymbolTable.names(), .has(), .interface(), .kinds(), .exported()."""

    def _populated_table(self):
        t = SymbolTable()

        def my_fn(x, y=10):
            return x + y

        class MyType:
            pass

        t.define(SymbolEntry(name="count", symbol=ValueSymbol(42, name="count")))
        t.define(SymbolEntry(name="my_fn", symbol=CallableSymbol(my_fn, name="my_fn")))
        t.define(SymbolEntry(name="MyType", symbol=CallableSymbol(MyType, name="MyType")))
        t.define(SymbolEntry(name="priv", symbol=ValueSymbol("secret", name="priv"), exported=False))
        return t

    def test_names_all(self):
        t = self._populated_table()
        names = t.names()
        assert set(names) == {"count", "my_fn", "MyType", "priv"}

    def test_names_filtered_by_kind(self):
        t = self._populated_table()
        assert "count" in t.names(kind=SymbolKind.VALUE)
        assert "my_fn" in t.names(kind=SymbolKind.CALLABLE)
        assert "MyType" in t.names(kind=SymbolKind.TYPE)

    def test_names_filtered_returns_empty_for_missing_kind(self):
        t = self._populated_table()
        assert t.names(kind=SymbolKind.PIPE) == []

    def test_has(self):
        t = self._populated_table()
        assert t.has("count") is True
        assert t.has("nope") is False

    def test_interface(self):
        t = self._populated_table()
        iface = t.interface("my_fn")
        assert isinstance(iface, InterfaceSpec)
        assert iface.kind == SymbolKind.CALLABLE
        param_names = [p.name for p in iface.params]
        assert "x" in param_names
        assert "y" in param_names

    def test_interface_missing_returns_none(self):
        t = self._populated_table()
        assert t.interface("nope") is None

    def test_kinds(self):
        t = self._populated_table()
        k = t.kinds()
        assert k["count"] == SymbolKind.VALUE
        assert k["my_fn"] == SymbolKind.CALLABLE
        assert k["MyType"] == SymbolKind.TYPE

    def test_exported_subtable(self):
        t = self._populated_table()
        exp = t.exported()
        names = list(exp)
        assert "count" in names
        assert "priv" not in names


# ── __scope__ in interpolation ───────────────────────────────────────────────


class TestScopeInInterpolation:
    """configs can query __scope__ from ${...} expressions."""

    def test_scope_has(self):
        """__scope__.has() works in interpolation."""
        cfg = dracon.loads("""
!define greeting: hello
check: ${__scope__.has('greeting')}
""")
        assert cfg["check"] is True

    def test_scope_names(self):
        """__scope__.names() returns user-defined names."""
        cfg = dracon.loads("""
!define x: 1
!define y: 2
vocab: ${__scope__.names(kind='value')}
""")
        names = cfg["vocab"]
        assert "x" in names
        assert "y" in names

    def test_scope_interface(self):
        """__scope__.interface() returns InterfaceSpec for a symbol."""
        cfg = dracon.loads("""
!define greet: !fn
  !require name: "who to greet"
  !fn : "Hello, ${name}!"
iface: ${__scope__.interface('greet')}
""")
        iface = cfg["iface"]
        assert isinstance(iface, InterfaceSpec)
        assert iface.kind == SymbolKind.TEMPLATE

    def test_scope_composes_across_layers(self):
        """__scope__ grows when vocabularies are layered."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "base.yaml"
            base.write_text("!define alpha: 1\n")
            main = Path(tmp) / "main.yaml"
            main.write_text(f"""
<<(<): !include file:{base}
!define beta: 2
has_alpha: ${{__scope__.has('alpha')}}
has_beta: ${{__scope__.has('beta')}}
""")
            cfg = dracon.load(str(main))
            assert cfg["has_alpha"] is True
            assert cfg["has_beta"] is True


# ── symbols rendering (text + JSON) ─────────────────────────────────────────


class TestSymbolsRendering:
    """render_symbols_text() and render_symbols_json() from symbol_table."""

    def test_render_text_basic(self):
        from dracon.symbol_table import render_symbols_text
        t = SymbolTable()

        def svc(name, port=8080):
            pass

        t.define(SymbolEntry(name="Service", symbol=CallableSymbol(svc, name="Service")))
        t.define(SymbolEntry(name="count", symbol=ValueSymbol(42, name="count")))
        text = render_symbols_text(t)
        assert "Service" in text
        assert "count" in text

    def test_render_json_basic(self):
        from dracon.symbol_table import render_symbols_json
        t = SymbolTable()

        def svc(name, port=8080):
            pass

        t.define(SymbolEntry(name="Service", symbol=CallableSymbol(svc, name="Service")))
        data = render_symbols_json(t)
        parsed = json.loads(data)
        assert "Service" in parsed
        assert parsed["Service"]["kind"] == "callable"
        assert any(p["name"] == "name" for p in parsed["Service"]["params"])

    def test_render_json_stability(self):
        """JSON output is deterministic (sorted keys)."""
        from dracon.symbol_table import render_symbols_json
        t = SymbolTable()
        t.define(SymbolEntry(name="b", symbol=ValueSymbol(2, name="b")))
        t.define(SymbolEntry(name="a", symbol=ValueSymbol(1, name="a")))
        j1 = render_symbols_json(t)
        j2 = render_symbols_json(t)
        assert j1 == j2
        # keys should be sorted
        parsed = json.loads(j1)
        assert list(parsed.keys()) == sorted(parsed.keys())

    def test_render_excludes_internals(self):
        """Internal names like getenv, Path, etc are not shown."""
        from dracon.symbol_table import render_symbols_text
        loader = DraconLoader()
        text = render_symbols_text(loader.context)
        # internals from DEFAULT_CONTEXT should be hidden
        assert "getenv" not in text
        assert "getcwd" not in text


# ── CLI --symbols / --symbols-json ───────────────────────────────────────────


class TestCLISymbols:
    """dracon show --symbols and --symbols-json flags."""

    def _run_show(self, argv):
        from dracon.cli import DraconCLI
        from unittest.mock import patch
        with patch('sys.exit'):
            return DraconCLI.cli(argv=["show"] + argv)

    def test_symbols_flag(self):
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            f.write("!define greet: !fn\n  !require name: 'who'\n  !fn : 'hi ${name}'\nval: 1\n")
            f.flush()
            try:
                result = self._run_show([f.name, "--symbols"])
                assert "greet" in result
            finally:
                os.unlink(f.name)

    def test_symbols_json_flag(self):
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            f.write("!define greet: !fn\n  !require name: 'who'\n  !fn : 'hi ${name}'\n")
            f.flush()
            try:
                result = self._run_show([f.name, "--symbols-json"])
                data = json.loads(result)
                assert "greet" in data
            finally:
                os.unlink(f.name)


# ── improved error messages ──────────────────────────────────────────────────


class TestImprovedErrors:
    """Error messages show interface and scope information."""

    def test_unresolved_tag_shows_available(self):
        """When a tag can't be resolved, error should mention available symbols."""
        class MyModel(BaseModel):
            x: int = 1

        loader = DraconLoader(context={"MyModel": MyModel})
        with pytest.raises(Exception) as exc_info:
            loader.loads("result: !Nope\n  x: 1\n")
        msg = str(exc_info.value)
        # should mention what IS available (MyModel) or hint at scope
        assert "MyModel" in msg or "scope" in msg.lower() or "available" in msg.lower()

    def test_wrong_callable_args_shows_interface(self):
        """When callable gets wrong args, error should show expected interface."""
        def my_fn(*, name: str, port: int = 8080):
            return {"name": name, "port": port}

        loader = DraconLoader(context={"my_fn": my_fn})
        with pytest.raises(Exception) as exc_info:
            loader.loads("result: !my_fn\n  wrong_arg: oops\n")
        msg = str(exc_info.value)
        assert "name" in msg or "interface" in msg.lower() or "expected" in msg.lower()

    def test_deferred_missing_runtime_shows_contract(self):
        """DeferredNode error should mention the required runtime inputs."""
        cfg = dracon.loads("""
report: !deferred
  !require run_id: "runtime run identifier"
  path: "/runs/${run_id}"
""")
        node = cfg["report"]
        with pytest.raises(Exception) as exc_info:
            node.construct(context={})
        msg = str(exc_info.value)
        # should mention what was required
        assert "run_id" in msg


# ── regression tests ─────────────────────────────────────────────────────────


class TestRegressions:
    """Existing patterns still work after catalog changes."""

    def test_constructor_slots(self):
        """Dynamic tag selection from a mapping."""
        class ResNet(BaseModel):
            layers: int = 12

        class Transformer(BaseModel):
            layers: int = 6

        cfg = dracon.loads("""
!define model_types:
  resnet: ResNet
  transformer: Transformer
!set_default model_kind: resnet
model: !$(model_types[model_kind])
  layers: 24
""", context={"ResNet": ResNet, "Transformer": Transformer})
        assert cfg["model"].layers == 24
        assert isinstance(cfg["model"], ResNet)

    def test_define_alias(self):
        """!define Alias: ${Type} then !Alias."""
        class MLP(BaseModel):
            hidden: int = 128

        cfg = dracon.loads("""
!define Net: ${MLP}
result: !Net
  hidden: 256
""", context={"MLP": MLP})
        assert isinstance(cfg["result"], MLP)
        assert cfg["result"].hidden == 256

    def test_layered_vocabs(self):
        """Propagated vocabulary definitions compose across files."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "base.yaml"
            base.write_text("""
!define greet: !fn
  !require name: "who"
  !fn : "hello ${name}"
""")
            main = Path(tmp) / "main.yaml"
            main.write_text(f"""
<<(<): !include file:{base}
msg: !greet {{name: world}}
""")
            cfg = dracon.load(str(main))
            assert cfg["msg"] == "hello world"

    def test_mixed_pipe_stages(self):
        """Pipe definition from context callables has symbol protocol."""
        def step1(x):
            return x * 2

        def step2(x):
            return x + 1

        loader = DraconLoader(context={"step1": step1, "step2": step2})
        cr = loader.compose_config_from_str("""
!define pipeline: !pipe
  - step1
  - step2
val: 1
""")
        pipeline = cr.defined_vars.get("pipeline")
        assert pipeline is not None
        assert isinstance(pipeline, DraconPipe)
        iface = pipeline.interface()
        assert iface.kind == SymbolKind.PIPE

    def test_deferred_contracts(self):
        """Deferred node with runtime contracts."""
        cfg = dracon.loads("""
report: !deferred
  !require run_id: "runtime run id"
  path: "/runs/${run_id}"
""")
        node = cfg["report"]
        result = node.construct(context={"run_id": "abc"})
        assert result["path"] == "/runs/abc"

    def test_backward_compat_dracon_partial(self):
        """DraconPartial still works as before."""
        def my_func(a, b, c=10):
            return a + b + c

        p = DraconPartial("test.my_func", my_func, {"b": 5})
        assert p(1) == 16  # 1 + 5 + 10
        assert p(1, c=20) == 26  # 1 + 5 + 20
        # symbol protocol
        iface = p.interface()
        assert iface.kind == SymbolKind.CALLABLE
        param_names = [pp.name for pp in iface.params]
        assert "a" in param_names
        assert "b" not in param_names  # already bound

    def test_loader_catalog_property(self):
        """DraconLoader exposes catalog() that returns symbols view."""
        class MyModel(BaseModel):
            x: int = 1

        loader = DraconLoader(context={"MyModel": MyModel})
        loader.loads("!define factor: 2\nval: 1\n")
        cat = loader.catalog()
        assert isinstance(cat, dict)
        # context-provided type should appear in the catalog
        assert "MyModel" in cat
        assert cat["MyModel"]["kind"] == "type"
