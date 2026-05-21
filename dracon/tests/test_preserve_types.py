# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset
"""Round-trip-stable live type references via `preserve_types`."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

import dracon as dr
from dracon import DraconLoader, TypeResolver, UnknownTypeError, dotted_path, import_resolver


class SampleA(BaseModel):
    name: str = "a"


class SampleB(BaseModel):
    n: int = 0


class Holder(BaseModel):
    model_config = {"arbitrary_types_allowed": True}
    cls: type | str


def test_dotted_path_builtin():
    assert dotted_path(int) == "int"
    assert dotted_path(str) == "str"


def test_dotted_path_module():
    assert dotted_path(SampleA) == f"{SampleA.__module__}.SampleA"


def test_import_resolver_roundtrip():
    assert import_resolver(dotted_path(SampleA)) is SampleA
    assert import_resolver("int") is int


def test_import_resolver_unknown():
    with pytest.raises(UnknownTypeError):
        import_resolver("nonexistent_module_xyz.Foo")
    with pytest.raises(UnknownTypeError):
        import_resolver("int_zzz_nope")


def test_dump_emits_type_tag():
    loader = DraconLoader(preserve_types=True)
    out = loader.dump(SampleA)
    assert "!Type" in out
    assert dotted_path(SampleA) in out


def test_dump_skipped_when_disabled():
    # without preserve_types, raw classes don't get the !Type tag
    loader = DraconLoader(preserve_types=False)
    out = loader.dump(SampleA)
    assert "!Type" not in out


def test_roundtrip_identity_default_resolver():
    loader = DraconLoader(preserve_types=True)
    yaml_str = loader.dump(SampleA)
    back = DraconLoader(preserve_types=True).loads(yaml_str)
    assert back is SampleA


def test_roundtrip_inside_pydantic_model():
    loader = DraconLoader(preserve_types=True)
    spec = Holder(cls=SampleA)
    yaml_str = loader.dump(spec)
    back = DraconLoader(preserve_types=True).loads(yaml_str)
    assert isinstance(back, Holder)
    assert back.cls is SampleA


def test_per_loader_identity_cache():
    loader = DraconLoader(preserve_types=True)
    yaml_str = f"a: !Type {dotted_path(SampleA)}\nb: !Type {dotted_path(SampleA)}\n"
    result = loader.loads(yaml_str)
    assert result["a"] is SampleA
    assert result["b"] is SampleA


def test_allowlist_resolver_allows():
    resolver = TypeResolver.allowlist({dotted_path(SampleA)})
    loader = DraconLoader(preserve_types=True, type_resolver=resolver)
    yaml_str = f"!Type {dotted_path(SampleA)}"
    assert loader.loads(yaml_str) is SampleA


def test_allowlist_resolver_blocks():
    resolver = TypeResolver.allowlist({dotted_path(SampleA)})
    loader = DraconLoader(preserve_types=True, type_resolver=resolver)
    with pytest.raises(UnknownTypeError):
        loader.loads(f"!Type {dotted_path(SampleB)}")


def test_table_resolver():
    resolver = TypeResolver.table({"X": SampleA})
    loader = DraconLoader(preserve_types=True, type_resolver=resolver)
    assert loader.loads("!Type X") is SampleA
    with pytest.raises(UnknownTypeError):
        loader.loads("!Type Missing")


def test_sandboxed_loader_no_resolver_errors():
    loader = DraconLoader(preserve_types=True, symbol_sources=[])
    with pytest.raises(UnknownTypeError):
        loader.loads(f"!Type {dotted_path(SampleA)}")


def test_fallback_mode_degrades_to_string():
    loader = DraconLoader(preserve_types='fallback', symbol_sources=[])
    result = loader.loads(f"!Type {dotted_path(SampleA)}")
    assert result == dotted_path(SampleA)


def test_stable_reference_roundtrip():
    class Registry:
        pass

    registry = Registry()
    loader_a = DraconLoader(preserve_types=True)
    loader_a.register_stable_reference(registry, "app.registry")

    yaml_str = loader_a.dump(registry)
    assert "!Ref app.registry" in yaml_str

    loader_b = DraconLoader(preserve_types=True)
    loader_b.register_stable_reference(registry, "app.registry")
    back = loader_b.loads(yaml_str)
    assert back is registry


def test_stable_reference_unknown_errors():
    loader = DraconLoader(preserve_types=True)
    with pytest.raises(Exception):
        loader.loads("!Ref nobody.knows")


def test_stable_reference_nested_in_dict():
    sentinel = object()
    loader = DraconLoader(preserve_types=True)
    loader.register_stable_reference(sentinel, "S")
    yaml_str = loader.dump({"k": sentinel, "other": 1})
    assert "!Ref S" in yaml_str
    back = loader.loads(yaml_str)
    assert back["k"] is sentinel
    assert back["other"] == 1


def test_copy_preserves_resolver_state():
    loader = DraconLoader(preserve_types=True, type_resolver=TypeResolver.table({"X": SampleA}))
    loader.register_stable_reference(SampleB, "B")
    clone = loader.copy()
    assert clone.preserve_types is True
    assert clone.loads("!Type X") is SampleA
    assert clone.loads("!Ref B") is SampleB


def test_vocab_entry_still_wins_for_instances():
    # registered models still dump as !VocabName, not !Type ...
    from dracon.symbols import auto_symbol
    from dracon.symbol_table import SymbolEntry
    loader = DraconLoader(preserve_types=True)
    loader.context.define(
        SymbolEntry(name="MyA", symbol=auto_symbol(SampleA), canonical=True)
    )
    instance = SampleA(name="hi")
    out = loader.dump(instance)
    assert "!MyA" in out
    assert "!Type" not in out


def test_module_level_dump_loads_with_kwarg():
    yaml_str = dr.dump(SampleA, preserve_types=True)
    assert "!Type" in yaml_str
    back = dr.loads(yaml_str, preserve_types=True)
    assert back is SampleA
