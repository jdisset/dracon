# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""Tests for permissive evaluation mode (two-phase resolution)."""

import pytest
from dracon.diagnostics import EvaluationError, UndefinedNameError
from dracon.interpolation import (
    do_safe_eval,
    evaluate_expression,
    fold_known_vars,
    UNRESOLVED_SENTINEL,
    PartiallyResolved,
    _UnresolvedSentinel,
    InterpolableNode,
)
from dracon.lazy import LazyInterpolable, resolve_all_lazy
from dracon.dracontainer import Mapping


ENGINES = ['asteval', 'eval']


# ── fold_known_vars ──────────────────────────────────────────────────────────


class TestFoldKnownVars:
    def test_all_vars_known(self):
        assert fold_known_vars('a + b', {'a': 1, 'b': 2}) == '3'

    def test_no_vars_known(self):
        assert fold_known_vars('a + b', {}) == 'a + b'

    def test_mixed_arithmetic(self):
        result = fold_known_vars('a + 1', {'a': 10})
        assert result == '11'

    def test_mixed_unknown_preserved(self):
        result = fold_known_vars('a + b', {'a': 10})
        # a is folded to constant but b remains; full fold not possible
        assert 'b' in result

    def test_string_concat(self):
        result = fold_known_vars("a + '_' + b", {'a': 'deploy'})
        assert "'deploy' + '_'" in result or "'deploy_'" in result or "deploy" in result

    def test_chained_binops(self):
        result = fold_known_vars('a + b + c', {'a': 1, 'b': 2})
        assert '3' in result

    def test_unary_op(self):
        result = fold_known_vars('-a', {'a': 5})
        assert result == '-5'

    def test_unary_not(self):
        result = fold_known_vars('not a', {'a': True})
        assert result == 'False'

    def test_compare(self):
        result = fold_known_vars('a > b', {'a': 5, 'b': 3})
        assert result == 'True'

    def test_compare_mixed(self):
        result = fold_known_vars('a > b', {'a': 5})
        assert 'b' in result

    def test_boolop(self):
        result = fold_known_vars('a and b', {'a': True, 'b': False})
        assert result == 'False'

    def test_boolop_mixed(self):
        result = fold_known_vars('a and b', {'a': True})
        assert 'b' in result

    def test_ifexp_true(self):
        result = fold_known_vars('x if condition else y', {'condition': True})
        assert result == 'x'

    def test_ifexp_false(self):
        result = fold_known_vars('x if condition else y', {'condition': False})
        assert result == 'y'

    def test_ifexp_unknown_condition(self):
        result = fold_known_vars('x if condition else y', {})
        assert 'condition' in result

    def test_non_primitive_left_as_name(self):
        result = fold_known_vars('obj.method()', {'obj': object()})
        assert 'obj' in result

    def test_syntax_error_returns_input(self):
        expr = 'a + = b'
        assert fold_known_vars(expr, {'a': 1}) == expr

    def test_dunder_vars_skipped(self):
        result = fold_known_vars('__secret + a', {'__secret': 42, 'a': 1})
        assert '__secret' in result


# ── UndefinedNameError detection ─────────────────────────────────────────────


class TestUndefinedNameError:
    @pytest.mark.parametrize('engine', ENGINES)
    def test_undefined_var_raises(self, engine):
        with pytest.raises(UndefinedNameError) as exc_info:
            do_safe_eval('undefined_var + 1', engine, symbols={})
        assert exc_info.value.undefined_name == 'undefined_var'

    @pytest.mark.parametrize('engine', ENGINES)
    def test_defined_var_typo_raises_evaluation_error(self, engine):
        """Attribute error on a defined var should raise EvaluationError, not UndefinedNameError."""
        with pytest.raises(EvaluationError) as exc_info:
            do_safe_eval("s.uppper()", engine, symbols={'s': 'hello'})
        assert not isinstance(exc_info.value, UndefinedNameError)

    @pytest.mark.parametrize('engine', ENGINES)
    def test_subclass_of_evaluation_error(self, engine):
        with pytest.raises(EvaluationError):
            do_safe_eval('nope', engine, symbols={})


# ── do_safe_eval permissive mode ─────────────────────────────────────────────


class TestDoSafeEvalPermissive:
    @pytest.mark.parametrize('engine', ENGINES)
    def test_undefined_permissive_returns_sentinel(self, engine):
        result = do_safe_eval('unknown', engine, symbols={}, permissive=True)
        assert result is UNRESOLVED_SENTINEL

    @pytest.mark.parametrize('engine', ENGINES)
    def test_undefined_with_foldable_knowns_returns_partial(self, engine):
        result = do_safe_eval('a + unknown', engine, symbols={'a': 10}, permissive=True)
        assert isinstance(result, PartiallyResolved)
        assert 'unknown' in result.expr

    @pytest.mark.parametrize('engine', ENGINES)
    def test_defined_var_error_still_raises(self, engine):
        """Non-name errors should still raise even in permissive mode."""
        with pytest.raises(EvaluationError):
            do_safe_eval('1 / 0', engine, symbols={}, permissive=True)

    @pytest.mark.parametrize('engine', ENGINES)
    def test_non_permissive_raises(self, engine):
        with pytest.raises(UndefinedNameError):
            do_safe_eval('unknown', engine, symbols={}, permissive=False)

    @pytest.mark.parametrize('engine', ENGINES)
    def test_fully_resolvable_permissive(self, engine):
        """Permissive mode should still return normal results when everything resolves."""
        result = do_safe_eval('a + b', engine, symbols={'a': 1, 'b': 2}, permissive=True)
        assert result == 3


# ── evaluate_expression two-phase ────────────────────────────────────────────


class TestEvaluateExpressionPermissive:
    @pytest.mark.parametrize('engine', ENGINES)
    def test_two_phase_resolution(self, engine):
        # phase 1: only 'a' known
        phase1 = evaluate_expression(
            '${a + b}', engine=engine, context={'a': 10}, permissive=True
        )
        assert isinstance(phase1, str)
        assert 'b' in phase1

        # phase 2: provide 'b'
        phase2 = evaluate_expression(
            phase1, engine=engine, context={'a': 10, 'b': 20}, permissive=False
        )
        assert phase2 == 30

    @pytest.mark.parametrize('engine', ENGINES)
    def test_multi_interpolation_partial(self, engine):
        result = evaluate_expression(
            '${a} and ${b}', engine=engine, context={'a': 1}, permissive=True
        )
        assert '1' in result
        assert '${b}' in result

    @pytest.mark.parametrize('engine', ENGINES)
    def test_single_interpolation_passthrough(self, engine):
        result = evaluate_expression(
            '${version}', engine=engine, context={}, permissive=True
        )
        assert result == '${version}'

    @pytest.mark.parametrize('engine', ENGINES)
    def test_mixed_fold(self, engine):
        # phase 1: prefix known, version unknown
        phase1 = evaluate_expression(
            "${prefix + '_' + version}",
            engine=engine,
            context={'prefix': 'deploy'},
            permissive=True,
        )
        assert isinstance(phase1, str)
        assert 'version' in phase1

        # phase 2: now version is known too
        phase2 = evaluate_expression(
            phase1,
            engine=engine,
            context={'prefix': 'deploy', 'version': '1.2.3'},
            permissive=False,
        )
        assert phase2 == 'deploy_1.2.3'

    @pytest.mark.parametrize('engine', ENGINES)
    def test_no_progress_no_recursion_waste(self, engine):
        """When no progress is made, should not recurse and waste budget."""
        result = evaluate_expression(
            '${unknown}', engine=engine, context={}, permissive=True, allow_recurse=5
        )
        assert result == '${unknown}'


# ── InterpolableNode.evaluate permissive ─────────────────────────────────────


class TestInterpolableNodePermissive:
    @pytest.mark.parametrize('engine', ENGINES)
    def test_permissive_evaluate(self, engine):
        node = InterpolableNode('${a} and ${b}')
        result = node.evaluate(engine=engine, context={'a': 42}, permissive=True)
        assert '42' in result
        assert '${b}' in result


# ── LazyInterpolable permissive ──────────────────────────────────────────────


class TestLazyInterpolablePermissive:
    @pytest.mark.parametrize('engine', ENGINES)
    def test_partial_context(self, engine):
        lazy = LazyInterpolable(
            '${a} and ${b}', permissive=True, engine=engine, context={'a': 'hello'}
        )
        result = lazy.resolve()
        assert 'hello' in result
        assert '${b}' in result

    @pytest.mark.parametrize('engine', ENGINES)
    def test_second_pass_full_resolve(self, engine):
        lazy = LazyInterpolable(
            '${a} and ${b}', permissive=True, engine=engine, context={'a': 'hello'}
        )
        partial = lazy.resolve()
        # now resolve with full context (non-permissive)
        lazy2 = LazyInterpolable(
            partial, permissive=False, engine=engine, context={'a': 'hello', 'b': 'world'}
        )
        result = lazy2.resolve()
        assert result == 'hello and world'


# ── resolve_all_lazy permissive ──────────────────────────────────────────────


class TestResolveAllLazyPermissive:
    def test_leaves_unresolved_as_strings(self):
        config = Mapping({
            'known': LazyInterpolable('${a}', context={'a': 42}, permissive=True),
            'unknown': LazyInterpolable('${b}', context={}, permissive=True),
        })
        resolve_all_lazy(config, permissive=True)
        assert config['known'] == 42
        assert config['unknown'] == '${b}'


# ── Idempotency ──────────────────────────────────────────────────────────────


class TestIdempotency:
    @pytest.mark.parametrize('engine', ENGINES)
    def test_permissive_eval_idempotent(self, engine):
        expr = '${a + b}'
        ctx = {'a': 10}
        r1 = evaluate_expression(expr, engine=engine, context=ctx, permissive=True)
        r2 = evaluate_expression(expr, engine=engine, context=ctx, permissive=True)
        assert r1 == r2


# ── Sentinel behavior ───────────────────────────────────────────────────────


class TestSentinel:
    def test_singleton(self):
        assert _UnresolvedSentinel() is UNRESOLVED_SENTINEL

    def test_bool_false(self):
        assert not UNRESOLVED_SENTINEL

    def test_repr(self):
        assert repr(UNRESOLVED_SENTINEL) == 'UNRESOLVED'


class TestPartiallyResolved:
    def test_repr(self):
        p = PartiallyResolved('a + b')
        assert repr(p) == "PartiallyResolved('a + b')"
