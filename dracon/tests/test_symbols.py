# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""Tests for dracon.symbols -- core typed model."""

import pytest
from dracon.symbols import (
    SymbolKind,
    ParamSpec,
    ContractSpec,
    SymbolSourceInfo,
    InterfaceSpec,
    BoundSymbol,
    ValueSymbol,
    CallableSymbol,
    MISSING,
)


# ── InterfaceSpec ────────────────────────────────────────────────────────────

class TestInterfaceSpec:
    def test_immutable(self):
        spec = InterfaceSpec(kind=SymbolKind.VALUE, name="x")
        with pytest.raises(AttributeError):
            spec.name = "y"

    def test_equality(self):
        a = InterfaceSpec(kind=SymbolKind.VALUE, name="x")
        b = InterfaceSpec(kind=SymbolKind.VALUE, name="x")
        assert a == b

    def test_inequality_different_kind(self):
        a = InterfaceSpec(kind=SymbolKind.VALUE, name="x")
        b = InterfaceSpec(kind=SymbolKind.TYPE, name="x")
        assert a != b

    def test_params_tuple(self):
        p = ParamSpec(name="lr", required=True)
        spec = InterfaceSpec(kind=SymbolKind.CALLABLE, name="train", params=(p,))
        assert spec.params == (p,)
        assert spec.params[0].required is True

    def test_contracts_roundtrip(self):
        c = ContractSpec(kind="require", name="run_id", message="needed for logging")
        spec = InterfaceSpec(
            kind=SymbolKind.DEFERRED,
            name="reporter",
            contracts=(c,),
        )
        assert spec.contracts[0].kind == "require"
        assert spec.contracts[0].name == "run_id"
        assert spec.contracts[0].message == "needed for logging"

    def test_source_context(self):
        src = SymbolSourceInfo(file_path="config.yaml", line=10)
        spec = InterfaceSpec(kind=SymbolKind.VALUE, name="x", source=src)
        assert spec.source.file_path == "config.yaml"
        assert spec.source.line == 10

    def test_hashable(self):
        spec = InterfaceSpec(kind=SymbolKind.VALUE, name="x")
        # should not raise
        {spec: 1}


# ── ParamSpec ────────────────────────────────────────────────────────────────

class TestParamSpec:
    def test_required_param(self):
        p = ParamSpec(name="lr", required=True)
        assert p.default is MISSING

    def test_optional_param(self):
        p = ParamSpec(name="lr", required=False, default=0.01)
        assert p.default == 0.01

    def test_immutable(self):
        p = ParamSpec(name="lr", required=True)
        with pytest.raises(AttributeError):
            p.name = "other"


# ── ValueSymbol ──────────────────────────────────────────────────────────────

class TestValueSymbol:
    def test_materialize(self):
        s = ValueSymbol(42, name="answer")
        assert s.materialize() == 42

    def test_interface_kind(self):
        s = ValueSymbol("hello", name="greeting")
        assert s.interface().kind == SymbolKind.VALUE
        assert s.interface().name == "greeting"

    def test_invoke_returns_value(self):
        s = ValueSymbol(99, name="n")
        assert s.invoke() == 99

    def test_bind_returns_same(self):
        s = ValueSymbol(10, name="n")
        b = s.bind(x=1)
        assert b.materialize() == 10


# ── CallableSymbol ───────────────────────────────────────────────────────────

class TestCallableSymbol:
    def test_materialize_returns_callable(self):
        fn = lambda x, y: x + y
        s = CallableSymbol(fn, name="add")
        assert s.materialize() is fn

    def test_invoke(self):
        fn = lambda x, y: x + y
        s = CallableSymbol(fn, name="add")
        assert s.invoke(x=2, y=3) == 5

    def test_interface_params(self):
        def train(lr, epochs=10):
            pass
        s = CallableSymbol(train, name="train")
        spec = s.interface()
        assert spec.kind == SymbolKind.CALLABLE
        names = [p.name for p in spec.params]
        assert "lr" in names
        assert "epochs" in names
        lr_param = next(p for p in spec.params if p.name == "lr")
        epochs_param = next(p for p in spec.params if p.name == "epochs")
        assert lr_param.required is True
        assert epochs_param.required is False
        assert epochs_param.default == 10

    def test_type_symbol(self):
        s = CallableSymbol(int, name="int")
        assert s.interface().kind == SymbolKind.TYPE


# ── BoundSymbol ──────────────────────────────────────────────────────────────

class TestBoundSymbol:
    def test_bound_removes_required_param(self):
        def train(lr, epochs=10):
            pass
        s = CallableSymbol(train, name="train")
        bound = BoundSymbol(s, lr=0.01)
        spec = bound.interface()
        names = [p.name for p in spec.params]
        assert "lr" not in names
        assert "epochs" in names

    def test_invoke_merges_kwargs(self):
        """stored kwargs first, runtime overrides."""
        calls = []
        def fn(a, b):
            calls.append((a, b))
        s = CallableSymbol(fn, name="fn")
        bound = BoundSymbol(s, a=1, b=2)
        bound.invoke(b=99)
        assert calls[-1] == (1, 99)

    def test_double_bind(self):
        def fn(a, b, c):
            return a + b + c
        s = CallableSymbol(fn, name="fn")
        b1 = BoundSymbol(s, a=1)
        b2 = b1.bind(b=2)
        assert isinstance(b2, BoundSymbol)
        result = b2.invoke(c=3)
        assert result == 6
        spec = b2.interface()
        names = [p.name for p in spec.params]
        assert "a" not in names
        assert "b" not in names
        assert "c" in names

    def test_materialize_returns_inner(self):
        fn = lambda: 42
        s = CallableSymbol(fn, name="fn")
        bound = BoundSymbol(s)
        assert bound.materialize() is fn

    def test_runtime_overrides_stored(self):
        """runtime kwargs override stored ones."""
        def fn(x):
            return x
        s = CallableSymbol(fn, name="fn")
        bound = BoundSymbol(s, x=1)
        assert bound.invoke(x=2) == 2
