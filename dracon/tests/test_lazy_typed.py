# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""Step 3: Lazy[T] typed Pydantic-friendly wrapper for lazy interpolation values.

Mirrors Resolvable[T] in shape; differs in trigger:
- Resolvable[T] requires explicit .resolve(context) (whole-subtree user-orchestrated)
- Lazy[T] resolves on attribute access from a LazyDraconModel (single ${...})
"""

from __future__ import annotations

from pydantic import BaseModel

from dracon import Lazy, LazyDraconModel, DraconLoader
from dracon.lazy import LazyInterpolable


class Inner(BaseModel):
    name: str = "x"
    n: int = 0


def test_lazy_int_resolves_on_attribute_access():
    class Cfg(LazyDraconModel):
        port: Lazy[int]

    loader = DraconLoader(context={"env_port": 9000, "Cfg": Cfg})
    cfg = loader.loads("!Cfg\nport: ${env_port}")
    assert isinstance(cfg, Cfg)
    # access triggers resolution
    assert cfg.port == 9000
    assert isinstance(cfg.port, int)


def test_lazy_str_with_default_literal():
    class Cfg(LazyDraconModel):
        host: Lazy[str] = "localhost"

    loader = DraconLoader(context={"Cfg": Cfg})
    cfg = loader.loads("!Cfg {}")
    # literal default flows through unchanged
    assert cfg.host == "localhost"


def test_lazy_pydantic_model_field_resolves_to_constructed():
    class Cfg(LazyDraconModel):
        inner: Lazy[Inner]

    loader = DraconLoader(context={
        "the_name": "bob", "the_n": 7, "Inner": Inner, "Cfg": Cfg,
    })
    cfg = loader.loads("!Cfg\ninner: ${Inner(name=the_name, n=the_n)}")
    val = cfg.inner
    assert isinstance(val, Inner)
    assert val.name == "bob" and val.n == 7


def test_lazy_round_trip_preserves_interpolation_string():
    class Cfg(LazyDraconModel):
        port: Lazy[int]

    loader = DraconLoader(context={"env_port": 9000, "Cfg": Cfg})
    text = "!Cfg\nport: ${env_port}\n"
    cfg = loader.loads(text)
    rendered = loader.dump(cfg)
    assert "${env_port}" in rendered


def test_lazy_explicit_resolve_method():
    """Underlying .resolve() returns T directly."""
    lz = Lazy(LazyInterpolable("${x + 1}", context={"x": 41}))
    assert lz.resolve() == 42


def test_lazy_on_plain_basemodel_eagerly_resolves():
    """Plain BaseModel triggers resolve_all_lazy before validation, so the field
    receives the resolved T value (not a Lazy wrapper). Use LazyDraconModel to
    keep the wrapper around for on-access resolution."""

    class Cfg(BaseModel):
        port: Lazy[int]

    loader = DraconLoader(context={"env_port": 9000, "Cfg": Cfg})
    cfg = loader.loads("!Cfg\nport: ${env_port}")
    assert cfg.port == 9000


def test_lazy_wrapper_assigned_directly_on_plain_basemodel_survives():
    """When a Lazy wrapper is constructed directly (e.g. by Lazy[T] schema),
    it survives Pydantic validation on a plain BaseModel."""

    class Cfg(BaseModel):
        port: Lazy[int]

    cfg = Cfg(port=Lazy(LazyInterpolable("${x}", context={"x": 9000})))
    assert isinstance(cfg.port, Lazy)
    assert cfg.port.resolve() == 9000
