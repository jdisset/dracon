# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset
"""regression: <<(<): !include must expose set_default vars to in-file compose-time
instructions (!define / !if / !set_default mapping-body / !each)."""
from __future__ import annotations

from pathlib import Path

import pytest
import dracon


@pytest.fixture
def has_x(tmp_path: Path) -> Path:
    p = tmp_path / "has_x.yaml"
    p.write_text("!set_default x: true\n")
    return p


@pytest.fixture
def has_n(tmp_path: Path) -> Path:
    p = tmp_path / "has_n.yaml"
    p.write_text("!set_default n: 3\n")
    return p


@pytest.fixture
def has_items(tmp_path: Path) -> Path:
    p = tmp_path / "has_items.yaml"
    p.write_text("!set_default items: [a, b, c]\n")
    return p


def test_field_interpolation_sees_propagated_setdefault(has_x):
    out = dracon.loads(
        f"<<(<): !include file:{has_x}\nresult: ${{x}}\n"
    )
    assert out['result'] is True


def test_define_sees_propagated_setdefault(has_x):
    out = dracon.loads(
        f"<<(<): !include file:{has_x}\n!define y: ${{x}}\nresult: ${{y}}\n"
    )
    assert out['result'] is True


def test_if_sees_propagated_setdefault(has_x):
    out = dracon.loads(
        f"<<(<): !include file:{has_x}\n"
        f"!if ${{x}}:\n  branch: taken\n"
    )
    assert out['branch'] == 'taken'


def test_each_sees_propagated_setdefault(has_items):
    out = dracon.loads(
        f"<<(<): !include file:{has_items}\n"
        f"items_out:\n"
        f"  !each(it) ${{items}}:\n"
        f"    - ${{it}}\n"
    )
    assert list(out['items_out']) == ['a', 'b', 'c']


def test_set_default_mapping_body_default_sees_propagated(has_n):
    out = dracon.loads(
        f"<<(<): !include file:{has_n}\n"
        f"!set_default m:\n  default: ${{n}}\n  help: h\n"
        f"result: ${{m}}\n"
    )
    assert out['result'] == 3


def test_chained_define_via_propagated_setdefault(has_x):
    out = dracon.loads(
        f"<<(<): !include file:{has_x}\n"
        f"!define y: ${{x}}\n!define z: ${{y}}\n"
        f"result: ${{z}}\n"
    )
    assert out['result'] is True


def test_genuine_undefined_name_still_errors():
    """Deferral must not mask real errors: a name that's never defined still raises."""
    from dracon.diagnostics import UndefinedNameError, CompositionError
    with pytest.raises((UndefinedNameError, CompositionError)):
        dracon.loads("!define y: ${nope}\nresult: ${y}\n")


def test_propagated_setdefault_overridden_by_outer_define(has_x):
    """Outer !define still wins over the propagated !set_default."""
    out = dracon.loads(
        f"<<(<): !include file:{has_x}\n"
        f"!define x: 42\n"
        f"!define y: ${{x}}\n"
        f"result: ${{y}}\n"
    )
    assert out['result'] == 42
