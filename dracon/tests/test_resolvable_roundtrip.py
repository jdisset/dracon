# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""End-to-end Resolvable[T] round-trip regression.

Step 1 of the SymbolTable refactor pins this contract: a Resolvable wrapping
an inner-type node must dump as `!Resolvable[T]` and parse back into a
Resolvable with `inner_type=T`. Resolution after the round-trip yields the
same value the original would have.
"""

from __future__ import annotations

from pydantic import BaseModel

from dracon.loader import DraconLoader
from dracon.resolvable import Resolvable


class Foo(BaseModel):
    name: str = "x"


def test_resolvable_typed_roundtrip_via_yaml():
    loader = DraconLoader(context={"Foo": Foo})
    text = """
f: !Resolvable[Foo]
  name: bob
"""
    obj = loader.loads(text)
    assert isinstance(obj["f"], Resolvable)
    assert obj["f"].inner_type is Foo

    rendered = loader.dump(obj)
    assert "!Resolvable[Foo]" in rendered

    obj2 = loader.loads(rendered)
    assert isinstance(obj2["f"], Resolvable)
    assert obj2["f"].inner_type is Foo
    resolved = obj2["f"].resolve()
    assert isinstance(resolved, Foo)
    assert resolved.name == "bob"


def test_resolvable_unparameterised_roundtrip():
    loader = DraconLoader(context={"Foo": Foo})
    text = """
f: !Resolvable
  name: anything
"""
    obj = loader.loads(text)
    assert isinstance(obj["f"], Resolvable)

    rendered = loader.dump(obj)
    assert "!Resolvable" in rendered
    obj2 = loader.loads(rendered)
    assert isinstance(obj2["f"], Resolvable)


def test_resolve_tag_routes_parametric_resolvable():
    """SymbolTable.resolve_tag('Resolvable[Foo]') should at least produce the base Resolvable symbol."""
    loader = DraconLoader(context={"Foo": Foo})
    sym = loader.context.resolve_tag("Resolvable")
    assert sym is not None
    # parametric form: dispatches through parametric_apply if present, else returns base
    sym_param = loader.context.resolve_tag("Resolvable[Foo]")
    assert sym_param is not None
