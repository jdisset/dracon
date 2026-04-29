"""Tests for !fn:path (DraconPartial) -- partial application of Python callables."""
import math
import pickle
import pytest
from dracon.loader import DraconLoader
from dracon.partial import DraconPartial
from dracon.symbols import CallableSymbol


# --- test helpers ---

def _add(a, b):
    return a + b

def _greet(name, greeting="hello"):
    return f"{greeting} {name}"

def _kwonly(*, x, y=0):
    return x + y


def _loads(yaml_str, **ctx):
    loader = DraconLoader(context=ctx)
    config = loader.loads(yaml_str)
    config.resolve_all_lazy()
    return config


# ── basic construction ──────────────────────────────────────────────────────


class TestFnPathBasic:
    def test_produces_partial(self):
        cfg = _loads("val: !fn:math.sqrt")
        assert isinstance(cfg['val'], CallableSymbol) and cfg['val']._kind == 'partial'

    def test_zero_kwargs(self):
        cfg = _loads("val: !fn:math.sqrt")
        assert cfg['val'](4) == 2.0

    def test_with_kwargs(self):
        cfg = _loads("""
val: !fn:dracon.tests.test_partial._greet
  greeting: howdy
""")
        assert cfg['val'](name="world") == "howdy world"

    def test_runtime_override(self):
        cfg = _loads("""
val: !fn:dracon.tests.test_partial._greet
  greeting: howdy
""")
        assert cfg['val'](name="world", greeting="hey") == "hey world"

    def test_positional_args(self):
        cfg = _loads("val: !fn:math.pow")
        assert cfg['val'](2.0, 3.0) == 8.0

    def test_repr(self):
        p = DraconPartial("math.sqrt", math.sqrt, {})
        assert "math.sqrt" in repr(p)

    def test_flow_style_kwargs(self):
        cfg = _loads("val: !fn:dracon.tests.test_partial._add { a: 1, b: 2 }")
        assert cfg['val']() == 3


# ── resolution ──────────────────────────────────────────────────────────────


class TestFnPathResolution:
    def test_import_resolution(self):
        cfg = _loads("val: !fn:math.sqrt")
        assert cfg['val'](9) == 3.0

    def test_context_resolution(self):
        cfg = _loads("val: !fn:my_func", my_func=_add)
        assert cfg['val'](a=1, b=2) == 3

    def test_not_found_error(self):
        with pytest.raises(Exception, match="cannot resolve"):
            _loads("val: !fn:nonexistent.module.func")

    def test_non_callable_error(self):
        with pytest.raises(Exception, match="non-callable"):
            _loads("val: !fn:math.pi")


# ── composition ─────────────────────────────────────────────────────────────


class TestFnPathComposition:
    def test_nested_callable_tag(self):
        """Nested callable tags are invoked at construction time."""
        cfg = _loads("""
val: !fn:dracon.tests.test_partial._greet
  greeting: !my_add { a: 1, b: 2 }
""", my_add=_add)
        # _add(1,2) = 3, stored as 'greeting' kwarg
        assert cfg['val'](name="x") == "3 x"

    def test_interpolation_in_kwargs(self):
        cfg = _loads("""
!define base: 10
val: !fn:dracon.tests.test_partial._add
  a: ${base}
""")
        assert cfg['val'](b=5) == 15

    def test_in_list(self):
        cfg = _loads("""
fns:
  - !fn:math.sqrt
  - !fn:math.ceil
""")
        assert len(cfg['fns']) == 2
        assert cfg['fns'][0](4) == 2.0
        assert cfg['fns'][1](2.3) == 3

    def test_as_define_value(self):
        cfg = _loads("""
!define my_sqrt: !fn:math.sqrt
result: ${my_sqrt(16)}
""")
        assert cfg['result'] == 4.0

    def test_in_fn_template_return(self):
        """!fn : returning a DraconPartial from a DraconCallable template."""
        cfg = _loads("""
!define make_greeter: !fn
  !require:str greeting: "the greeting"
  !fn : !fn:dracon.tests.test_partial._greet
    greeting: ${greeting}
greeter: !make_greeter { greeting: yo }
""")
        assert isinstance(cfg['greeter'], CallableSymbol) and cfg['greeter']._kind == 'partial'
        assert cfg['greeter'](name="world") == "yo world"


# ── serialization ───────────────────────────────────────────────────────────


class TestFnPathSerialization:
    def test_pickle_roundtrip(self):
        cfg = _loads("""
val: !fn:dracon.tests.test_partial._add
  a: 10
""")
        data = pickle.dumps(cfg['val'])
        restored = pickle.loads(data)
        assert restored(b=5) == 15

    def test_pickle_context_only_fails(self):
        p = DraconPartial("my_func", _add, {"a": 1})
        data = pickle.dumps(p)
        with pytest.raises(ValueError, match="context-only"):
            pickle.loads(data)

    def test_yaml_dump_with_kwargs(self):
        from dracon import dump
        cfg = _loads("""
val: !fn:dracon.tests.test_partial._add
  a: 10
""")
        dumped = dump(cfg)
        assert '!fn:dracon.tests.test_partial._add' in dumped
        assert 'a: 10' in dumped or 'a:' in dumped

    def test_yaml_dump_no_kwargs(self):
        from dracon import dump
        cfg = _loads("val: !fn:math.sqrt")
        dumped = dump(cfg)
        assert '!fn:math.sqrt' in dumped

    def test_yaml_dump_reload(self):
        """Full round-trip: load -> dump -> reload -> call."""
        cfg = _loads("""
val: !fn:dracon.tests.test_partial._add
  a: 10
""")
        from dracon import dump
        dumped = dump(cfg)
        cfg2 = _loads(dumped)
        assert cfg2['val'](b=5) == 15


# ── pipe integration ────────────────────────────────────────────────────────


def _step_a(x, **_):
    """Returns dict so pipe threads via kwarg-unpack."""
    return {'val': abs(x)}

def _step_b(val, **_):
    return val * 2


class TestFnPathPipe:
    def test_pipe_with_tagged_fn_path(self):
        """!fn:path as inline tagged node in pipe, single stage."""
        cfg = _loads("""
!define pipeline: !pipe
  - !fn:dracon.tests.test_partial._step_a
result: ${pipeline(x=-5)}
""")
        assert cfg['result'] == {'val': 5}

    def test_pipe_tagged_fn_path_chained(self):
        """Chain two !fn:path stages via dict output."""
        cfg = _loads("""
!define pipeline: !pipe
  - !fn:dracon.tests.test_partial._step_a
  - !fn:dracon.tests.test_partial._step_b
result: ${pipeline(x=-3)}
""")
        # _step_a(x=-3) = {'val': 3}, _step_b(val=3) = 6
        assert cfg['result'] == 6

    def test_pipe_mixed_callable_and_fn_path(self):
        """Mix DraconCallable stages and !fn:path stages."""
        cfg = _loads("""
!define first: !fn
  !require x: "input"
  val: ${abs(x)}
!define pipeline: !pipe
  - first
  - !fn:dracon.tests.test_partial._step_b
result: ${pipeline(x=-7)}
""")
        # first(x=-7) -> {val: 7}, _step_b(val=7) = 14
        assert cfg['result'] == 14

    def test_pipe_fn_path_with_prefilled_kwargs(self):
        """!fn:path with pre-filled kwargs in pipe."""
        cfg = _loads("""
!define pipeline: !pipe
  - !fn:dracon.tests.test_partial._greet { greeting: hey }
result: ${pipeline(name='world')}
""")
        assert cfg['result'] == "hey world"
