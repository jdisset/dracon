# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset
"""Block-scalar fidelity.

ruamel's round-trip scanner injects a BEL (``\\a`` / ``\\x07``) fold-marker
into every folded block scalar (``>``/``>-``/``>+``) and relies on its own
constructor to strip it. dracon composes its own scalar nodes, so it must do
the same stripping -- but only for folded scalars, never for a legitimate BEL
that a user wrote in a double-quoted string."""

import dracon as dr


def test_folded_scalar_strip_no_interpolation():
    cfg = dr.loads("v: >-\n  alpha\n  beta\n  gamma\n")
    assert cfg["v"] == "alpha beta gamma"
    assert "\a" not in cfg["v"]


def test_folded_scalar_strip_with_interpolation():
    cfg = dr.loads(
        "!define x: 2\nv: >-\n  alpha\n  beta=${x}\n  gamma\n",
        enable_interpolation=True,
    )
    assert cfg["v"] == "alpha beta=2 gamma"
    assert "\a" not in cfg["v"]


def test_folded_keep_style_clip():
    # ``>`` (clip) keeps a single trailing newline
    cfg = dr.loads("v: >\n  alpha\n  beta\n")
    assert cfg["v"] == "alpha beta\n"


def test_folded_keep_style_strip():
    # ``>+`` (keep) keeps all trailing newlines
    cfg = dr.loads("v: >+\n  alpha\n  beta\n\n")
    assert cfg["v"] == "alpha beta\n\n"
    assert "\a" not in cfg["v"]


def test_literal_block_unaffected():
    cfg = dr.loads("v: |\n  alpha\n  beta\n")
    assert cfg["v"] == "alpha\nbeta\n"


def test_double_quoted_bell_preserved():
    # a real BEL the user explicitly wrote must survive untouched
    cfg = dr.loads('v: "x\\ay"\n')
    assert cfg["v"] == "x\ay"
    assert "\a" in cfg["v"]


def test_folded_blank_line_paragraph_break():
    # a blank line inside a folded scalar is a real newline, not a fold space
    cfg = dr.loads("v: >-\n  alpha\n  beta\n\n  gamma\n")
    assert cfg["v"] == "alpha beta\ngamma"
    assert "\a" not in cfg["v"]


def test_folded_scalar_as_mapping_key():
    cfg = dr.loads("? >-\n    long\n    key\n: value\n")
    assert cfg["long key"] == "value"
