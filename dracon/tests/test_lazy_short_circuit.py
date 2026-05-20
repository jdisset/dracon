# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset
"""Lazy identifiers must not pre-resolve before short-circuit eval.

Python ternary `a if cond else b` and `or`/`and` short-circuit by contract;
dracon's eval should honor this for Lazy* values too. Pre-resolving every
identifier referenced in the expression defeats the short-circuit and runs
side-effects (or fails) the chosen branch never asked for.
"""
import pytest

from dracon.interpolation import do_safe_eval, LazyConstructable, LazyProtocol
from dracon.lazy import LazyInterpolable


# a LazyInterpolable wrapping `${1/0}` resolves by re-evaluating the
# wrapped string. it raises ZeroDivisionError on resolve, which is exactly
# the "expensive failure we want to avoid" surrogate.
def _exploding_lazy():
    return LazyInterpolable(value="${1/0}")


class _ResolveCounter:
    """Object that counts how often resolve() is called, fits LazyProtocol."""

    def __init__(self, value):
        self.value = value
        self.calls = 0
        # protocol fields; not actually used here but satisfy isinstance checks
        self.name = "_ResolveCounter"
        self.current_path = None
        self.root_obj = None
        self.context = {}

    def resolve(self):
        self.calls += 1
        return self.value


@pytest.mark.parametrize("engine", ["asteval", "eval"])
def test_ternary_false_branch_does_not_resolve_unselected_lazy(engine):
    """`expensive if False else 42` returns 42 without resolving expensive."""
    symbols = {"expensive": _exploding_lazy(), "needs": False}
    result = do_safe_eval("expensive if needs else 42", engine, symbols=symbols)
    assert result == 42


@pytest.mark.parametrize("engine", ["asteval", "eval"])
def test_ternary_true_branch_resolves_only_selected_lazy(engine):
    """`a if True else b` resolves a (selected) but not b (unselected)."""
    a = _ResolveCounter("alive")
    b = _ResolveCounter("dead")
    symbols = {"a": a, "b": b, "cond": True}
    result = do_safe_eval("a if cond else b", engine, symbols=symbols)
    assert result == "alive"
    assert a.calls == 1
    assert b.calls == 0


@pytest.mark.parametrize("engine", ["asteval", "eval"])
def test_or_short_circuit_does_not_resolve_rhs_when_lhs_truthy(engine):
    """`truthy or expensive` returns truthy without touching expensive."""
    symbols = {"first": "ok", "expensive": _exploding_lazy()}
    result = do_safe_eval("first or expensive", engine, symbols=symbols)
    assert result == "ok"


@pytest.mark.parametrize("engine", ["asteval", "eval"])
def test_and_short_circuit_does_not_resolve_rhs_when_lhs_falsy(engine):
    """`False and expensive` returns False without touching expensive."""
    symbols = {"first": False, "expensive": _exploding_lazy()}
    result = do_safe_eval("first and expensive", engine, symbols=symbols)
    assert result is False


@pytest.mark.parametrize("engine", ["asteval", "eval"])
def test_attribute_access_on_selected_lazy_resolves(engine):
    """`expensive.attr if True else fallback` resolves expensive only."""

    class _Obj:
        attr = "hello"

    selected = _ResolveCounter(_Obj())
    fallback = _ResolveCounter("fallback")
    symbols = {"selected": selected, "fallback": fallback, "cond": True}
    result = do_safe_eval(
        "selected.attr if cond else fallback", engine, symbols=symbols
    )
    assert result == "hello"
    assert selected.calls == 1
    assert fallback.calls == 0


@pytest.mark.parametrize("engine", ["asteval", "eval"])
def test_bare_lazy_expression_still_resolves(engine):
    """`${expensive}` (no conditional) must resolve to the concrete value."""
    counter = _ResolveCounter(99)
    symbols = {"expensive": counter}
    result = do_safe_eval("expensive", engine, symbols=symbols)
    assert result == 99
    assert counter.calls == 1


@pytest.mark.parametrize("engine", ["asteval", "eval"])
def test_lazy_resolved_only_once_when_referenced_multiple_times(engine):
    """`x + x` -- x is a lazy. resolve once, reuse."""
    counter = _ResolveCounter(7)
    symbols = {"x": counter}
    result = do_safe_eval("x + x", engine, symbols=symbols)
    assert result == 14
    # ideally exactly once; the caching contract is per-call
    assert counter.calls == 1


@pytest.mark.parametrize("engine", ["asteval", "eval"])
def test_nested_ternary_resolves_only_chosen_branch(engine):
    """`a if c1 else (b if c2 else c)` with c1=False, c2=True picks b only."""
    a = _ResolveCounter("a-val")
    b = _ResolveCounter("b-val")
    c = _ResolveCounter("c-val")
    symbols = {"a": a, "b": b, "c": c, "c1": False, "c2": True}
    result = do_safe_eval("a if c1 else (b if c2 else c)", engine, symbols=symbols)
    assert result == "b-val"
    assert a.calls == 0
    assert b.calls == 1
    assert c.calls == 0


@pytest.mark.parametrize("engine", ["asteval", "eval"])
def test_or_chain_short_circuits_at_first_truthy(engine):
    """`a or b or c` with a=falsy, b=truthy resolves a and b only, not c."""
    a = _ResolveCounter(0)  # falsy
    b = _ResolveCounter("yes")
    c = _ResolveCounter("never")
    symbols = {"a": a, "b": b, "c": c}
    result = do_safe_eval("a or b or c", engine, symbols=symbols)
    assert result == "yes"
    assert a.calls == 1
    assert b.calls == 1
    assert c.calls == 0


@pytest.mark.parametrize("engine", ["asteval", "eval"])
def test_mixed_unconditional_and_conditional_references(engine):
    """`always + (cond_branch if False else 0)` -- `always` resolves,
    `cond_branch` does not."""
    always = _ResolveCounter(10)
    cond_branch = _ResolveCounter("crash")
    symbols = {"always": always, "cond_branch": cond_branch, "flag": False}
    result = do_safe_eval(
        "always + (cond_branch if flag else 0)", engine, symbols=symbols
    )
    assert result == 10
    assert always.calls == 1
    assert cond_branch.calls == 0


def test_e2e_yaml_ternary_lazy_short_circuit():
    """End-to-end via dracon.load: a LazyConstructable that would fail on
    construction must not be triggered when guarded by a falsy condition."""
    import dracon
    from dracon.loader import DraconLoader
    from dracon.include import compose_from_include_str

    class _Explodes:
        """A class that crashes when instantiated."""

        def __init__(self, **kwargs):
            raise RuntimeError("must not construct")

    yaml_src = """
!define needs: false
!define expensive: !Explodes
  arg: 1
result: ${expensive if needs else 42}
"""
    loader = DraconLoader(
        enable_interpolation=True,
        context={"Explodes": _Explodes},
    )
    config = loader.loads(yaml_src)
    from dracon.dracontainer import resolve_all_lazy

    resolve_all_lazy(config)
    assert config["result"] == 42
