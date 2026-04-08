# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""Tests for !pipe function composition."""
import pytest
from dracon.loader import DraconLoader


def _loads(yaml_str, **ctx):
    loader = DraconLoader(context=ctx)
    config = loader.loads(yaml_str)
    config.resolve_all_lazy()
    return config


# ── Core behavior ──────────────────────────────────────────────────────────


class TestPipeCoreBasic:
    """!pipe produces a callable that chains stages."""

    def test_pipe_produces_callable(self):
        from dracon.pipe import DraconPipe
        yaml = """
        !define f: !fn
          !require x: "val"
          result: ${x}
        !define g: !fn
          !require result: "val"
          doubled: ${result * 2}
        !define p: !pipe [f, g]
        check: ${isinstance(p, DraconPipe)}
        """
        config = _loads(yaml, DraconPipe=DraconPipe)
        assert config['check'] is True

    def test_pipe_chains_dict_output(self):
        """f returns a dict, g receives it unpacked as kwargs."""
        yaml = """
        !define f: !fn
          !require x: "val"
          result: ${x * 2}
        !define g: !fn
          !require result: "val"
          final: ${result + 1}
        !define p: !pipe [f, g]
        out: ${p(x=5)}
        """
        config = _loads(yaml)
        assert config['out']['final'] == 11

    def test_pipe_three_stages(self):
        yaml = """
        !define a: !fn
          !require x: "val"
          val: ${x + 1}
        !define b: !fn
          !require val: "val"
          val: ${val * 2}
        !define c: !fn
          !require val: "val"
          val: ${val + 100}
        !define p: !pipe [a, b, c]
        out: ${p(x=4)}
        """
        config = _loads(yaml)
        # (4+1)=5, 5*2=10, 10+100=110
        assert config['out']['val'] == 110

    def test_pipe_pre_filled_kwargs(self):
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
        out: ${p(x=5)}
        """
        config = _loads(yaml)
        assert config['out']['result'] == 1050

    def test_pipe_kwargs_pass_through(self):
        """Pipeline kwargs flow to all stages, not just the first."""
        yaml = """
        !define f: !fn
          !require x: "val"
          val: ${x}
        !define g: !fn
          !require val: "val"
          !require scale: "multiplier"
          result: ${val * scale}
        !define p: !pipe [f, g]
        out: ${p(x=3, scale=10)}
        """
        config = _loads(yaml)
        assert config['out']['result'] == 30

    def test_pipe_first_stage_no_pipe_input(self):
        """First stage receives only pipeline kwargs, no piped value."""
        yaml = """
        !define f: !fn
          !require a: "val"
          !require b: "val"
          sum: ${a + b}
        !define g: !fn
          !require sum: "val"
          result: ${sum}
        !define p: !pipe [f, g]
        out: ${p(a=1, b=2)}
        """
        config = _loads(yaml)
        assert config['out']['result'] == 3


# ── Dict unpack vs typed threading ────────────────────────────────────────────


class TestPipeDictVsTyped:
    """Dict output is kwarg-unpacked; typed output goes to unfilled !require."""

    def test_pipe_dict_return_unpack(self):
        """Plain dict return from a Python callable stage."""
        def make_data(x=0):
            return {'val': x * 2, 'tag': 'data'}

        yaml = """
        !define g: !fn
          !require val: "val"
          !require tag: "tag"
          result: ${tag}_${val}
        !define p: !pipe [make_data, g]
        out: ${p(x=5)}
        """
        config = _loads(yaml, make_data=make_data)
        assert config['out']['result'] == 'data_10'

    def test_pipe_dracontainer_return_unpack(self):
        """DraconCallable returns a Dracontainer (MutableMapping) -- still unpacked."""
        yaml = """
        !define f: !fn
          !require x: "val"
          val: ${x * 3}
        !define g: !fn
          !require val: "val"
          result: ${val + 1}
        !define p: !pipe [f, g]
        out: ${p(x=2)}
        """
        config = _loads(yaml)
        # f(x=2) returns Dracontainer with {val: 6}, unpacked into g(val=6)
        assert config['out']['result'] == 7

    def test_pipe_typed_return_single_value(self):
        """Non-mapping return goes as single value to unfilled !require."""
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

    def test_pipe_piped_overrides_pre_kwargs(self):
        """Piped dict output overrides pre-filled kwargs (data flow wins)."""
        yaml = """
        !define f: !fn
          !require x: "val"
          strategy: computed
          val: ${x}
        !define g: !fn
          !require val: "val"
          !require strategy: "strat"
          result: ${strategy}_${val}
        !define p: !pipe
          - f
          - g: { strategy: default }
        out: ${p(x=1)}
        """
        config = _loads(yaml)
        # f returns {strategy: "computed", val: 1}
        # piped output overrides pre-fill: strategy="computed" wins over "default"
        assert config['out']['result'] == 'computed_1'


# ── Signature introspection ───────────────────────────────────────────────────


class TestPipeSignatureIntrospection:
    """Symbol interface-based param introspection for pipe stages."""

    def test_scan_template_requires(self):
        """Finds !require param names via symbol interface()."""
        from dracon.callable import DraconCallable
        yaml = """
        !define f: !fn
          !require alpha: "first"
          !require beta: "second"
          result: ${alpha + beta}
        check: ${f}
        """
        loader = DraconLoader()
        config = loader.loads(yaml)
        f = config['check']
        assert isinstance(f, DraconCallable)
        iface = f.interface()
        req = sorted(p.name for p in iface.params if p.required)
        opt = [p.name for p in iface.params if not p.required]
        assert req == ['alpha', 'beta']
        assert opt == []

    def test_scan_template_defaults(self):
        """Finds !set_default param names via symbol interface()."""
        yaml = """
        !define f: !fn
          !require x: "val"
          !set_default y: 10
          result: ${x + y}
        check: ${f}
        """
        loader = DraconLoader()
        config = loader.loads(yaml)
        f = config['check']
        iface = f.interface()
        req = [p.name for p in iface.params if p.required]
        opt = [p.name for p in iface.params if not p.required]
        assert req == ['x']
        assert opt == ['y']

    def test_get_unfilled_require_single(self):
        """Correctly identifies the one unfilled !require."""
        from dracon.pipe import _get_unfilled_require
        yaml = """
        !define f: !fn
          !require a: "val"
          !require b: "val"
          result: ${a + b}
        check: ${f}
        """
        loader = DraconLoader()
        config = loader.loads(yaml)
        f = config['check']
        # a is filled, b is unfilled
        assert _get_unfilled_require(f, {'a': 1}) == 'b'
        # b is filled, a is unfilled
        assert _get_unfilled_require(f, {'b': 2}) == 'a'

    def test_get_unfilled_require_zero_returns_none(self):
        """Zero unfilled requires returns None (stage runs independently)."""
        from dracon.pipe import _get_unfilled_require
        yaml = """
        !define f: !fn
          !require a: "val"
          result: ${a}
        check: ${f}
        """
        loader = DraconLoader()
        config = loader.loads(yaml)
        f = config['check']
        assert _get_unfilled_require(f, {'a': 1}) is None

    def test_get_unfilled_require_multiple_raises(self):
        """Error when 2+ !requires are unfilled."""
        from dracon.pipe import _get_unfilled_require
        from dracon.diagnostics import CompositionError
        yaml = """
        !define f: !fn
          !require a: "val"
          !require b: "val"
          !require c: "val"
          result: ${a + b + c}
        check: ${f}
        """
        loader = DraconLoader()
        config = loader.loads(yaml)
        f = config['check']
        with pytest.raises(CompositionError, match="3 unfilled"):
            _get_unfilled_require(f, {})


# ── Stage resolution & errors ─────────────────────────────────────────────────


class TestPipeStageErrors:
    """Error handling for invalid pipe definitions."""

    def test_pipe_unknown_stage_error(self):
        from dracon.diagnostics import CompositionError
        yaml = """
        !define p: !pipe [nonexistent_stage]
        out: ${p()}
        """
        with pytest.raises(CompositionError, match="nonexistent_stage.*not found"):
            _loads(yaml)

    def test_pipe_uncallable_stage_error(self):
        from dracon.diagnostics import CompositionError
        yaml = """
        !define not_fn: 42
        !define p: !pipe [not_fn]
        out: ${p()}
        """
        with pytest.raises(CompositionError, match="not callable"):
            _loads(yaml)

    def test_pipe_empty_sequence_error(self):
        from dracon.diagnostics import CompositionError
        yaml = """
        !define p: !pipe []
        out: ${p()}
        """
        with pytest.raises(CompositionError, match="must not be empty"):
            _loads(yaml)

    def test_pipe_non_sequence_error(self):
        from dracon.diagnostics import CompositionError
        yaml = """
        !define p: !pipe { a: b }
        out: ${p()}
        """
        with pytest.raises(CompositionError, match="must be a sequence"):
            _loads(yaml)


# ── Composition & invocation ──────────────────────────────────────────────────


class TestPipeComposition:
    """Pipes compose with pipes, work as tags, expressions, comprehensions."""

    def test_pipe_of_pipes(self):
        """A pipe stage can be another pipe -- they compose."""
        yaml = """
        !define a: !fn
          !require x: "val"
          val: ${x + 1}
        !define b: !fn
          !require val: "val"
          val: ${val * 2}
        !define c: !fn
          !require val: "val"
          result: ${val + 100}
        !define ab: !pipe [a, b]
        !define abc: !pipe [ab, c]
        out: ${abc(x=4)}
        """
        config = _loads(yaml)
        # (4+1)=5, 5*2=10, 10+100=110
        assert config['out']['result'] == 110

    def test_pipe_flattening(self):
        """Nested pipe stages are flattened -- same result as flat pipe."""
        from dracon.pipe import DraconPipe
        yaml = """
        !define a: !fn
          !require x: "val"
          val: ${x + 1}
        !define b: !fn
          !require val: "val"
          val: ${val * 2}
        !define c: !fn
          !require val: "val"
          result: ${val + 100}
        !define ab: !pipe [a, b]
        !define abc: !pipe [ab, c]
        pipe_ref: ${abc}
        out: ${abc(x=4)}
        """
        config = _loads(yaml, DraconPipe=DraconPipe)
        pipe = config['pipe_ref']
        assert isinstance(pipe, DraconPipe)
        # flattened: 3 stages, not 2
        assert len(pipe._stages) == 3
        assert config['out']['result'] == 110

    def test_pipe_tag_invocation(self):
        """!pipe_name { kwargs } tag syntax."""
        yaml = """
        !define f: !fn
          !require x: "val"
          val: ${x * 2}
        !define g: !fn
          !require val: "val"
          result: ${val + 1}
        !define p: !pipe [f, g]
        out: !p
          x: 5
        """
        config = _loads(yaml)
        assert config['out']['result'] == 11

    def test_pipe_expression_invocation(self):
        """${pipe(kwargs)} expression syntax."""
        yaml = """
        !define f: !fn
          !require x: "val"
          val: ${x * 2}
        !define g: !fn
          !require val: "val"
          result: ${val + 1}
        !define p: !pipe [f, g]
        out: ${p(x=5)}
        """
        config = _loads(yaml)
        assert config['out']['result'] == 11

    def test_pipe_in_comprehension(self):
        """Pipe callable inside a list comprehension."""
        yaml = """
        !define f: !fn
          !require x: "val"
          val: ${x * 2}
        !define g: !fn
          !require val: "val"
          result: ${val + 1}
        !define p: !pipe [f, g]
        results: ${[p(x=i)['result'] for i in range(4)]}
        """
        config = _loads(yaml)
        assert config['results'] == [1, 3, 5, 7]


# ── Integration ──────────────────────────────────────────────────────────────


class TestPipeIntegration:
    """!pipe composes with other dracon features."""

    def test_pipe_with_fn_file_stages(self):
        """!fn file: templates work as pipe stages."""
        yaml = """
        !define double: !fn pkg:dracon:tests/fn_double.yaml
        !define add_ten: !fn
          !require result: "val"
          result: ${result + 10}
        !define p: !pipe [double, add_ten]
        out: ${p(x=5)}
        """
        config = _loads(yaml)
        # double(x=5) returns {result: 10}, add_ten receives result=10, returns {result: 20}
        assert config['out']['result'] == 20

    def test_pipe_with_set_default_bubble(self):
        """!set_default params from stages are available at pipeline level."""
        yaml = """
        !define f: !fn
          !require x: "val"
          !set_default scale: 1
          val: ${x * scale}
        !define g: !fn
          !require val: "val"
          result: ${val}
        !define p: !pipe [f, g]
        default_out: ${p(x=5)}
        scaled_out: ${p(x=5, scale=10)}
        """
        config = _loads(yaml)
        assert config['default_out']['result'] == 5
        assert config['scaled_out']['result'] == 50

    def test_pipe_with_each(self):
        """Pipe callable inside !each iteration."""
        yaml = """
        !define f: !fn
          !require x: "val"
          val: ${x * 2}
        !define g: !fn
          !require val: "val"
          result: ${val + 1}
        !define p: !pipe [f, g]
        !define items: ${[1, 2, 3]}
        results:
          !each(i) ${items}:
            item_${i}: ${p(x=i)}
        """
        config = _loads(yaml)
        assert config['results']['item_1']['result'] == 3
        assert config['results']['item_2']['result'] == 5
        assert config['results']['item_3']['result'] == 7

    def test_pipe_isolation(self):
        """Multiple pipe invocations don't leak state."""
        yaml = """
        !define f: !fn
          !require x: "val"
          val: ${x}
        !define g: !fn
          !require val: "val"
          result: ${val * 10}
        !define p: !pipe [f, g]
        a: ${p(x=1)}
        b: ${p(x=2)}
        c: ${p(x=3)}
        """
        config = _loads(yaml)
        assert config['a']['result'] == 10
        assert config['b']['result'] == 20
        assert config['c']['result'] == 30

    def test_pipe_with_define_lazy(self):
        """!define result: ${pipe(kwargs)} works with lazy evaluation."""
        yaml = """
        !define f: !fn
          !require x: "val"
          val: ${x * 2}
        !define g: !fn
          !require val: "val"
          result: ${val + 1}
        !define p: !pipe [f, g]
        !define computed: ${p(x=10)}
        result: ${computed['result']}
        """
        config = _loads(yaml)
        assert config['result'] == 21
