# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset

"""Lexical scoping for ``LazyInterpolable``.

A ``LazyInterpolable`` is a closure: it must resolve against the scope
where it was authored, not the scope active when it's eventually
forced. Aliasing the caller's mutable context dict at construction
breaks that contract -- downstream context mutations (most visibly,
template kwarg binding) leak into the lazy and can poison its own
expression by shadowing names it depends on.

See ``refactors/lexical-scoping-for-template-kwargs.md`` for the
analysis. The fix is a one-line snapshot in ``__init__``; these tests
pin the closure-correctness contract so it can't quietly regress.
"""

from __future__ import annotations

import dracon
from dracon.lazy import LazyInterpolable


def test_lazy_captures_authoring_scope_not_force_scope():
    """Mutating the loader context after a lazy is constructed must not
    affect that lazy's resolution. Establishes the data-structure-level
    contract independently of any composition pipeline."""
    ctx = {"x": 1}
    lzy = LazyInterpolable("${x}", context=ctx)
    ctx["x"] = 999
    assert lzy.resolve() == 1


def test_lazy_context_snapshot_is_independent_dict():
    """Constructing a second lazy and mutating its context must not
    affect the first lazy. Verifies the snapshot is a fresh dict, not a
    shared reference."""
    ctx = {"x": 1}
    a = LazyInterpolable("${x}", context=ctx)
    b = LazyInterpolable("${x}", context=ctx)
    ctx["x"] = 42
    # both snapshots predate the mutation
    assert a.resolve() == 1
    assert b.resolve() == 1


def test_template_kwarg_shadowing_via_outer_scope_reference():
    """Reproducer for the original bug. The kwarg expression
    ``${_resolved}`` is authored in the caller's scope where ``cmd`` is
    the outer ``""``, so ``_resolved`` collapses to ``"default-binary"``.
    Without the fix the kwarg lazy aliases the loader context, the
    template's parameter binding writes ``cmd = <the kwarg lazy>`` into
    that same dict, and the lazy circularly resolves ``cmd`` against
    itself -> empty string."""
    src = """
    !set_default cmd: ""
    !define _resolved: ${cmd or 'default-binary'}

    !define Worker: !fn
      !require cmd: "what to run"
      !fn :
        run: ${cmd}

    thing: !Worker
      cmd: ${_resolved}
    """
    cfg = dracon.loads(src)
    assert cfg["thing"]["run"] == "default-binary"


def test_chained_defines_resolve_through_template_boundary():
    """Multi-level !define chain still resolves correctly across a
    parameter-shadowing template invocation. By induction, each lazy in
    the chain owns its own snapshot; forcing the outermost retrieves
    the next, forces it against its own snapshot, and so on."""
    src = """
    !set_default base: 1
    !define a: ${base}
    !define b: ${a}
    !define c: ${b}

    !define T: !fn
      !require a: "shadows outer a"
      !fn :
        out: ${a}

    result: !T
      a: ${c}
    """
    cfg = dracon.loads(src)
    assert cfg["result"]["out"] == 1


def test_template_kwarg_does_not_see_template_parameter():
    """Sharper version: the kwarg expression must NOT see the
    template's parameter binding. ``cmd`` in the kwarg expression
    refers to the outer ``cmd`` (caller scope), not the template's
    parameter (which doesn't exist in caller scope)."""
    src = """
    !set_default cmd: "outer-value"

    !define Echo: !fn
      !require cmd: "inner cmd shadows outer in template body only"
      !fn :
        seen: ${cmd}

    out: !Echo
      cmd: "<<${cmd}>>"
    """
    cfg = dracon.loads(src)
    # the kwarg ``"<<${cmd}>>"`` is authored in caller scope where
    # ``cmd == "outer-value"``, so it must resolve to ``"<<outer-value>>"``.
    # the template body sees ``cmd`` bound to that resolved kwarg value.
    assert cfg["out"]["seen"] == "<<outer-value>>"
