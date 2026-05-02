"""!require / !set_default must NOT consider Python builtins as user-defined.

Bug class: ``var in loader.context`` is True for ``min``/``max``/``sum``/...
because the default ``dynamic_import`` symbol source resolves any name
that happens to live in ``builtins``. The historical leak: a template
that declared ``!set_default min: 1`` would read
``<built-in function min>`` from the source instead of using its own
default; ``!require min`` would silently pass even when no value was
supplied.

Both checks must consult the *explicit* layer of the symbol table only.
"""

import pytest

import dracon


def test_set_default_uses_default_when_only_python_builtin_shadows():
    """`!set_default min: 1` must produce 1, not Python's builtin ``min``."""
    res = dracon.loads(
        """
        !set_default min: 1
        !set_default max: 9
        result_min: ${min}
        result_max: ${max}
        """
    )
    assert res["result_min"] == 1
    assert res["result_max"] == 9


def test_require_unsatisfied_by_python_builtin():
    """`!require min` must NOT pass just because ``min`` is a builtin."""
    with pytest.raises(Exception):
        dracon.loads("!require min: 'min count'\nresult: ${min}\n")


def test_set_default_in_fn_template_uses_default():
    """!set_default inside a !fn template body must shadow Python builtins.

    Reduced from broodmon's ``!KeepRunning`` sugar:
        !define KR: !fn
          !set_default min: 1
          !set_default max: null
          !fn : { min: ${min}, max: ${max} }
    Pre-fix, ``${min}`` evaluated to ``<built-in function min>``.
    """
    res = dracon.loads(
        """
        !define KR: !fn
          !require source: "x"
          !set_default min: 1
          !set_default max: null
          !fn :
            source: ${source}
            min: ${min}
            max: ${max}

        out: !KR
          source: workers
        """
    )
    out = res["out"]
    assert out["min"] == 1
    assert out["max"] is None
    assert out["source"] == "workers"


def test_set_default_overridable_via_define_or_argv():
    """!set_default still defers to a real outer definition."""
    res = dracon.loads(
        """
        !define min: 7
        !set_default min: 1
        out: ${min}
        """
    )
    assert res["out"] == 7


def test_set_default_in_fn_overridable_via_kwargs():
    """!set_default inside !fn defers to the kwarg passed at call time."""
    res = dracon.loads(
        """
        !define KR: !fn
          !require source: "x"
          !set_default min: 1
          !fn :
            min: ${min}

        out: !KR
          source: workers
          min: 42
        """
    )
    assert res["out"]["min"] == 42
