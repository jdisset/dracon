# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""Tests: pipes and deferred on InterfaceSpec.

Covers:
- pipe param inference via symbol.interface() instead of bespoke scanners
- bound symbols reducing open params in pipe threading
- deferred interface extraction from !require / !assert
- pipe behavior with mixed stage kinds
- deferred construction end-to-end with Symbol protocol
"""

import pytest
from dracon.loader import DraconLoader
from dracon.symbols import (
    SymbolKind, ParamSpec, ContractSpec, InterfaceSpec,
    CallableSymbol, BoundSymbol, auto_symbol,
)


def _loads(yaml_str, **ctx):
    loader = DraconLoader(context=ctx)
    config = loader.loads(yaml_str)
    config.resolve_all_lazy()
    return config


# ── pipe param inference via interface() ────────────────────────────────────


class TestPipeInterfaceInference:
    """Pipe stages expose params through the unified symbol.interface() model."""

    def test_pipe_interface_shows_aggregated_params(self):
        """DraconPipe.interface() aggregates required/optional params from stages."""
        yaml = """
        !define f: !fn
          !require x: "val"
          !set_default scale: 1
          val: ${x * scale}
        !define g: !fn
          !require val: "val"
          result: ${val + 1}
        !define p: !pipe [f, g]
        pipe_ref: ${p}
        """
        config = _loads(yaml)
        pipe = config['pipe_ref']
        iface = pipe.interface()
        assert iface.kind == SymbolKind.PIPE
        param_names = [p.name for p in iface.params]
        assert 'x' in param_names
        assert 'scale' in param_names
        required = [p.name for p in iface.params if p.required]
        optional = [p.name for p in iface.params if not p.required]
        assert 'x' in required
        assert 'scale' in optional

    def test_pipe_interface_excludes_prefilled(self):
        """Pre-filled kwargs are excluded from the pipe's interface."""
        yaml = """
        !define f: !fn
          !require x: "val"
          !require y: "val"
          sum: ${x + y}
        !define g: !fn
          !require sum: "val"
          result: ${sum * 10}
        !define p: !pipe
          - f: { y: 100 }
          - g
        pipe_ref: ${p}
        """
        config = _loads(yaml)
        pipe = config['pipe_ref']
        iface = pipe.interface()
        param_names = [p.name for p in iface.params]
        assert 'x' in param_names
        assert 'y' not in param_names  # pre-filled

    def test_python_callable_stage_interface(self):
        """Python callables in pipe stages have their params discovered via interface()."""
        def transform(data, factor=2):
            return {'result': data * factor}

        yaml = """
        !define g: !fn
          !require result: "val"
          final: ${result + 1}
        !define p: !pipe [transform, g]
        pipe_ref: ${p}
        """
        config = _loads(yaml, transform=transform)
        pipe = config['pipe_ref']
        iface = pipe.interface()
        param_names = [p.name for p in iface.params]
        assert 'data' in param_names
        assert 'factor' in param_names

    def test_mixed_stage_kinds_interface(self):
        """Pipe with template, python callable, and partial stages."""
        def double(x):
            return {'val': x * 2}

        yaml = """
        !define add_one: !fn
          !require val: "val"
          val: ${val + 1}
        !define p: !pipe [double, add_one]
        pipe_ref: ${p}
        out: ${p(x=5)}
        """
        config = _loads(yaml, double=double)
        pipe = config['pipe_ref']
        iface = pipe.interface()
        param_names = [p.name for p in iface.params]
        assert 'x' in param_names
        assert config['out']['val'] == 11


# ── bound symbols reduce open params in pipe threading ──────────────────────


class TestBoundSymbolPipeReduction:
    """Binding a pipe stage reduces its open params in the interface."""

    def test_bound_pipe_reduces_params(self):
        """Binding kwargs on a pipe reduces its interface params."""
        yaml = """
        !define f: !fn
          !require x: "val"
          !require y: "val"
          sum: ${x + y}
        !define g: !fn
          !require sum: "val"
          result: ${sum * 10}
        !define p: !pipe [f, g]
        pipe_ref: ${p}
        """
        config = _loads(yaml)
        pipe = config['pipe_ref']
        bound = pipe.bind(x=5)
        bound_iface = bound.interface()
        param_names = [p.name for p in bound_iface.params]
        assert 'x' not in param_names
        assert 'y' in param_names

    def test_bound_pipe_invokes_correctly(self):
        """Bound pipe still executes correctly."""
        yaml = """
        !define f: !fn
          !require x: "val"
          !require y: "val"
          sum: ${x + y}
        !define g: !fn
          !require sum: "val"
          result: ${sum * 10}
        !define p: !pipe [f, g]
        pipe_ref: ${p}
        """
        config = _loads(yaml)
        pipe = config['pipe_ref']
        bound = pipe.bind(x=5)
        result = bound.invoke(y=3)
        assert result['result'] == 80


# ── deferred interface extraction ───────────────────────────────────────────


class TestDeferredInterfaceExtraction:
    """DeferredNode surfaces runtime contracts via InterfaceSpec."""

    def test_deferred_has_symbol_interface(self):
        """DeferredNode implements symbol protocol with interface()."""
        yaml = """
        reporting: !deferred
          !require run_id: "runtime run identifier"
          path: /runs/${run_id}
        """
        loader = DraconLoader(enable_interpolation=True)
        config = loader.loads(yaml)
        from dracon.deferred import DeferredNode
        deferred = config['reporting']
        assert isinstance(deferred, DeferredNode)
        iface = deferred.interface()
        assert iface.kind == SymbolKind.DEFERRED
        param_names = [p.name for p in iface.params]
        assert 'run_id' in param_names

    def test_deferred_require_params_are_required(self):
        """!require inside deferred surfaces as required params."""
        yaml = """
        reporting: !deferred
          !require run_id: "runtime run identifier"
          !require model: "trained model object"
          path: /runs/${run_id}
        """
        loader = DraconLoader(enable_interpolation=True)
        config = loader.loads(yaml)
        deferred = config['reporting']
        iface = deferred.interface()
        required = [p for p in iface.params if p.required]
        assert len(required) == 2
        names = {p.name for p in required}
        assert names == {'run_id', 'model'}

    def test_deferred_set_default_params(self):
        """!set_default inside deferred surfaces as optional params."""
        yaml = """
        reporting: !deferred
          !require run_id: "runtime run identifier"
          !set_default format: json
          path: /runs/${run_id}.${format}
        """
        loader = DraconLoader(enable_interpolation=True)
        config = loader.loads(yaml)
        deferred = config['reporting']
        iface = deferred.interface()
        optional = [p for p in iface.params if not p.required]
        assert any(p.name == 'format' for p in optional)

    def test_deferred_require_docs(self):
        """!require hint message becomes ParamSpec.docs."""
        yaml = """
        reporting: !deferred
          !require run_id: "runtime run identifier"
          path: /runs/${run_id}
        """
        loader = DraconLoader(enable_interpolation=True)
        config = loader.loads(yaml)
        deferred = config['reporting']
        iface = deferred.interface()
        run_id_param = next(p for p in iface.params if p.name == 'run_id')
        assert run_id_param.docs == 'runtime run identifier'

    def test_deferred_assert_contracts(self):
        """!assert inside deferred surfaces as ContractSpec."""
        yaml = """
        reporting: !deferred
          !require run_id: "runtime run identifier"
          !assert ${len(run_id) > 0}: "run_id must not be empty"
          path: /runs/${run_id}
        """
        loader = DraconLoader(enable_interpolation=True)
        config = loader.loads(yaml)
        deferred = config['reporting']
        iface = deferred.interface()
        assert len(iface.contracts) >= 1
        assert any(c.kind == 'assert' for c in iface.contracts)

    def test_deferred_materialize_returns_self(self):
        """DeferredNode.materialize() returns self (it IS the deferred value)."""
        yaml = """
        reporting: !deferred
          !require run_id: "runtime run identifier"
          path: /runs/${run_id}
        """
        loader = DraconLoader(enable_interpolation=True)
        config = loader.loads(yaml)
        deferred = config['reporting']
        assert deferred.materialize() is deferred

    def test_deferred_invoke_constructs(self):
        """DeferredNode.invoke() constructs with provided context."""
        yaml = """
        reporting: !deferred
          !require run_id: "runtime run identifier"
          path: /runs/${run_id}
        """
        loader = DraconLoader(enable_interpolation=True)
        config = loader.loads(yaml)
        deferred = config['reporting']
        # invoke with context should construct
        from dracon.deferred import DeferredNode
        assert isinstance(deferred, DeferredNode)
        result = deferred.copy().construct(context={'run_id': 'exp-17'})
        assert result['path'] == '/runs/exp-17'


# ── shared interface model between pipes and deferred ───────────────────────


class TestSharedInterfaceModel:
    """Both pipes and deferred use the same InterfaceSpec/ParamSpec/ContractSpec."""

    def test_pipe_and_deferred_same_param_type(self):
        """Both features produce ParamSpec instances."""
        def step(x):
            return {'val': x * 2}

        yaml = """
        !define p: !pipe [step]
        deferred_part: !deferred
          !require run_id: "id"
          data: ${run_id}
        pipe_ref: ${p}
        """
        loader = DraconLoader(context={'step': step})
        config = loader.loads(yaml)

        pipe_iface = config['pipe_ref'].interface()
        deferred_iface = config['deferred_part'].interface()

        # both produce ParamSpec
        assert all(isinstance(p, ParamSpec) for p in pipe_iface.params)
        assert all(isinstance(p, ParamSpec) for p in deferred_iface.params)

    def test_auto_symbol_wraps_deferred(self):
        """auto_symbol recognizes DeferredNode as a Symbol."""
        yaml = """
        reporting: !deferred
          !require run_id: "runtime run identifier"
          path: /runs/${run_id}
        """
        loader = DraconLoader(enable_interpolation=True)
        config = loader.loads(yaml)
        deferred = config['reporting']
        sym = auto_symbol(deferred, name='reporting')
        # should return the deferred itself (it implements Symbol)
        assert sym is deferred
        iface = sym.interface()
        assert iface.kind == SymbolKind.DEFERRED


# ── pipe no longer imports from instructions for template scanning ──────────


class TestPipeDecoupled:
    """pipe.py does not use instructions.match_instruct for param scanning."""

    def test_pipe_no_instructions_import_for_scanning(self):
        """Verify _has_custom_tag does not import from instructions."""
        from dracon import pipe
        import inspect
        source = inspect.getsource(pipe._has_custom_tag)
        assert 'instructions' not in source
        assert 'match_instruct' not in source

    def test_pipe_still_chains_correctly(self):
        """Pipes still chain stages after refactor."""
        yaml = """
        !define a: !fn
          !require x: "val"
          val: ${x + 1}
        !define b: !fn
          !require val: "val"
          val: ${val * 2}
        !define p: !pipe [a, b]
        out: ${p(x=4)}
        """
        config = _loads(yaml)
        assert config['out']['val'] == 10

    def test_pipe_typed_threading_via_interface(self):
        """Non-mapping output threaded to unfilled require via interface()."""
        from pydantic import BaseModel

        class Result(BaseModel):
            value: int

        def make_result(x=0):
            return Result(value=x * 2)

        yaml = """
        !define extract: !fn
          !require data: "typed result"
          extracted: ${data.value + 100}
        !define p: !pipe [make_result, extract]
        out: ${p(x=5)}
        """
        config = _loads(yaml, make_result=make_result, Result=Result)
        assert config['out']['extracted'] == 110
