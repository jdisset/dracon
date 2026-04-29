"""
Regression tests for the SetDefault + outer-context override bug.

When `!set_default var: default` runs while `loader.context` already
carries an authoritative `var` (e.g. from CLI `++var=...` or a passed-in
`context={'var': ...}`), the authoritative value must win EVERYWHERE:

- plain `${var}` interpolations (always worked),
- `!include file:${var}` at top level (always worked),
- `!include file:${var}` inside a `!define NAME: !TypedTag { ... }` body
  (was broken — the !include resolved to the default),
- `!include file:${var}` inside chains of typed !defines,
- `!include file:${var}` inside !each expansions under typed !defines.

The common root is `comp_res.defined_vars` being populated with the
set_default default value (not the override) and then re-propagated
into the subtree via a "new wins" merge at LazyConstructable resolve time.
"""

from typing import Any
import pytest
from pydantic import BaseModel, ConfigDict
from dracon.loader import DraconLoader
from dracon.include import compose_from_include_str


class WrapperModel(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    content: Any = None


def _load(config_path: str, overrides: dict) -> dict:
    loader = DraconLoader(
        enable_interpolation=True,
        context={'TestWrapper': WrapperModel, **overrides},
    )
    compres = compose_from_include_str(loader, f"pkg:{config_path}")
    return loader.load_composition_result(compres)


def test_setdefault_default_is_used_when_no_override():
    """Baseline: with no override, the set_default value is used."""
    cfg = _load(
        "dracon:tests/test_setdefault_override_typed_define.yaml",
        overrides={},
    )
    assert cfg["wrapper_content"].content["label"] == "this is the DEFAULT file"


def test_setdefault_override_reaches_include_inside_typed_define():
    """The reported bug: !include file:${var} inside !define NAME: !TypedTag body."""
    from pathlib import Path
    base = Path(__file__).resolve().parent
    override = str(base / "test_setdefault_override_override.yaml")
    cfg = _load(
        "dracon:tests/test_setdefault_override_typed_define.yaml",
        overrides={'target_file': override},
    )
    assert cfg["selected_path"] == override
    assert cfg["wrapper_content"].content["label"] == "this is the OVERRIDE file"


def test_setdefault_override_reaches_include_inside_plain_define():
    """Control: !include file:${var} inside !define (untyped) must also respect override."""
    from pathlib import Path
    base = Path(__file__).resolve().parent
    override = str(base / "test_setdefault_override_override.yaml")
    cfg = _load(
        "dracon:tests/test_setdefault_override_plain_define.yaml",
        overrides={'target_file': override},
    )
    assert cfg["selected_path"] == override
    assert cfg["wrapper_content"]["label"] == "this is the OVERRIDE file"


def test_setdefault_override_reaches_nested_typed_define_chain():
    """Chain of typed !defines where inner uses !include file:${var} and
    outer references inner.  Both layers must see the override."""
    from pathlib import Path
    base = Path(__file__).resolve().parent
    override = str(base / "test_setdefault_override_override.yaml")
    cfg = _load(
        "dracon:tests/test_setdefault_override_nested_define.yaml",
        overrides={'target_file': override},
    )
    assert cfg["wrapper_content"].content["nested"] == "this is the OVERRIDE file"


def test_setdefault_override_reaches_include_inside_each_under_typed_define():
    """!each expansions inside typed !define bodies must also honor the override."""
    from pathlib import Path
    base = Path(__file__).resolve().parent
    override = str(base / "test_setdefault_override_override.yaml")
    cfg = _load(
        "dracon:tests/test_setdefault_override_each_include.yaml",
        overrides={'target_file': override},
    )
    item = cfg["wrapper_content"].content["item_1"]
    assert item["label"] == "this is the OVERRIDE file"


def test_setdefault_does_not_shadow_loader_context_in_defined_vars():
    """SSOT invariant: if the variable already exists in loader.context,
    !set_default must not record a different value in comp_res.defined_vars.
    (Guards against the class of bugs where downstream consumers of
    defined_vars — like LazyConstructable — re-inject a stale default.)"""
    loader = DraconLoader(
        enable_interpolation=True,
        context={'TestWrapper': WrapperModel, 'target_file': '/abs/override/path'},
    )
    compres = compose_from_include_str(
        loader, "pkg:dracon:tests/test_setdefault_override_typed_define.yaml"
    )
    recorded = compres.defined_vars.get('target_file')
    assert recorded == '/abs/override/path', (
        f"defined_vars must mirror the authoritative loader.context value, "
        f"got {recorded!r}"
    )


def test_setdefault_loader_context_exports_as_hard_binding():
    from dracon.stack import exported_context_from

    loader = DraconLoader(
        enable_interpolation=True,
        context={'TestWrapper': WrapperModel, 'target_file': '/abs/override/path'},
    )
    compres = compose_from_include_str(
        loader, "pkg:dracon:tests/test_setdefault_override_typed_define.yaml"
    )
    exported = exported_context_from(compres)
    assert exported['target_file'] == '/abs/override/path'
    assert 'target_file' not in getattr(exported, '_soft_keys', set())
