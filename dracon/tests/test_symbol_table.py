# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""Tests for dracon.symbol_table -- SymbolEntry and SymbolTable."""

import pytest
from dracon.symbols import (
    SymbolKind,
    InterfaceSpec,
    ValueSymbol,
    CallableSymbol,
    SymbolSourceInfo,
)
from dracon.symbol_table import SymbolEntry, SymbolTable


# ── SymbolEntry ──────────────────────────────────────────────────────────────

class TestSymbolEntry:
    def test_frozen(self):
        entry = SymbolEntry(name="x", symbol=ValueSymbol(1, name="x"))
        with pytest.raises(AttributeError):
            entry.name = "y"

    def test_defaults(self):
        entry = SymbolEntry(name="x", symbol=ValueSymbol(1, name="x"))
        assert entry.exported is True
        assert entry.source is None


# ── SymbolTable define/set_default ────────────────────────────────────────────

class TestSymbolTableDefine:
    def test_define_sets_value(self):
        t = SymbolTable()
        t.define(SymbolEntry(name="x", symbol=ValueSymbol(10, name="x")))
        assert t["x"] == 10

    def test_define_overwrites(self):
        t = SymbolTable()
        t.define(SymbolEntry(name="x", symbol=ValueSymbol(1, name="x")))
        t.define(SymbolEntry(name="x", symbol=ValueSymbol(2, name="x")))
        assert t["x"] == 2

    def test_define_no_overwrite(self):
        t = SymbolTable()
        t.define(SymbolEntry(name="x", symbol=ValueSymbol(1, name="x")))
        t.define(SymbolEntry(name="x", symbol=ValueSymbol(2, name="x")), overwrite=False)
        assert t["x"] == 1

    def test_set_default_fills_missing(self):
        t = SymbolTable()
        t.set_default(SymbolEntry(name="x", symbol=ValueSymbol(42, name="x")))
        assert t["x"] == 42

    def test_set_default_does_not_overwrite(self):
        t = SymbolTable()
        t.define(SymbolEntry(name="x", symbol=ValueSymbol(1, name="x")))
        t.set_default(SymbolEntry(name="x", symbol=ValueSymbol(99, name="x")))
        assert t["x"] == 1

    def test_set_default_marks_soft(self):
        t = SymbolTable()
        t.set_default(SymbolEntry(name="x", symbol=ValueSymbol(1, name="x")))
        assert t.is_soft("x")

    def test_define_hardens_soft(self):
        t = SymbolTable()
        t.set_default(SymbolEntry(name="x", symbol=ValueSymbol(1, name="x")))
        assert t.is_soft("x")
        t.define(SymbolEntry(name="x", symbol=ValueSymbol(2, name="x")))
        assert not t.is_soft("x")


# ── lookup ───────────────────────────────────────────────────────────────────

class TestSymbolTableLookup:
    def test_lookup_symbol(self):
        t = SymbolTable()
        sym = ValueSymbol(10, name="x")
        t.define(SymbolEntry(name="x", symbol=sym))
        assert t.lookup_symbol("x") is sym

    def test_lookup_symbol_missing(self):
        t = SymbolTable()
        assert t.lookup_symbol("nope") is None

    def test_lookup_entry(self):
        t = SymbolTable()
        entry = SymbolEntry(name="x", symbol=ValueSymbol(10, name="x"))
        t.define(entry)
        result = t.lookup_entry("x")
        assert result is not None
        assert result.name == "x"

    def test_getitem_materializes(self):
        fn = lambda: 42
        t = SymbolTable()
        t.define(SymbolEntry(name="fn", symbol=CallableSymbol(fn, name="fn")))
        # __getitem__ returns materialized value (the callable itself)
        assert t["fn"] is fn

    def test_contains(self):
        t = SymbolTable()
        t.define(SymbolEntry(name="x", symbol=ValueSymbol(1, name="x")))
        assert "x" in t
        assert "y" not in t

    def test_len(self):
        t = SymbolTable()
        t.define(SymbolEntry(name="a", symbol=ValueSymbol(1, name="a")))
        t.define(SymbolEntry(name="b", symbol=ValueSymbol(2, name="b")))
        assert len(t) == 2

    def test_iter(self):
        t = SymbolTable()
        t.define(SymbolEntry(name="a", symbol=ValueSymbol(1, name="a")))
        t.define(SymbolEntry(name="b", symbol=ValueSymbol(2, name="b")))
        assert set(t) == {"a", "b"}


# ── exported entries ─────────────────────────────────────────────────────────

class TestSymbolTableExports:
    def test_exported(self):
        t = SymbolTable()
        t.define(SymbolEntry(name="pub", symbol=ValueSymbol(1, name="pub"), exported=True))
        t.define(SymbolEntry(name="priv", symbol=ValueSymbol(2, name="priv"), exported=False))
        exported = list(t.exported_entries())
        names = [e.name for e in exported]
        assert "pub" in names
        assert "priv" not in names


# ── overlay ──────────────────────────────────────────────────────────────────

class TestSymbolTableOverlay:
    def test_overlay_lookup_order(self):
        """child entries shadow parent entries."""
        parent = SymbolTable()
        parent.define(SymbolEntry(name="x", symbol=ValueSymbol(1, name="x")))
        parent.define(SymbolEntry(name="y", symbol=ValueSymbol(2, name="y")))
        child = SymbolTable()
        child.define(SymbolEntry(name="x", symbol=ValueSymbol(99, name="x")))
        overlay = child.overlay(parent)
        assert overlay["x"] == 99
        assert overlay["y"] == 2

    def test_overlay_contains(self):
        parent = SymbolTable()
        parent.define(SymbolEntry(name="x", symbol=ValueSymbol(1, name="x")))
        child = SymbolTable()
        overlay = child.overlay(parent)
        assert "x" in overlay

    def test_overlay_iter(self):
        parent = SymbolTable()
        parent.define(SymbolEntry(name="a", symbol=ValueSymbol(1, name="a")))
        child = SymbolTable()
        child.define(SymbolEntry(name="b", symbol=ValueSymbol(2, name="b")))
        overlay = child.overlay(parent)
        assert set(overlay) == {"a", "b"}


# ── materialized view consistency ────────────────────────────────────────────

class TestSymbolTableConsistency:
    def test_getitem_consistent_after_define(self):
        t = SymbolTable()
        t.define(SymbolEntry(name="x", symbol=ValueSymbol(1, name="x")))
        assert t["x"] == 1
        t.define(SymbolEntry(name="x", symbol=ValueSymbol(2, name="x")))
        assert t["x"] == 2

    def test_dict_view(self):
        """items/keys/values match __getitem__."""
        t = SymbolTable()
        t.define(SymbolEntry(name="a", symbol=ValueSymbol(10, name="a")))
        t.define(SymbolEntry(name="b", symbol=ValueSymbol(20, name="b")))
        assert dict(t.items()) == {"a": 10, "b": 20}


# ── propagation preserves source ─────────────────────────────────────────────

class TestSymbolTablePropagation:
    def test_source_preserved(self):
        src = SymbolSourceInfo(file_path="base.yaml", line=5)
        parent = SymbolTable()
        parent.define(SymbolEntry(
            name="x", symbol=ValueSymbol(1, name="x"), source=src,
        ))
        child = SymbolTable()
        overlay = child.overlay(parent)
        entry = overlay.lookup_entry("x")
        assert entry is not None
        assert entry.source is not None
        assert entry.source.file_path == "base.yaml"
        assert entry.source.line == 5


# ── Mapping protocol ────────────────────────────────────────────────────────

class TestSymbolTableMapping:
    def test_get_with_default(self):
        t = SymbolTable()
        assert t.get("x", 42) == 42
        t.define(SymbolEntry(name="x", symbol=ValueSymbol(1, name="x")))
        assert t.get("x", 42) == 1

    def test_keyerror_on_missing(self):
        t = SymbolTable()
        with pytest.raises(KeyError):
            _ = t["nope"]


# ── setitem/delitem for backwards compat ─────────────────────────────────────

class TestSymbolTableMutation:
    def test_setitem(self):
        """raw __setitem__ wraps value in ValueSymbol."""
        t = SymbolTable()
        t["x"] = 42
        assert t["x"] == 42
        assert t.lookup_symbol("x") is not None

    def test_delitem(self):
        t = SymbolTable()
        t["x"] = 42
        del t["x"]
        assert "x" not in t

    def test_update(self):
        t = SymbolTable()
        t.update({"a": 1, "b": 2})
        assert t["a"] == 1
        assert t["b"] == 2

    def test_pop(self):
        t = SymbolTable()
        t["x"] = 10
        v = t.pop("x", None)
        assert v == 10
        assert "x" not in t

    def test_pop_missing(self):
        t = SymbolTable()
        assert t.pop("x", 42) == 42

    def test_clear(self):
        t = SymbolTable()
        t["x"] = 1
        t["y"] = 2
        t.clear()
        assert len(t) == 0

    def test_copy(self):
        t = SymbolTable()
        t["x"] = 1
        c = t.copy()
        c["x"] = 2
        assert t["x"] == 1
        assert c["x"] == 2
