# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""Tests for SymbolSource chain on SymbolTable.

The chain is the SSOT for tag resolution: lookup_symbol() and identify()
both walk the same ordered list of named sources, so removing the
dynamic-import source produces a sandbox-safe loader.
"""

from __future__ import annotations

import pytest

from dracon.symbols import (
    CallableSymbol,
    ValueSymbol,
)
from dracon.symbol_table import (
    SymbolEntry,
    SymbolSource,
    SymbolTable,
)


class Foo:
    pass


class Bar:
    pass


def make_endpoint(name: str, port: int = 8080) -> str:
    return f"https://{name}:{port}"


# ── source-chain plumbing ───────────────────────────────────────────────────


class TestSymbolSourceChain:
    def test_local_entries_take_precedence_over_sources(self):
        src = SymbolSource(
            name='dyn',
            lookup=lambda n: CallableSymbol(Bar, name=n) if n == 'Foo' else None,
        )
        t = SymbolTable(sources=[src])
        t.define(SymbolEntry(name='Foo', symbol=CallableSymbol(Foo, name='Foo')))
        sym = t.lookup_symbol('Foo')
        assert sym is not None and sym.materialize() is Foo

    def test_lookup_falls_through_to_source(self):
        src = SymbolSource(
            name='dyn',
            lookup=lambda n: CallableSymbol(Foo, name=n) if n == 'Foo' else None,
        )
        t = SymbolTable(sources=[src])
        sym = t.lookup_symbol('Foo')
        assert sym is not None and sym.materialize() is Foo

    def test_lookup_missing_returns_none(self):
        t = SymbolTable(sources=[])
        assert t.lookup_symbol('missing') is None

    def test_sources_are_ordered(self):
        a = SymbolSource(
            name='a', lookup=lambda n: CallableSymbol(Foo, name=n) if n == 'X' else None,
        )
        b = SymbolSource(
            name='b', lookup=lambda n: CallableSymbol(Bar, name=n) if n == 'X' else None,
        )
        t = SymbolTable(sources=[a, b])
        assert t.lookup_symbol('X').materialize() is Foo
        # reverse the order
        t2 = SymbolTable(sources=[b, a])
        assert t2.lookup_symbol('X').materialize() is Bar

    def test_add_source_appends_by_default(self):
        a = SymbolSource(
            name='a', lookup=lambda n: CallableSymbol(Foo, name=n) if n == 'X' else None,
        )
        t = SymbolTable()
        t.add_source(a)
        assert t.lookup_symbol('X').materialize() is Foo

    def test_add_source_with_position(self):
        a = SymbolSource(
            name='a', lookup=lambda n: CallableSymbol(Foo, name=n) if n == 'X' else None,
        )
        b = SymbolSource(
            name='b', lookup=lambda n: CallableSymbol(Bar, name=n) if n == 'X' else None,
        )
        t = SymbolTable(sources=[a])
        t.add_source(b, position=0)
        # b is first now
        assert t.lookup_symbol('X').materialize() is Bar


# ── identify() walks canonical sources only ─────────────────────────────────


class TestIdentifySources:
    def test_identify_skips_non_canonical_source(self):
        # source with canonical_for_identify=False (default) is invisible to identify
        src = SymbolSource(
            name='dyn',
            lookup=lambda n: CallableSymbol(Foo, name=n) if n == 'Foo' else None,
            identify=lambda v: 'Foo' if isinstance(v, Foo) else None,
            canonical_for_identify=False,
        )
        t = SymbolTable(sources=[src])
        # lookup works (forward direction)
        assert t.lookup_symbol('Foo') is not None
        # identify does NOT use the source
        assert t.identify(Foo()) is None

    def test_identify_uses_canonical_source(self):
        src = SymbolSource(
            name='vocab',
            lookup=lambda n: CallableSymbol(Foo, name=n) if n == 'Foo' else None,
            identify=lambda v: 'Foo' if isinstance(v, Foo) else None,
            canonical_for_identify=True,
        )
        t = SymbolTable(sources=[src])
        assert t.identify(Foo()) == 'Foo'

    def test_identify_local_wins_over_source(self):
        src = SymbolSource(
            name='vocab',
            lookup=lambda n: CallableSymbol(Foo, name=n) if n == 'Other' else None,
            identify=lambda v: 'Other' if isinstance(v, Foo) else None,
            canonical_for_identify=True,
        )
        t = SymbolTable(sources=[src])
        t.define(SymbolEntry(name='Local', symbol=CallableSymbol(Foo, name='Local')))
        assert t.identify(Foo()) == 'Local'


# ── parametric tag resolution ────────────────────────────────────────────────


class TestParametricResolveTag:
    def test_resolve_tag_strips_leading_bang(self):
        t = SymbolTable()
        t.define(SymbolEntry(name='Foo', symbol=CallableSymbol(Foo, name='Foo')))
        # both forms should resolve
        assert t.resolve_tag('Foo') is not None
        assert t.resolve_tag('!Foo') is not None

    def test_resolve_tag_unknown_returns_none(self):
        t = SymbolTable()
        assert t.resolve_tag('NoSuchThing') is None

    def test_parametric_tag_dispatches_to_parametric_apply(self):
        captured: list[tuple[str, ...]] = []

        class FakeBase:
            def interface(self): ...
            def bind(self, **kw): ...
            def invoke(self, **kw): ...
            def materialize(self): return self
            def represented_type(self): return None

            def parametric_apply(self, type_args):
                captured.append(type_args)
                return self

        base_sym = FakeBase()
        t = SymbolTable()
        t.define(SymbolEntry(name='Resolvable', symbol=base_sym))
        result = t.resolve_tag('Resolvable[Foo]')
        assert result is base_sym
        assert captured == [('Foo',)]

    def test_parametric_tag_falls_back_to_base_when_no_hook(self):
        # base symbol without parametric_apply should still resolve
        t = SymbolTable()
        t.define(SymbolEntry(name='Foo', symbol=CallableSymbol(Foo, name='Foo')))
        # Foo[Bar] -> just returns the base symbol
        sym = t.resolve_tag('Foo[Bar]')
        assert sym is not None
