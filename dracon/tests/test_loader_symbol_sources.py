# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""Tests for the DraconLoader symbol_sources kwarg + default chain.

Validates the trust-zone case: a loader constructed without the
`dynamic_import` source must reject ad-hoc imports while still
honoring its explicit vocabulary.
"""

from __future__ import annotations

import pytest

from dracon.loader import DraconLoader
from dracon.symbol_table import SymbolEntry, SymbolSource, SymbolTable
from dracon.symbols import CallableSymbol


from pydantic import BaseModel


class Foo(BaseModel):
    a: int = 0


def test_default_chain_includes_dynamic_import():
    """A vanilla DraconLoader has the dynamic_import source registered."""
    loader = DraconLoader()
    names = [s.name for s in loader.context.sources()]
    assert 'dynamic_import' in names


def test_dynamic_import_resolves_module_type():
    """Without registering os.path.Path, dynamic_import still finds it."""
    loader = DraconLoader()
    sym = loader.context.lookup_symbol('pathlib.Path')
    assert sym is not None


def test_loader_without_dynamic_import_rejects_unknown_tags():
    """Sandbox style: omit the dynamic_import source -> tags must be in vocab."""
    loader = DraconLoader(symbol_sources=[])
    # registered type works
    loader.context.define(
        SymbolEntry(name='Foo', symbol=CallableSymbol(Foo, name='Foo'))
    )
    cfg = loader.loads("x: !Foo { a: 1 }")
    cfg.resolve_all_lazy()
    assert cfg['x'].a == 1
    # an importable type must NOT silently leak through
    with pytest.raises(Exception, match="vocabulary|sandbox"):
        cfg2 = loader.loads("p: !pathlib.Path /tmp")
        cfg2.resolve_all_lazy()


def test_loader_symbol_sources_overrides_default():
    """User-supplied symbol_sources replaces the default chain."""
    src = SymbolSource(
        name='custom',
        lookup=lambda n: CallableSymbol(Foo, name=n) if n == 'CustomThing' else None,
    )
    loader = DraconLoader(symbol_sources=[src])
    names = [s.name for s in loader.context.sources()]
    assert names == ['custom']
    assert loader.context.lookup_symbol('CustomThing') is not None


def test_default_chain_dynamic_import_not_canonical_for_identify():
    """Ad-hoc imports must NOT pollute reverse identify()."""
    from pathlib import Path as PathlibPath
    loader = DraconLoader()
    # dynamic_import found via lookup
    assert loader.context.lookup_symbol('pathlib.Path') is not None
    # but identify() must not return 'pathlib.Path' for a Path instance,
    # because dynamic_import is not canonical_for_identify.
    assert loader.context.identify(PathlibPath('/tmp')) is None
