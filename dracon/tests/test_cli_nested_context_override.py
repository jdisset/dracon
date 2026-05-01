"""regression: ++a.b=v / --a.b=v should deep-merge into mapping context vars.
bugs/_archive/cli-nested-context-override-silent-noop.md"""
from __future__ import annotations

from pathlib import Path
from typing import List

import pytest
from pydantic import BaseModel

from dracon import make_program


class _RecipeOut(BaseModel):
    result: List[float] = []


class _NestedOut(BaseModel):
    result: List[float] = []
    nested: dict = {}


@pytest.fixture
def recipe_with_mapping(tmp_path: Path) -> Path:
    p = tmp_path / "recipe.yaml"
    p.write_text(
        """
!set_default widths:
  a: 1.0
  b: 2.0
  c: 3.0

result: ${[widths['a'], widths['b'], widths['c']]}
"""
    )
    return p


@pytest.fixture
def recipe_with_nested_mapping(tmp_path: Path) -> Path:
    p = tmp_path / "recipe_nested.yaml"
    p.write_text(
        """
!set_default canvas:
  axes:
    x: 1.0
    y: 2.0
  margin:
    top: 5.0
    bottom: 10.0

result: ${[canvas['axes']['x'], canvas['axes']['y'], canvas['margin']['top'], canvas['margin']['bottom']]}
nested: ${canvas}
"""
    )
    return p


def _make_program(model_cls):
    return make_program(model_cls, name="recipe-cli")


def test_full_mapping_replacement_works(recipe_with_mapping):
    prog = _make_program(_RecipeOut)
    cfg, _ = prog.parse_args(
        [f"+{recipe_with_mapping}", "++widths={a: 1, b: 99, c: 3}"]
    )
    assert cfg.result == [1.0, 99.0, 3.0]


def test_default_values_when_no_override(recipe_with_mapping):
    prog = _make_program(_RecipeOut)
    cfg, _ = prog.parse_args([f"+{recipe_with_mapping}"])
    assert cfg.result == [1.0, 2.0, 3.0]


def test_plusplus_dotted_override_into_mapping_context_var(recipe_with_mapping):
    prog = _make_program(_RecipeOut)
    cfg, _ = prog.parse_args([f"+{recipe_with_mapping}", "++widths.b=99"])
    assert cfg.result == [1.0, 99.0, 3.0]


def test_dashdash_dotted_override_into_mapping_context_var(recipe_with_mapping):
    prog = _make_program(_RecipeOut)
    cfg, _ = prog.parse_args([f"+{recipe_with_mapping}", "--widths.b=99"])
    assert cfg.result == [1.0, 99.0, 3.0]


def test_dotted_override_recursive(recipe_with_nested_mapping):
    prog = _make_program(_NestedOut)
    cfg, _ = prog.parse_args([f"+{recipe_with_nested_mapping}", "++canvas.axes.x=42"])
    assert cfg.result == [42.0, 2.0, 5.0, 10.0]


def test_multiple_dotted_overrides_same_root(recipe_with_mapping):
    prog = _make_program(_RecipeOut)
    cfg, _ = prog.parse_args(
        [f"+{recipe_with_mapping}", "++widths.a=10", "++widths.c=30"]
    )
    assert cfg.result == [10.0, 2.0, 30.0]


def test_dashdash_and_plusplus_dotted_overrides_equivalent(recipe_with_mapping):
    prog1 = _make_program(_RecipeOut)
    prog2 = _make_program(_RecipeOut)
    cfg1, _ = prog1.parse_args([f"+{recipe_with_mapping}", "++widths.b=77"])
    cfg2, _ = prog2.parse_args([f"+{recipe_with_mapping}", "--widths.b=77"])
    assert cfg1.result == cfg2.result == [1.0, 77.0, 3.0]


def test_dotted_override_with_yaml_value(recipe_with_nested_mapping):
    prog = _make_program(_NestedOut)
    cfg, _ = prog.parse_args(
        [f"+{recipe_with_nested_mapping}", "++canvas.axes={x: 100, y: 200}"]
    )
    assert cfg.result == [100.0, 200.0, 5.0, 10.0]


def test_dotted_override_after_full_replacement(recipe_with_mapping):
    prog = _make_program(_RecipeOut)
    cfg, _ = prog.parse_args(
        [f"+{recipe_with_mapping}", "++widths={a: 10, b: 20, c: 30}", "++widths.b=99"]
    )
    assert cfg.result == [10.0, 99.0, 30.0]


class _DbConfig(BaseModel):
    host: str = "default-host"
    port: int = 5432


class _AppWithDb(BaseModel):
    database: _DbConfig = _DbConfig()
    workers: int = 1


def test_dashdash_dotted_override_into_model_field_unchanged():
    prog = make_program(_AppWithDb, name="db-app")
    cfg, _ = prog.parse_args(["--database.port", "5433"])
    assert cfg.database.port == 5433
    assert cfg.database.host == "default-host"


def test_dotted_override_creates_intermediate_mapping(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text(
        "!set_default canvas:\n  axes:\n    x: 1.0\n"
        "result: ${[canvas['axes']['x'], canvas.get('extra', {}).get('y', -1)]}\n"
    )
    prog = make_program(_RecipeOut, name="r")
    cfg, _ = prog.parse_args([f"+{p}", "++canvas.extra.y=42"])
    assert cfg.result == [1.0, 42.0]


def test_no_unused_var_warning_for_dotted_override(tmp_path, capsys):
    p = tmp_path / "r.yaml"
    p.write_text(
        "!set_default widths:\n  a: 1.0\n  b: 2.0\n"
        "result: ${[widths['a'], widths['b']]}\n"
    )
    prog = make_program(_RecipeOut, name="r")
    cfg, _ = prog.parse_args([f"+{p}", "++widths.b=99"])
    captured = capsys.readouterr()
    assert "widths.b" not in captured.out + captured.err
    assert cfg.result == [1.0, 99.0]


def test_merge_dotted_into_context_basic():
    from dracon.utils import merge_dotted_into_context
    ctx = {"widths": {"a": 1, "b": 2, "c": 3}}
    leftover = merge_dotted_into_context({"widths.b": 99}, ctx)
    assert leftover == {}
    assert ctx["widths"] == {"a": 1, "b": 99, "c": 3}


def test_merge_dotted_into_context_deep():
    from dracon.utils import merge_dotted_into_context
    ctx = {"canvas": {"axes": {"x": 1, "y": 2}}}
    merge_dotted_into_context({"canvas.axes.x": 42}, ctx)
    assert ctx["canvas"] == {"axes": {"x": 42, "y": 2}}


def test_merge_dotted_into_context_unconsumed_for_unknown_root():
    from dracon.utils import merge_dotted_into_context
    ctx = {"widths": {"a": 1}}
    leftover = merge_dotted_into_context({"unknown.x": 9}, ctx)
    assert leftover == {"unknown.x": 9}
    assert "unknown" not in ctx


def test_merge_dotted_into_context_unconsumed_for_non_mapping_root():
    from dracon.utils import merge_dotted_into_context
    ctx = {"port": 8080}
    leftover = merge_dotted_into_context({"port.x": 9}, ctx)
    assert leftover == {"port.x": 9}
    assert ctx["port"] == 8080


def test_merge_dotted_into_context_creates_intermediate_dicts():
    from dracon.utils import merge_dotted_into_context
    ctx = {"a": {"b": 1}}
    merge_dotted_into_context({"a.c.d.e": 5}, ctx)
    assert ctx["a"] == {"b": 1, "c": {"d": {"e": 5}}}


def test_merge_dotted_into_context_in_place():
    from dracon.utils import merge_dotted_into_context
    inner = {"a": 1, "b": 2}
    ctx = {"widths": inner}
    merge_dotted_into_context({"widths.b": 99}, ctx)
    assert ctx["widths"] is inner
    assert inner == {"a": 1, "b": 99}
