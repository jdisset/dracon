"""regression: !set_default with mapping-body default must unwrap node trees."""
from __future__ import annotations

from pathlib import Path

import pytest

import dracon
from dracon import make_program
from pydantic import BaseModel
from typing import List


@pytest.fixture
def scalar_yaml(tmp_path: Path) -> Path:
    p = tmp_path / "scalar.yaml"
    p.write_text("!set_default slice_grid: [3, 3]\n")
    return p


@pytest.fixture
def mapping_yaml(tmp_path: Path) -> Path:
    p = tmp_path / "mapping.yaml"
    p.write_text(
        '!set_default slice_grid:\n  default: [3, 3]\n  help: "test"\n'
    )
    return p


def _load(layer: Path) -> dict:
    return dracon.loads(
        f"<<(<): !include file:{layer}\nx: ${{slice_grid}}\n"
    )


def test_mapping_body_default_list_is_unwrapped(mapping_yaml):
    out = _load(mapping_yaml)
    assert list(out['x']) == [3, 3]
    for el in out['x']:
        assert type(el) is int


def test_scalar_body_default_list_unwrapped(scalar_yaml):
    out = _load(scalar_yaml)
    assert list(out['x']) == [3, 3]
    for el in out['x']:
        assert type(el) is int


def test_mapping_and_scalar_body_equivalent(scalar_yaml, mapping_yaml):
    s = _load(scalar_yaml)
    m = _load(mapping_yaml)
    assert list(s['x']) == list(m['x'])
    assert [type(e) for e in s['x']] == [type(e) for e in m['x']]


def test_mapping_body_default_dict_is_unwrapped(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text(
        '!set_default canvas:\n  default: {x: 1, y: 2}\n  help: "h"\n'
    )
    out = dracon.loads(
        f"<<(<): !include file:{p}\nv: ${{canvas}}\n"
    )
    assert dict(out['v']) == {'x': 1, 'y': 2}
    for v in out['v'].values():
        assert type(v) is int


def test_mapping_body_default_nested_dict_is_unwrapped(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text(
        '!set_default cfg:\n  default:\n    a: [1, 2]\n    b: {x: 10}\n'
    )
    out = dracon.loads(
        f"<<(<): !include file:{p}\nv: ${{cfg}}\n"
    )
    v = out['v']
    assert list(v['a']) == [1, 2]
    assert dict(v['b']) == {'x': 10}
    assert all(type(e) is int for e in v['a'])
    assert all(type(e) is int for e in v['b'].values())


def test_mapping_body_default_subscript_works(tmp_path):
    """The reported failure mode: int(slice_grid[0]) must work."""
    p = tmp_path / "m.yaml"
    p.write_text(
        '!set_default slice_grid:\n  default: [3, 3]\n  help: "h"\n'
    )
    out = dracon.loads(
        f"<<(<): !include file:{p}\nv: ${{int(slice_grid[0])}}\n"
    )
    assert out['v'] == 3
    assert type(out['v']) is int


def test_mapping_body_default_works_via_cli_program(tmp_path):
    """End-to-end: a recipe layered into a @dracon_program should work."""
    p = tmp_path / "m.yaml"
    p.write_text(
        '!set_default slice_grid:\n  default: [3, 3]\n  help: "h"\n'
        'result: ${[slice_grid[0], slice_grid[1]]}\n'
    )

    class Out(BaseModel):
        result: List[int] = []

    prog = make_program(Out, name="r")
    cfg, _ = prog.parse_args([f"+{p}"])
    assert cfg.result == [3, 3]
