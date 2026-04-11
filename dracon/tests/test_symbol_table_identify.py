# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""Tests for SymbolTable.identify() and the canonical/alias invariants.

Covers:
- Symbol.represented_type() defaults on every concrete kind
- identify() MRO walk, caching, parent-chain via overlay
- canonical vs consume-only aliases
- collision detection across every mutation path (define, set_default,
  __setitem__, _merge_into_symbol_table)
- captured-globals default to non-canonical
"""

from __future__ import annotations

from enum import Enum

import pytest
from pydantic import BaseModel

from dracon.symbols import (
    BoundSymbol,
    CallableSymbol,
    ValueSymbol,
)
from dracon.symbol_table import (
    CanonicalCollisionError,
    SymbolEntry,
    SymbolTable,
)
from dracon.merge import _merge_into_symbol_table, cached_merge_key


# ── fixtures ────────────────────────────────────────────────────────────────


class Animal:
    pass


class Dog(Animal):
    pass


class Puppy(Dog):
    pass


class Submit(BaseModel):
    name: str = "x"


class SubmitChild(Submit):
    pass


class Status(str, Enum):
    RUNNING = "running"
    DONE = "done"


def make_endpoint(name: str, port: int = 8080):
    return f"https://{name}:{port}"


# ── Symbol.represented_type ─────────────────────────────────────────────────


class TestRepresentedType:
    def test_value_symbol_represents_type_for_type_alias(self):
        sym = ValueSymbol(Dog, name="Net")
        assert sym.represented_type() is Dog

    def test_value_symbol_represents_none_for_plain_value(self):
        assert ValueSymbol(42, name="n").represented_type() is None
        assert ValueSymbol("hello", name="s").represented_type() is None

    def test_callable_symbol_represents_type_for_class(self):
        sym = CallableSymbol(Dog, name="Dog")
        assert sym.represented_type() is Dog

    def test_callable_symbol_represents_none_for_function(self):
        sym = CallableSymbol(make_endpoint, name="make_endpoint")
        assert sym.represented_type() is None

    def test_bound_symbol_represents_none(self):
        inner = CallableSymbol(Dog, name="Dog")
        bound = BoundSymbol(inner, extra=1)
        assert bound.represented_type() is None

    def test_dracon_callable_represents_none(self):
        from dracon.callable import DraconCallable
        from dracon.composer import DraconMappingNode

        empty_node = DraconMappingNode(tag="tag:yaml.org,2002:map", value=[])
        c = DraconCallable(template_node=empty_node, loader=None, name="t")
        assert c.represented_type() is None

    def test_dracon_pipe_represents_none(self):
        from dracon.pipe import DraconPipe

        p = DraconPipe(stages=[lambda x=0: x], stage_kwargs=[{}], name="p")
        assert p.represented_type() is None

    def test_dracon_partial_represents_type_for_class_target(self):
        from dracon.partial import DraconPartial

        p = DraconPartial(func_path="m.Dog", func=Dog, kwargs={})
        assert p.represented_type() is Dog

    def test_dracon_partial_represents_none_for_function_target(self):
        from dracon.partial import DraconPartial

        p = DraconPartial(func_path="m.f", func=make_endpoint, kwargs={})
        assert p.represented_type() is None

    def test_deferred_node_represents_none(self):
        from dracon.deferred import DeferredNode
        from dracon.nodes import DraconScalarNode

        inner = DraconScalarNode(tag="tag:yaml.org,2002:int", value="1")
        node = DeferredNode(value=inner, loader=None)
        assert node.represented_type() is None


# ── identify() ──────────────────────────────────────────────────────────────


def _define(table: SymbolTable, name: str, value, *, canonical: bool = True):
    table.define(
        SymbolEntry(name=name, symbol=CallableSymbol(value, name=name), canonical=canonical)
    )


class TestIdentify:
    def test_identify_exact_type_match(self):
        t = SymbolTable()
        _define(t, "Submit", Submit)
        assert t.identify(Submit(name="a")) == "Submit"

    def test_identify_mro_walk(self):
        t = SymbolTable()
        _define(t, "Animal", Animal)
        # MRO: Puppy -> Dog -> Animal; only Animal is registered
        assert t.identify(Puppy()) == "Animal"

    def test_identify_picks_most_specific_in_mro(self):
        t = SymbolTable()
        _define(t, "Animal", Animal)
        _define(t, "Dog", Dog, canonical=False)  # alias, skipped
        _define(t, "Puppy", Puppy)
        # Puppy is most specific canonical match in MRO
        assert t.identify(Puppy()) == "Puppy"

    def test_identify_returns_none_for_unregistered(self):
        t = SymbolTable()
        assert t.identify(Dog()) is None

    def test_identify_skips_consume_only_aliases(self):
        t = SymbolTable()
        _define(t, "Submit", Submit)
        _define(t, "Sub", Submit, canonical=False)
        # Sub is an alias; identify should still pick Submit
        assert t.identify(Submit(name="a")) == "Submit"

    def test_identify_primitives_return_none(self):
        t = SymbolTable()
        _define(t, "Submit", Submit)
        assert t.identify(1) is None
        assert t.identify("hello") is None
        assert t.identify(True) is None
        assert t.identify(None) is None

    def test_identify_enum_matches_enum_class(self):
        t = SymbolTable()
        _define(t, "Status", Status)
        assert t.identify(Status.RUNNING) == "Status"

    def test_identify_with_pydantic_subclass(self):
        t = SymbolTable()
        _define(t, "Submit", Submit)
        # SubmitChild's MRO includes Submit; it is not itself registered
        assert t.identify(SubmitChild(name="x")) == "Submit"

    def test_identify_walks_parent_chain_via_overlay(self):
        parent = SymbolTable()
        _define(parent, "Submit", Submit)
        child = SymbolTable()
        view = child.overlay(parent)
        assert view.identify(Submit(name="a")) == "Submit"

    def test_identify_child_shadows_parent(self):
        parent = SymbolTable()
        _define(parent, "Submit", Submit)
        child = SymbolTable()
        _define(child, "Renamed", Submit)
        view = child.overlay(parent)
        # child wins; local scope is consulted before parent
        assert view.identify(Submit(name="a")) == "Renamed"

    def test_identify_deterministic_across_runs(self):
        # order of registration must not affect output for a given MRO
        for _ in range(5):
            t = SymbolTable()
            _define(t, "Animal", Animal)
            _define(t, "Dog", Dog)
            assert t.identify(Puppy()) == "Dog"

    def test_identify_cache_invalidated_on_mutation(self):
        t = SymbolTable()
        _define(t, "Animal", Animal)
        assert t.identify(Dog()) == "Animal"
        _define(t, "Dog", Dog)
        # after registering Dog, a more specific match should be picked up
        assert t.identify(Dog()) == "Dog"

    def test_identify_cache_invalidated_on_delete(self):
        t = SymbolTable()
        _define(t, "Dog", Dog)
        assert t.identify(Dog()) == "Dog"
        del t["Dog"]
        assert t.identify(Dog()) is None


# ── collision detection ─────────────────────────────────────────────────────


class TestCollision:
    def test_duplicate_canonical_raises_on_define(self):
        t = SymbolTable()
        _define(t, "Submit", Submit)
        with pytest.raises(CanonicalCollisionError, match="Submit"):
            _define(t, "SubmitReq", Submit)

    def test_duplicate_canonical_raises_on_set_default(self):
        t = SymbolTable()
        _define(t, "Submit", Submit)
        with pytest.raises(CanonicalCollisionError):
            t.set_default(
                SymbolEntry(name="Other", symbol=CallableSymbol(Submit, name="Other"))
            )

    def test_setitem_inserts_non_canonical(self):
        # raw __setitem__ should never mint a canonical entry
        t = SymbolTable()
        _define(t, "Submit", Submit)
        t["Other"] = Submit  # must not raise
        assert "Other" in t
        assert t.identify(Submit(name="a")) == "Submit"

    def test_duplicate_canonical_raises_on_merge_into_symbol_table(self):
        t = SymbolTable()
        _define(t, "Submit", Submit)
        # merging a fresh canonical entry for the same type should fail
        other = SymbolTable()
        other.define(
            SymbolEntry(name="SubmitReq", symbol=CallableSymbol(Submit, name="SubmitReq"))
        )
        mk = cached_merge_key("{+<}")
        with pytest.raises(CanonicalCollisionError):
            _merge_into_symbol_table(t, other, mk)

    def test_overlay_with_shadowing_does_not_raise(self):
        parent = SymbolTable()
        _define(parent, "A", Submit)
        child = SymbolTable()
        _define(child, "B", Submit)
        # overlay must not run collision detection across parent boundary
        view = child.overlay(parent)
        assert view.identify(Submit(name="a")) == "B"

    def test_consume_only_alias_does_not_collide(self):
        t = SymbolTable()
        _define(t, "Submit", Submit)
        _define(t, "Sub", Submit, canonical=False)
        _define(t, "Subby", Submit, canonical=False)
        # both aliases still resolve as symbols
        assert t.lookup_symbol("Sub") is not None
        assert t.lookup_symbol("Subby") is not None
        # identify still picks the canonical name
        assert t.identify(Submit(name="a")) == "Submit"

    def test_redefining_same_name_does_not_collide_with_itself(self):
        t = SymbolTable()
        _define(t, "Submit", Submit)
        # re-registering under the same name is an overwrite, not a collision
        _define(t, "Submit", Submit)
        assert t.identify(Submit(name="a")) == "Submit"

    def test_collision_message_includes_both_names(self):
        t = SymbolTable()
        _define(t, "Submit", Submit)
        with pytest.raises(CanonicalCollisionError) as exc:
            _define(t, "SubmitReq", Submit)
        msg = str(exc.value)
        assert "Submit" in msg and "SubmitReq" in msg


# ── captured-globals behavior ───────────────────────────────────────────────


class TestCapturedGlobals:
    def test_setitem_captured_globals_default_to_non_canonical(self):
        # composition writes captured globals via table[k] = v.
        # these must not participate in identify(), which defaults to non-canonical.
        t = SymbolTable()
        t["Dog"] = Dog
        assert t.identify(Dog()) is None

    def test_explicit_define_makes_canonical(self):
        t = SymbolTable()
        t.define(SymbolEntry(name="Dog", symbol=CallableSymbol(Dog, name="Dog")))
        assert t.identify(Dog()) == "Dog"

    def test_mixed_captured_and_explicit(self):
        t = SymbolTable()
        t["Dog"] = Dog  # captured global, non-canonical
        t.define(SymbolEntry(name="Animal", symbol=CallableSymbol(Animal, name="Animal")))
        # Animal is canonical; Dog is alias-only, so MRO walk hits Animal
        assert t.identify(Dog()) == "Animal"
