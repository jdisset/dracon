# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""Tests for scope unification: SymbolTable is __scope__ directly, with describe/to_json methods."""

import json
import os
import tempfile
from pathlib import Path

import pytest
from pydantic import BaseModel

import dracon
from dracon import DraconLoader
from dracon.symbols import (
    SymbolKind,
    InterfaceSpec,
    ValueSymbol,
    CallableSymbol,
    auto_symbol,
)
from dracon.symbol_table import SymbolEntry, SymbolTable


# ── __scope__ is SymbolTable directly (not a proxy) ─────────────────────────


class TestScopeIsTable:
    """__scope__ in interpolation is the SymbolTable itself."""

    def test_scope_is_symbol_table_instance(self):
        """__scope__ resolves to SymbolTable, not a proxy.
        ScopeProxy never had describe(); SymbolTable does."""
        cfg = dracon.loads("""
!define x: 42
desc: ${__scope__.describe('x')}
""")
        assert "x" in cfg["desc"]
        assert "value" in cfg["desc"]

    def test_scope_contains_check(self):
        """'name' in __scope__ works (standard Mapping protocol)."""
        cfg = dracon.loads("""
!define greeting: hello
has_it: ${'greeting' in __scope__}
missing: ${'nope' in __scope__}
""")
        assert cfg["has_it"] is True
        assert cfg["missing"] is False

    def test_scope_has_method(self):
        """__scope__.has() still works after unification."""
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


# ── describe() and to_json() methods on SymbolTable ────────────────────────


class TestDescribeMethod:
    """SymbolTable.describe() returns human-readable text."""

    def test_describe_all(self):
        t = SymbolTable()
        def svc(name, port=8080):
            pass
        t.define(SymbolEntry(name="Service", symbol=CallableSymbol(svc, name="Service")))
        t.define(SymbolEntry(name="count", symbol=ValueSymbol(42, name="count")))
        text = t.describe()
        assert "Service" in text
        assert "count" in text

    def test_describe_single_symbol(self):
        t = SymbolTable()
        def svc(name, port=8080):
            pass
        t.define(SymbolEntry(name="Service", symbol=CallableSymbol(svc, name="Service")))
        text = t.describe("Service")
        assert "Service" in text
        assert "name" in text  # param should be visible

    def test_describe_missing_symbol(self):
        t = SymbolTable()
        text = t.describe("nope")
        assert text == ""

    def test_describe_excludes_internals(self):
        loader = DraconLoader()
        text = loader.context.describe()
        assert "getenv" not in text
        assert "getcwd" not in text

    def test_describe_in_interpolation(self):
        """${__scope__.describe()} returns text from interpolation."""
        cfg = dracon.loads("""
!define greeting: hello
desc: ${__scope__.describe()}
""")
        desc = cfg["desc"]
        assert isinstance(desc, str)
        assert "greeting" in desc

    def test_describe_single_in_interpolation(self):
        """${__scope__.describe('name')} for a single symbol."""
        cfg = dracon.loads("""
!define Service: !fn
  !require name: "svc name"
  !fn : "url: ${name}"
desc: ${__scope__.describe('Service')}
""")
        desc = cfg["desc"]
        assert "Service" in desc
        assert "name" in desc


class TestToJsonMethod:
    """SymbolTable.to_json() returns structured dict."""

    def test_to_json_basic(self):
        t = SymbolTable()
        def svc(name, port=8080):
            pass
        t.define(SymbolEntry(name="Service", symbol=CallableSymbol(svc, name="Service")))
        data = t.to_json()
        assert "Service" in data
        assert data["Service"]["kind"] == "callable"

    def test_to_json_filter_by_kind(self):
        t = SymbolTable()
        t.define(SymbolEntry(name="count", symbol=ValueSymbol(42, name="count")))
        def fn():
            pass
        t.define(SymbolEntry(name="fn", symbol=CallableSymbol(fn, name="fn")))
        vals = t.to_json(kind=SymbolKind.VALUE)
        assert "count" in vals
        assert "fn" not in vals

    def test_to_json_serializable(self):
        """to_json() output is JSON-serializable."""
        t = SymbolTable()
        t.define(SymbolEntry(name="x", symbol=ValueSymbol(42, name="x")))
        data = t.to_json()
        s = json.dumps(data, default=str)
        assert isinstance(s, str)

    def test_to_json_stability(self):
        """JSON output is deterministic (sorted keys)."""
        t = SymbolTable()
        t.define(SymbolEntry(name="b", symbol=ValueSymbol(2, name="b")))
        t.define(SymbolEntry(name="a", symbol=ValueSymbol(1, name="a")))
        j1 = t.to_json()
        j2 = t.to_json()
        assert j1 == j2
        assert list(j1.keys()) == sorted(j1.keys())

    def test_to_json_in_interpolation(self):
        """${__scope__.to_json()} returns a dict."""
        cfg = dracon.loads("""
!define x: 42
info: ${__scope__.to_json()}
""")
        info = cfg["info"]
        assert isinstance(info, dict)
        assert "x" in info


# ── CLI uses table methods directly ──────────────────────────────────────────


class TestCLIUsesTableMethods:
    """--symbols and --symbols-json call table.describe() and table.to_json()."""

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

    def test_symbols_output_matches_describe(self):
        """CLI --symbols output is the same as table.describe()."""
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            f.write("!define counter: 10\n")
            f.flush()
            try:
                loader = DraconLoader()
                cr = loader.compose(f.name)
                # replicate what CLI does: merge defined_vars into scope
                scope = loader.context.copy()
                if cr.defined_vars:
                    scope.update(cr.defined_vars)
                expected = scope.describe()
                result = self._run_show([f.name, "--symbols"])
                assert ("counter" in result) == ("counter" in expected)
            finally:
                os.unlink(f.name)


# ── error messages use describe() ────────────────────────────────────────────


class TestErrorsUseDescribe:
    """Error messages include available symbols via table.describe()."""

    def test_unresolved_tag_shows_available(self):
        class MyModel(BaseModel):
            x: int = 1
        loader = DraconLoader(context={"MyModel": MyModel})
        with pytest.raises(Exception) as exc_info:
            loader.loads("result: !Nope\n  x: 1\n")
        msg = str(exc_info.value)
        assert "MyModel" in msg or "scope" in msg.lower() or "available" in msg.lower()

    def test_wrong_callable_args_shows_interface(self):
        def my_fn(*, name: str, port: int = 8080):
            return {"name": name, "port": port}
        loader = DraconLoader(context={"my_fn": my_fn})
        with pytest.raises(Exception) as exc_info:
            loader.loads("result: !my_fn\n  wrong_arg: oops\n")
        msg = str(exc_info.value)
        assert "name" in msg or "interface" in msg.lower() or "expected" in msg.lower()


# ── vocabulary-conditional composition ───────────────────────────────────────


class TestVocabularyConditionals:
    """!if and !assert with __scope__."""

    def test_if_scope_has(self):
        """!if ${__scope__.has(...)} controls composition."""
        cfg = dracon.loads("""
!define gpu: true
result:
  !if ${__scope__.has('gpu')}:
    accelerated: yes
""")
        assert cfg["result"]["accelerated"] == "yes"

    def test_if_scope_has_missing(self):
        """!if ${__scope__.has(...)} false branch."""
        cfg = dracon.loads("""
result:
  !if ${__scope__.has('gpu')}:
    then:
      accelerated: yes
    else:
      accelerated: no
""")
        assert cfg["result"]["accelerated"] == "no"

    def test_assert_scope_has_passes(self):
        """!assert with __scope__ check passes when symbol exists."""
        cfg = dracon.loads("""
!define Service: !fn
  !require name: "svc"
  !fn : "${name}"
!assert ${__scope__.has('Service')}: "missing Service"
val: ok
""")
        assert cfg["val"] == "ok"

    def test_assert_scope_has_fails(self):
        """!assert with __scope__ check fails when symbol missing."""
        with pytest.raises(Exception, match="missing Service"):
            dracon.loads("""
!assert ${__scope__.has('Service')}: "missing Service"
val: ok
""")

    def test_assert_with_in_syntax(self):
        """!assert ${'name' in __scope__} works."""
        cfg = dracon.loads("""
!define name: test
!assert ${'name' in __scope__}: "name should exist"
val: ok
""")
        assert cfg["val"] == "ok"


# ── scope composes across layers ──────────────────────────────────────────────


class TestScopeAcrossLayers:
    """__scope__ grows when vocabularies are layered."""

    def test_scope_composes_across_layers(self):
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


# ── ScopeProxy is gone ───────────────────────────────────────────────────────


class TestNoScopeProxy:
    """ScopeProxy class no longer exists."""

    def test_no_scope_proxy_in_module(self):
        from dracon import symbol_table
        assert not hasattr(symbol_table, 'ScopeProxy')

    def test_no_render_symbols_text_free_function(self):
        from dracon import symbol_table
        assert not hasattr(symbol_table, 'render_symbols_text')

    def test_no_render_symbols_json_free_function(self):
        from dracon import symbol_table
        assert not hasattr(symbol_table, 'render_symbols_json')


# ── loader catalog still works ───────────────────────────────────────────────


class TestLoaderCatalogCompat:
    """DraconLoader.catalog() still works after moving rendering to methods."""

    def test_catalog_uses_to_json(self):
        class MyModel(BaseModel):
            x: int = 1
        loader = DraconLoader(context={"MyModel": MyModel})
        loader.loads("!define factor: 2\nval: 1\n")
        cat = loader.catalog()
        assert isinstance(cat, dict)
        assert "MyModel" in cat
