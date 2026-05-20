# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset
"""Merge keys with an interpolation as right-hand side.

The style guide warns against `<<: ${some_dict}` and the docs predict
"shallow dict.update overlay". The actual behavior was worse: the merge
collapsed the entire parent mapping (or nested-model node) to whatever
the interpolation resolved to, silently dropping all sibling field
assignments. Fix: realize lazy merge sources at compose time so their
content can be merged like any other mapping.
"""
import textwrap
from pathlib import Path

import pytest
from pydantic import BaseModel

import dracon


def _loads(content: str, **kwargs):
    loader = dracon.DraconLoader(enable_interpolation=True, **kwargs)
    return loader.loads(textwrap.dedent(content).lstrip())


def test_merge_with_empty_interpolated_dict_preserves_siblings():
    """`<<{+<}: ${empty_dict}` on a plain mapping must not eat siblings."""
    result = _loads(
        """
        !set_default extra_overrides: {}
        conf:
          style: hi
          flag: world
          <<{+<}: ${extra_overrides}
        """
    )
    assert dict(result["conf"]) == {"style": "hi", "flag": "world"}


def test_merge_with_populated_interpolated_dict_overrides_siblings():
    """`<<{+<}: ${dict}` with NEW-wins must override matching keys."""
    result = _loads(
        """
        !set_default extra_overrides:
          style: from_overrides
        conf:
          style: hi
          flag: world
          <<{+<}: ${extra_overrides}
        """
    )
    # NEW-wins: style overridden, flag preserved
    assert dict(result["conf"]) == {"style": "from_overrides", "flag": "world"}


def test_merge_with_existing_wins_interpolated_dict_preserves_existing():
    """`<<{+>}: ${dict}` (EXISTING-wins) keeps the sibling values."""
    result = _loads(
        """
        !set_default extra_overrides:
          style: from_overrides
          new_key: added
        conf:
          style: hi
          flag: world
          <<{+>}: ${extra_overrides}
        """
    )
    assert dict(result["conf"]) == {
        "style": "hi",
        "flag": "world",
        "new_key": "added",
    }


class _Conf(BaseModel):
    style: str = "DEFAULT_STYLE"
    flag: bool = False


class _Fig(BaseModel):
    name: str
    conf: _Conf = _Conf()


def test_merge_into_nested_tagged_pydantic_model_preserves_siblings():
    """The minimal trigger from the bug report: nested !Config gets a
    `<<{+<}: ${extra_overrides}` and its sibling `${...}` fields must
    keep their values (not fall back to the Pydantic default)."""
    result = _loads(
        """
        !Fig
        !set_default variant: DEFAULT_VAR
        !set_default extra_overrides: {}
        name: ${variant}
        conf: !Conf
          style: ${variant}
          flag: ${variant == 'excl'}
          <<{+<}: ${extra_overrides}
        """,
        context={"Fig": _Fig, "Conf": _Conf, "variant": "main"},
    )
    assert result.name == "main"
    assert result.conf.style == "main"
    assert result.conf.flag is False


def test_merge_into_nested_tagged_pydantic_model_with_overrides():
    """And the same but `extra_overrides` actually carries something."""
    result = _loads(
        """
        !Fig
        !set_default variant: main
        !set_default extra_overrides:
          style: overridden
        name: ${variant}
        conf: !Conf
          style: ${variant}
          flag: ${variant == 'excl'}
          <<{+<}: ${extra_overrides}
        """,
        context={"Fig": _Fig, "Conf": _Conf},
    )
    assert result.name == "main"
    assert result.conf.style == "overridden"


def test_merge_with_each_variant_repro_from_bug_report():
    """Full reproduction from bugs/each-define-leaks-...md -- three
    iterations over an outer `!each` with `!define`s setting variant,
    nested `!Conf` with a sibling `<<{+<}: ${empty_dict}`."""
    import tempfile, textwrap as _tw, os
    with tempfile.TemporaryDirectory() as d:
        Path(d, "frag.yaml").write_text(_tw.dedent("""
            !Fig
            !set_default variant: DEFAULT_VAR
            !set_default extra_overrides: {}
            name: ${variant}
            conf: !Conf
              style: ${variant}
              flag: ${variant == 'excl'}
              <<{+<}: ${extra_overrides}
        """).lstrip())
        root = _tw.dedent(f"""
            !define jobs:
              - {{variant: main}}
              - {{variant: excl}}
              - {{variant: simple}}
            figures:
              !each(job) ${{jobs}}:
                - !define variant: ${{job['variant']}}
                  <<: !include file:{d}/frag.yaml
        """).lstrip()
        loader = dracon.DraconLoader(
            enable_interpolation=True,
            context={"Fig": _Fig, "Conf": _Conf},
        )
        result = loader.loads(root)
        figs = []
        for f in result["figures"]:
            if isinstance(f, dracon.DeferredNode):
                f = f.construct()
            figs.append(f)
        assert [f.name for f in figs] == ["main", "excl", "simple"]
        assert [f.conf.style for f in figs] == ["main", "excl", "simple"]
        assert [f.conf.flag for f in figs] == [False, True, False]
