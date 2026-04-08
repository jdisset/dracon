# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""Phase 5 tests: symbol algebra -- universal binding and composition.

Covers:
- !fn:TypeName produces a bound type symbol
- !fn:pipe_name produces a bound pipe symbol
- invoking a bound type constructs with merged kwargs
- invoking a bound pipe runs the pipe with merged kwargs
- pipe with zero unfilled params: stage runs, value passes through
- pipe with mixed threading/non-threading stages
- higher-order: template returns a symbol, caller can invoke it
- YAML round-trip for bound symbols
- regression: existing !fn:path and !pipe behaviors
"""

import pickle
import pytest
from pydantic import BaseModel
from dracon.loader import DraconLoader
from dracon.partial import DraconPartial
from dracon.pipe import DraconPipe
from dracon.symbols import (
    SymbolKind, BoundSymbol, CallableSymbol, auto_symbol, Symbol,
)


def _loads(yaml_str, **ctx):
    loader = DraconLoader(context=ctx)
    config = loader.loads(yaml_str)
    config.resolve_all_lazy()
    return config


# -- helpers for tests --

def _add(a, b):
    return a + b

def _greet(name, greeting="hello"):
    return f"{greeting} {name}"

def _double(x):
    return {'val': x * 2}

def _add_one(val):
    return {'val': val + 1}

class SimpleModel(BaseModel):
    x: int = 0
    y: int = 0


# ── 1. !fn:TypeName produces a bound type symbol ────────────────────────────


class TestFnTargetTypeBinding:
    def test_fn_type_produces_callable_result(self):
        """!fn:TypeName { kwargs } produces something callable that constructs."""
        cfg = _loads("""
val: !fn:dracon.tests.test_phase5_symbol_algebra.SimpleModel
  x: 10
""")
        result = cfg['val']
        # should be callable and invoke to produce SimpleModel
        assert callable(result)
        obj = result(y=20)
        assert isinstance(obj, BaseModel)
        assert obj.x == 10
        assert obj.y == 20

    def test_fn_type_zero_kwargs(self):
        """!fn:TypeName with no kwargs produces a partial that uses defaults."""
        cfg = _loads("val: !fn:dracon.tests.test_phase5_symbol_algebra.SimpleModel")
        result = cfg['val']
        assert callable(result)
        obj = result()
        assert isinstance(obj, BaseModel)
        assert obj.x == 0

    def test_fn_context_type_binding(self):
        """!fn:TypeName where TypeName is in context (not imported)."""
        cfg = _loads("""
val: !fn:SimpleModel
  x: 42
""", SimpleModel=SimpleModel)
        result = cfg['val']
        assert callable(result)
        obj = result(y=7)
        assert isinstance(obj, BaseModel)
        assert obj.x == 42
        assert obj.y == 7

    def test_fn_type_invoke_as_tag(self):
        """A bound type from !fn:Type can be invoked as a tag later."""
        cfg = _loads("""
!define MyModel: !fn:dracon.tests.test_phase5_symbol_algebra.SimpleModel
  x: 100
result: !MyModel
  y: 200
""")
        assert isinstance(cfg['result'], BaseModel)
        assert cfg['result'].x == 100
        assert cfg['result'].y == 200


# ── 2. !fn:pipe_name produces a bound pipe symbol ──────────────────────────


class TestFnTargetPipeBinding:
    def test_fn_pipe_produces_callable(self):
        """!fn:pipe_name { kwargs } produces a callable bound pipe."""
        cfg = _loads("""
!define pipeline: !pipe [dbl, add1]
bound: !fn:pipeline
  x: 5
""", dbl=_double, add1=_add_one)
        result = cfg['bound']
        assert callable(result)

    def test_fn_pipe_invoke_merges_kwargs(self):
        """Invoking a bound pipe merges pre-filled with runtime kwargs."""
        def step_a(x, scale=1, **_):
            return {'val': x * scale}
        def step_b(val, **_):
            return val + 100

        cfg = _loads("""
!define pipeline: !pipe [step_a, step_b]
bound: !fn:pipeline
  scale: 10
""", step_a=step_a, step_b=step_b)
        result = cfg['bound'](x=3)
        # step_a(x=3, scale=10) -> {'val': 30}, step_b(val=30) -> 130
        assert result == 130

    def test_fn_pipe_tag_invocation(self):
        """Bound pipe can be invoked via tag syntax."""
        def step_a(x, scale=1, **_):
            return {'val': x * scale}
        def step_b(val, **_):
            return val + 100

        cfg = _loads("""
!define pipeline: !pipe [step_a, step_b]
!define fast: !fn:pipeline
  scale: 10
result: !fast
  x: 3
""", step_a=step_a, step_b=step_b)
        assert cfg['result'] == 130


# ── 3. Pipe with zero unfilled params (relaxed threading) ──────────────────


class TestPipeRelaxedThreading:
    def test_zero_unfilled_stage_passes_through(self):
        """Stage with no unfilled requires: runs independently, value passes through."""
        call_log = []
        def side_effect(**kwargs):
            call_log.append('side_effect')
            return {'status': 'logged'}

        def process(x):
            return {'val': x * 2}

        # side_effect has no required params, should run independently
        # process has one required param (x), should receive piped value
        cfg = _loads("""
!define pipeline: !pipe [process, side_effect]
result: ${pipeline(x=5)}
""", process=process, side_effect=side_effect)
        # process(x=5) -> {'val': 10}
        # side_effect receives val=10 from dict unpack but has no required params
        # side_effect runs, returns {'status': 'logged'}
        assert cfg['result'] == {'status': 'logged'}
        assert 'side_effect' in call_log

    def test_fully_bound_stage_runs_independently(self):
        """A fully-bound stage (all params pre-filled) runs without threading."""
        results = []
        def log_result(msg, **_):
            results.append(msg)
            return {'logged': True}

        def compute(x, **_):
            return {'val': x * 3}

        cfg = _loads("""
!define pipeline: !pipe
  - compute
  - log_it: { msg: done }
result: ${pipeline(x=7)}
""", compute=compute, log_it=log_result)
        # compute(x=7) -> {'val': 21}
        # log_it has msg pre-filled, zero unfilled -> runs independently
        # piped dict {'val': 21} is merged into call_kwargs but msg is pre-filled
        assert cfg['result'] == {'logged': True}
        assert 'done' in results

    def test_mixed_threading_non_threading(self):
        """Mix of threaded and non-threaded stages in one pipe."""
        def step_a(x, **_):
            return {'val': x * 2}

        def step_b(val, **_):
            return {'result': val + 1}

        log = []
        def step_log(**kwargs):
            log.append(kwargs)
            return {'status': 'ok'}

        cfg = _loads("""
!define pipeline: !pipe [step_a, step_b, step_log]
result: ${pipeline(x=5)}
""", step_a=step_a, step_b=step_b, step_log=step_log)
        # step_a(x=5) -> {'val': 10}
        # step_b(val=10) -> {'result': 11}
        # step_log has no required params -> runs with dict unpack from prev
        assert cfg['result'] == {'status': 'ok'}
        assert len(log) >= 1  # may run multiple times due to lazy eval

    def test_all_stages_fully_bound(self):
        """All stages have no unfilled params -> each runs independently."""
        results = []
        def s1(**kwargs):
            results.append('s1')
            return {'a': 1}
        def s2(**kwargs):
            results.append('s2')
            return {'b': 2}

        cfg = _loads("""
!define pipeline: !pipe [s1, s2]
result: ${pipeline()}
""", s1=s1, s2=s2)
        assert 's1' in results
        assert 's2' in results


# ── 4. Higher-order symbol returns ──────────────────────────────────────────


class TestHigherOrderSymbolReturns:
    def test_template_returns_partial(self):
        """!fn returning !fn:path yields a callable that the caller can invoke."""
        cfg = _loads("""
!define make_greeter: !fn
  !require greeting: "the greeting"
  !fn : !fn:dracon.tests.test_phase5_symbol_algebra._greet
    greeting: ${greeting}
!define greeter: !make_greeter { greeting: yo }
result: ${greeter(name='world')}
""")
        assert cfg['result'] == "yo world"

    def test_template_returns_bound_type(self):
        """!fn returning !fn:TypeName yields a bound type, caller can invoke."""
        cfg = _loads("""
!define make_model: !fn
  !require default_x: "default x value"
  !fn : !fn:dracon.tests.test_phase5_symbol_algebra.SimpleModel
    x: ${default_x}
!define factory: !make_model { default_x: 99 }
factory_ref: ${factory}
""")
        factory = cfg['factory_ref']
        assert callable(factory)
        obj = factory(y=42)
        assert isinstance(obj, BaseModel)
        assert obj.x == 99
        assert obj.y == 42

    def test_factory_invoked_as_tag(self):
        """Factory output (a callable) invoked via tag syntax."""
        cfg = _loads("""
!define make_greeter: !fn
  !require greeting: "the greeting"
  !fn : !fn:dracon.tests.test_phase5_symbol_algebra._greet
    greeting: ${greeting}
!define hey_greeter: !make_greeter { greeting: hey }
result: ${hey_greeter(name='there')}
""")
        assert cfg['result'] == "hey there"


# ── 5. YAML round-trip for bound symbols ────────────────────────────────────


class TestBoundSymbolSerialization:
    def test_fn_path_yaml_roundtrip(self):
        """!fn:path with kwargs survives dump -> reload -> call."""
        from dracon import dump
        cfg = _loads("""
val: !fn:dracon.tests.test_phase5_symbol_algebra._add
  a: 10
""")
        dumped = dump(cfg)
        assert '!fn:dracon.tests.test_phase5_symbol_algebra._add' in dumped
        cfg2 = _loads(dumped)
        assert cfg2['val'](b=5) == 15

    def test_fn_path_pickle_roundtrip(self):
        """!fn:path partials survive pickle round-trip."""
        cfg = _loads("""
val: !fn:dracon.tests.test_phase5_symbol_algebra._add
  a: 10
""")
        data = pickle.dumps(cfg['val'])
        restored = pickle.loads(data)
        assert restored(b=5) == 15


# ── 6. Regression: existing behaviors preserved ─────────────────────────────


class TestRegression:
    def test_fn_path_basic_callable(self):
        """Basic !fn:path still works for plain callables."""
        cfg = _loads("val: !fn:math.sqrt")
        assert isinstance(cfg['val'], DraconPartial)
        assert cfg['val'](4) == 2.0

    def test_fn_path_with_kwargs(self):
        cfg = _loads("""
val: !fn:dracon.tests.test_phase5_symbol_algebra._greet
  greeting: howdy
""")
        assert cfg['val'](name="world") == "howdy world"

    def test_callable_tag_invocation(self):
        """!callable_name { kwargs } still works for callables."""
        cfg = _loads("""
result: !my_add { a: 1, b: 2 }
""", my_add=_add)
        assert cfg['result'] == 3

    def test_pipe_basic_chaining(self):
        """Basic pipe chaining still works."""
        cfg = _loads("""
!define f: !fn
  !require x: "val"
  val: ${x * 2}
!define g: !fn
  !require val: "val"
  result: ${val + 1}
!define p: !pipe [f, g]
out: ${p(x=5)}
""")
        assert cfg['out']['result'] == 11

    def test_pipe_multiple_unfilled_still_errors(self):
        """Pipe stage with 2+ unfilled required params still errors."""
        from dracon.diagnostics import CompositionError

        def stage_a(x):
            return 42  # non-mapping return

        def stage_b(a, b, c):
            return a + b + c

        loader = DraconLoader(context={'stage_a': stage_a, 'stage_b': stage_b})
        cfg = loader.loads("""
!define pipeline: !pipe [stage_a, stage_b]
pipeline_ref: ${pipeline}
""")
        pipe = cfg['pipeline_ref']
        # should fail at invocation when trying to thread non-mapping
        # into a stage with multiple unfilled required params
        with pytest.raises(CompositionError, match="unfilled"):
            pipe(x=1)

    def test_non_callable_fn_path_now_binds_types(self):
        """!fn:math.pi used to error as non-callable -- now it should still error
        since pi is a float (a value, not bindable in a useful way)."""
        # math.pi is a float, not callable, not a type -- should still error
        with pytest.raises(Exception):
            _loads("val: !fn:math.pi")

    def test_dracon_partial_importable(self):
        """DraconPartial name is still importable from dracon.partial."""
        from dracon.partial import DraconPartial as DP
        assert DP is not None

    def test_pipe_tag_invocation(self):
        """!pipe_name { kwargs } tag syntax still works."""
        cfg = _loads("""
!define f: !fn
  !require x: "val"
  val: ${x * 2}
!define g: !fn
  !require val: "val"
  result: ${val + 1}
!define p: !pipe [f, g]
out: !p
  x: 5
""")
        assert cfg['out']['result'] == 11


# ── 7. _get_unfilled_require returns None for zero unfilled ──────────────────


class TestGetUnfilledRequireRelaxed:
    def test_zero_unfilled_returns_none(self):
        """Zero unfilled required params returns None (no threading)."""
        from dracon.pipe import _get_unfilled_require
        cfg = _loads("""
!define f: !fn
  !require a: "val"
  result: ${a}
check: ${f}
""")
        f = cfg['check']
        result = _get_unfilled_require(f, {'a': 1})
        assert result is None

    def test_single_unfilled_returns_name(self):
        """Single unfilled required param returns the param name (unchanged)."""
        from dracon.pipe import _get_unfilled_require
        cfg = _loads("""
!define f: !fn
  !require a: "val"
  !require b: "val"
  result: ${a + b}
check: ${f}
""")
        f = cfg['check']
        assert _get_unfilled_require(f, {'a': 1}) == 'b'

    def test_multiple_unfilled_still_errors(self):
        """2+ unfilled required params still raises CompositionError."""
        from dracon.pipe import _get_unfilled_require
        from dracon.diagnostics import CompositionError
        cfg = _loads("""
!define f: !fn
  !require a: "val"
  !require b: "val"
  !require c: "val"
  result: ${a + b + c}
check: ${f}
""")
        f = cfg['check']
        with pytest.raises(CompositionError, match="unfilled"):
            _get_unfilled_require(f, {})
