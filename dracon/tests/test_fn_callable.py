"""Tests for !fn callable templates."""
import pytest
from pydantic import BaseModel
from dracon.loader import DraconLoader
from dracon.diagnostics import CompositionError


class SimpleModel(BaseModel):
    field: int
    name: str = "default"


# --- template fixture helpers ---

def _loads(yaml_str, **ctx):
    loader = DraconLoader(context={**ctx, 'SimpleModel': SimpleModel})
    config = loader.loads(yaml_str)
    config.resolve_all_lazy()
    return config


# --- core behavior ---


class TestFnFileBasic:
    """!fn file: captures a template as a DraconCallable."""

    def test_fn_file_stores_callable(self):
        from dracon.callable import DraconCallable
        yaml = """
        !define f: !fn pkg:dracon:tests/fn_endpoint.yaml
        result: ${isinstance(f, DraconCallable)}
        """
        loader = DraconLoader(context={'DraconCallable': DraconCallable})
        config = loader.loads(yaml)
        config.resolve_all_lazy()
        assert config['result'] is True

    def test_fn_file_call_returns_mapping(self):
        yaml = """
        !define f: !fn pkg:dracon:tests/fn_endpoint.yaml
        result: ${f(name='api', port=443)}
        """
        config = _loads(yaml)
        assert config['result']['url'] == 'https://api.example.com:443'
        assert config['result']['health'] == 'https://api.example.com:443/health'

    def test_fn_file_with_result_key(self):
        """File template that returns a mapping with computed value."""
        yaml = """
        !define double: !fn pkg:dracon:tests/fn_double.yaml
        result: ${double(x=21)}
        """
        config = _loads(yaml)
        assert config['result']['result'] == 42


class TestFnInlineBasic:
    """!fn on a mapping node captures an inline template."""

    def test_fn_inline_mapping(self):
        yaml = """
        !define greet: !fn
          !require who: "name"
          msg: hello ${who}
        result: ${greet(who='world')}
        """
        config = _loads(yaml)
        assert config['result']['msg'] == 'hello world'

    def test_fn_inline_with_defaults(self):
        yaml = """
        !define make_ep: !fn
          !require name: "svc"
          !set_default port: 8080
          url: https://${name}:${port}
        result: ${make_ep(name='api')}
        """
        config = _loads(yaml)
        assert config['result']['url'] == 'https://api:8080'


class TestFnRequireSetDefault:
    """!require and !set_default work inside templates."""

    def test_require_satisfied(self):
        yaml = """
        !define f: !fn pkg:dracon:tests/fn_endpoint.yaml
        result: ${f(name='svc')}
        """
        config = _loads(yaml)
        assert 'svc' in config['result']['url']

    def test_require_missing_raises(self):
        yaml = """
        !define f: !fn
          !require name: "service name"
          url: https://${name}
        result: ${f()}
        """
        with pytest.raises(Exception, match="name"):
            _loads(yaml)

    def test_set_default_used(self):
        yaml = """
        !define f: !fn pkg:dracon:tests/fn_endpoint.yaml
        result: ${f(name='svc')}
        """
        config = _loads(yaml)
        assert ':8080' in config['result']['url']

    def test_set_default_overridden(self):
        yaml = """
        !define f: !fn pkg:dracon:tests/fn_endpoint.yaml
        result: ${f(name='svc', port=443)}
        """
        config = _loads(yaml)
        assert ':443' in config['result']['url']

    def test_args_consumed(self):
        """Arguments don't appear in output (consumed by !require/!set_default)."""
        yaml = """
        !define f: !fn pkg:dracon:tests/fn_endpoint.yaml
        result: ${f(name='svc')}
        """
        config = _loads(yaml)
        assert 'name' not in config['result']
        assert 'port' not in config['result']

    def test_multiple_calls_independent(self):
        yaml = """
        !define f: !fn pkg:dracon:tests/fn_endpoint.yaml
        a: ${f(name='alpha', port=1)}
        b: ${f(name='beta', port=2)}
        """
        config = _loads(yaml)
        assert 'alpha' in config['a']['url']
        assert ':1' in config['a']['url']
        assert 'beta' in config['b']['url']
        assert ':2' in config['b']['url']


# --- tag syntax ---


class TestFnTagSyntax:
    """!callable_name { args } invocation from YAML tags."""

    def test_tag_invocation_mapping(self):
        yaml = """
        !define make_ep: !fn
          !require name: "svc"
          !set_default port: 8080
          url: https://${name}:${port}
        result: !make_ep
          name: api
          port: 443
        """
        config = _loads(yaml)
        assert config['result']['url'] == 'https://api:443'

    def test_tag_invocation_flow(self):
        yaml = """
        !define make_ep: !fn
          !require name: "svc"
          !set_default port: 8080
          url: https://${name}:${port}
        result: !make_ep { name: api, port: 443 }
        """
        config = _loads(yaml)
        assert config['result']['url'] == 'https://api:443'

    def test_tag_invocation_with_interpolation_arg(self):
        yaml = """
        !define svc_name: api
        !define make_ep: !fn
          !require name: "svc"
          url: https://${name}.example.com
        result: !make_ep { name: "${svc_name}" }
        """
        config = _loads(yaml)
        assert config['result']['url'] == 'https://api.example.com'


# --- expression syntax ---


class TestFnExpressionSyntax:
    """${callable(kwargs)} invocation from interpolation."""

    def test_expression_call(self):
        yaml = """
        !define f: !fn
          !require x: "val"
          result: ${x * 2}
        val: ${f(x=5)}
        """
        config = _loads(yaml)
        assert config['val']['result'] == 10

    def test_expression_list_comprehension(self):
        yaml = """
        !define names: ${['a', 'b', 'c']}
        !define make_ep: !fn
          !require name: "svc"
          url: https://${name}.example.com
        endpoints: ${[make_ep(name=n) for n in names]}
        """
        config = _loads(yaml)
        assert len(config['endpoints']) == 3
        assert config['endpoints'][0]['url'] == 'https://a.example.com'
        assert config['endpoints'][2]['url'] == 'https://c.example.com'

    def test_expression_chaining(self):
        """Result of one callable used as input to another operation."""
        yaml = """
        !define make_ep: !fn
          !require name: "svc"
          url: https://${name}.example.com
        result: ${make_ep(name='api')['url'].upper()}
        """
        config = _loads(yaml)
        assert config['result'] == 'HTTPS://API.EXAMPLE.COM'


# --- isolation ---


class TestFnIsolation:
    """Arguments don't leak into caller scope."""

    def test_args_dont_leak(self):
        yaml = """
        !define outer_name: original
        !define f: !fn
          !require name: "svc"
          url: https://${name}
        ep: ${f(name='inner')}
        check: ${outer_name}
        """
        config = _loads(yaml)
        assert config['ep']['url'] == 'https://inner'
        assert config['check'] == 'original'

    def test_concurrent_calls_isolated(self):
        """Multiple calls in a list comprehension don't interfere."""
        yaml = """
        !define f: !fn
          !require x: "val"
          doubled: ${x * 2}
        results: ${[f(x=i) for i in range(5)]}
        """
        config = _loads(yaml)
        assert [r['doubled'] for r in config['results']] == [0, 2, 4, 6, 8]


# --- inline scalar !fn (expression lambdas) ---


class TestFnInlineScalar:
    """!define f: !fn ${expr} -- expression lambdas returning scalars."""

    def test_scalar_arithmetic(self):
        yaml = """
        !define double: !fn ${x * 2}
        result: ${double(x=21)}
        """
        config = _loads(yaml)
        assert config['result'] == 42

    def test_scalar_string_expr(self):
        yaml = """
        !define greet: !fn ${"Hello " + name}
        result: ${greet(name="world")}
        """
        config = _loads(yaml)
        assert config['result'] == "Hello world"

    def test_scalar_multiple_calls(self):
        yaml = """
        !define inc: !fn ${x + 1}
        a: ${inc(x=0)}
        b: ${inc(x=10)}
        """
        config = _loads(yaml)
        assert config['a'] == 1
        assert config['b'] == 11

    def test_scalar_in_comprehension(self):
        yaml = """
        !define sq: !fn ${x ** 2}
        results: ${[sq(x=i) for i in range(5)]}
        """
        config = _loads(yaml)
        assert config['results'] == [0, 1, 4, 9, 16]

    def test_scalar_tag_invocation(self):
        """!fn_name { args } works for scalar-returning callables."""
        yaml = """
        !define double: !fn ${x * 2}
        result: !double { x: 21 }
        """
        config = _loads(yaml)
        assert config['result'] == 42

    def test_scalar_chaining(self):
        yaml = """
        !define double: !fn ${x * 2}
        result: ${str(double(x=21))}
        """
        config = _loads(yaml)
        assert config['result'] == '42'


# --- !fn : return marker ---


class TestFnReturnMarker:
    """!fn : value inside a body marks the return value."""

    def test_return_scalar_with_outer_fn(self):
        """!fn body with !fn : returns scalar, not mapping."""
        yaml = """
        !define double: !fn
          !require x: "number"
          !fn : ${x * 2}
        result: ${double(x=21)}
        """
        config = _loads(yaml)
        assert config['result'] == 42

    def test_return_scalar_without_outer_fn(self):
        """!fn : inside !define body implies callable creation."""
        yaml = """
        !define double:
          !require x: "number"
          !fn : ${x * 2}
        result: ${double(x=21)}
        """
        config = _loads(yaml)
        assert config['result'] == 42

    def test_return_with_set_default(self):
        yaml = """
        !define greet:
          !require name: "who"
          !set_default prefix: Hello
          !fn : ${prefix + " " + name}
        result: ${greet(name="world")}
        overridden: ${greet(name="world", prefix="Hi")}
        """
        config = _loads(yaml)
        assert config['result'] == "Hello world"
        assert config['overridden'] == "Hi world"

    def test_return_mapping_value(self):
        """!fn : with a mapping value returns that mapping."""
        yaml = """
        !define extract:
          !require data: "input list"
          !fn :
            count: ${len(data)}
            first: ${data[0]}
        result: ${extract(data=[10, 20, 30])}
        """
        config = _loads(yaml)
        assert config['result']['count'] == 3
        assert config['result']['first'] == 10

    def test_return_with_define_helpers(self):
        """!define inside body provides intermediate values for !fn return."""
        yaml = """
        !define compute:
          !require x: "number"
          !define intermediate: ${x + 1}
          !fn : ${intermediate * 2}
        result: ${compute(x=4)}
        """
        config = _loads(yaml)
        assert config['result'] == 10

    def test_return_tag_invocation(self):
        """Tag syntax works with !fn : return."""
        yaml = """
        !define double:
          !require x: "number"
          !fn : ${x * 2}
        result: !double { x: 21 }
        """
        config = _loads(yaml)
        assert config['result'] == 42

    def test_return_multiple_fn_keys_error(self):
        """Multiple !fn : keys should error."""
        yaml = """
        !define bad:
          !require x: "number"
          !fn : ${x * 2}
          !fn : ${x * 3}
        result: ${bad(x=1)}
        """
        with pytest.raises(Exception):
            _loads(yaml)

    def test_return_in_comprehension(self):
        yaml = """
        !define sq:
          !require x: "number"
          !fn : ${x ** 2}
        results: ${[sq(x=i) for i in range(5)]}
        """
        config = _loads(yaml)
        assert config['results'] == [0, 1, 4, 9, 16]


# --- callable() tag invocation ---


class TestCallableTagInvocation:
    """Any callable in context works as a YAML tag."""

    def test_python_function_tag_with_kwargs(self):
        def make_url(host='localhost', port=80):
            return f"http://{host}:{port}"

        yaml = """
        result: !make_url { host: example.com, port: 443 }
        """
        config = _loads(yaml, make_url=make_url)
        assert config['result'] == "http://example.com:443"

    def test_python_function_tag_scalar_arg(self):
        """!callable "scalar" passes scalar as single positional arg."""
        yaml = """
        !define upper: ${str.upper}
        result: !upper "hello"
        """
        config = _loads(yaml)
        assert config['result'] == "HELLO"

    def test_lambda_tag(self):
        yaml = """
        result: !double "21"
        """
        config = _loads(yaml, double=lambda x: int(x) * 2)
        assert config['result'] == 42

    def test_callable_with_no_args(self):
        """Tag invocation with no arguments."""
        def get_answer():
            return 42

        yaml = """
        result: !get_answer
        """
        config = _loads(yaml, get_answer=get_answer)
        assert config['result'] == 42

    def test_non_callable_not_tag(self):
        """!define'd non-callable falls through to type resolution, not tag invocation."""
        yaml = """
        !define my_val: 42
        result: ${my_val}
        """
        config = _loads(yaml)
        assert config['result'] == 42

    def test_callable_tag_overrides_type(self):
        """Explicit !define callable shadows implicit type resolution."""
        def custom_int(x):
            return int(x) + 1000

        yaml = """
        result: !custom_int "42"
        """
        config = _loads(yaml, custom_int=custom_int)
        assert config['result'] == 1042


# --- return types ---


class TestFnReturnTypes:
    """Templates can return mappings or typed objects."""

    def test_mapping_return(self):
        yaml = """
        !define f: !fn pkg:dracon:tests/fn_endpoint.yaml
        result: ${f(name='api', port=443)}
        """
        config = _loads(yaml)
        assert 'url' in config['result']
        assert 'health' in config['result']

    def test_typed_object_return(self):
        """Template returning a constructed Pydantic model."""
        yaml = """
        !define make_model: !fn
          !require val: "field value"
          !set_default model_name: from_fn
          field: ${val}
          name: ${model_name}
        result: !SimpleModel ${make_model(val=42)}
        """
        config = _loads(yaml)
        assert isinstance(config['result'], SimpleModel)
        assert config['result'].field == 42
        assert config['result'].name == 'from_fn'


# --- error cases ---


class TestFnErrors:
    """Error handling and validation."""

    def test_fn_invalid_scalar_no_colon(self):
        yaml = """
        !define f: !fn nocolon
        result: ${f()}
        """
        with pytest.raises(CompositionError, match="loader reference"):
            _loads(yaml)

    def test_fn_file_not_found(self):
        yaml = """
        !define f: !fn file:nonexistent_template_xyz.yaml
        result: ${f()}
        """
        with pytest.raises(FileNotFoundError):
            _loads(yaml)

    def test_recursion_guard(self):
        """Self-referencing template should raise, not infinite loop."""
        yaml = """
        !define f: !fn
          !require x: "val"
          result: ${f(x=x)}
        val: ${f(x=1)}
        """
        with pytest.raises(Exception):
            _loads(yaml)


# --- integration with other features ---


class TestFnIntegration:
    """!fn composes with other dracon features."""

    def test_fn_with_if_inside_template(self):
        yaml = """
        !define f: !fn pkg:dracon:tests/fn_with_if.yaml
        prod: ${f(name='api', is_prod=True)}
        dev: ${f(name='api', is_prod=False)}
        """
        config = _loads(yaml)
        assert 'monitoring' in config['prod']
        assert 'monitoring' not in config['dev']

    def test_fn_with_each(self):
        """Callable invoked per !each iteration."""
        yaml = """
        !define services: ${['web', 'api', 'worker']}
        !define make_ep: !fn
          !require name: "svc"
          url: https://${name}.example.com
        endpoints:
          !each(svc) ${services}:
            ${svc}: ${make_ep(name=svc)}
        """
        config = _loads(yaml)
        assert config['endpoints']['web']['url'] == 'https://web.example.com'
        assert config['endpoints']['api']['url'] == 'https://api.example.com'

    def test_fn_with_lazy_define(self):
        """!define with fn result works with lazy evaluation."""
        yaml = """
        !define make_data: !fn
          !require val: "field value"
          field: ${val}
          name: computed
        !define m: ${make_data(val=7)}
        result: ${m['field']}
        """
        config = _loads(yaml)
        assert config['result'] == 7


# --- nested !fn tag invocation ---


class TestNestedFnTagInvocation:
    """Sibling !define'd callables used as tags inside !fn bodies."""

    def test_sibling_callable_tag_in_fn_body(self):
        """!Inner tag inside !Outer's !fn body resolves at construction time."""
        yaml = """
        !define Inner: !fn
          !require name: "identifier"
          !fn :
            result: hello ${name}
        !define Outer: !fn
          !require label: "what to build"
          !fn :
            items:
              - !Inner { name: from-outer }
        out: !Outer { label: test }
        """
        config = _loads(yaml)
        assert config['out']['items'][0]['result'] == 'hello from-outer'

    def test_nested_callable_tag_mapping_in_fn(self):
        """Tag invocation with mapping kwargs inside !fn body."""
        yaml = """
        !define Agent: !fn
          !require name: "agent name"
          !require prompt: "what to do"
          !fn :
            agent_name: ${name}
            agent_prompt: ${prompt}
        !define Campaign: !fn
          !require goal: "campaign goal"
          !fn :
            jobs:
              - !Agent { name: director, prompt: "${goal}" }
        result: !Campaign { goal: test-goal }
        """
        config = _loads(yaml)
        assert config['result']['jobs'][0]['agent_name'] == 'director'
        assert config['result']['jobs'][0]['agent_prompt'] == 'test-goal'

    def test_multiple_sibling_tags_in_fn_body(self):
        """Multiple different sibling !define tags in the same !fn body."""
        yaml = """
        !define Agent: !fn
          !require name: "id"
          !fn :
            type: agent
            name: ${name}
        !define Relay: !fn
          !require channel: "ch"
          !fn :
            type: relay
            channel: ${channel}
        !define System: !fn
          !fn :
            job: !Agent { name: front }
            edge: !Relay { channel: events }
        result: !System {}
        """
        config = _loads(yaml)
        assert config['result']['job']['name'] == 'front'
        assert config['result']['edge']['channel'] == 'events'

    def test_three_level_nesting(self):
        """Callable A used inside B, B used inside C -- three levels deep."""
        yaml = """
        !define Cell: !fn
          !require val: "cell value"
          !fn :
            cell: ${val}
        !define Row: !fn
          !require a: "first"
          !require b: "second"
          !fn :
            row:
              - !Cell { val: "${a}" }
              - !Cell { val: "${b}" }
        !define Grid: !fn
          !fn :
            grid:
              - !Row { a: x, b: y }
        result: !Grid {}
        """
        config = _loads(yaml)
        cells = config['result']['grid'][0]['row']
        assert cells[0]['cell'] == 'x'
        assert cells[1]['cell'] == 'y'

    def test_callable_invoked_multiple_times_in_fn(self):
        """Same sibling callable used more than once in one !fn body."""
        yaml = """
        !define Item: !fn
          !require id: "item id"
          !fn : ${id}
        !define Bundle: !fn
          !fn :
            first: !Item { id: one }
            second: !Item { id: two }
            third: !Item { id: three }
        result: !Bundle {}
        """
        config = _loads(yaml)
        assert config['result']['first'] == 'one'
        assert config['result']['second'] == 'two'
        assert config['result']['third'] == 'three'

    def test_scalar_callable_tag_in_fn_body(self):
        """Scalar-returning callable used as tag inside !fn body."""
        yaml = """
        !define double: !fn ${x * 2}
        !define Wrapper: !fn
          !require n: "number"
          !fn :
            val: !double { x: "${n}" }
        result: !Wrapper { n: 21 }
        """
        config = _loads(yaml)
        assert config['result']['val'] == 42

    def test_fn_body_callable_with_each(self):
        """!each inside !fn body producing callable tag invocations."""
        yaml = """
        !define Agent: !fn
          !require name: "agent name"
          !require prompt: "prompt"
          !fn :
            agent_name: ${name}
            agent_prompt: ${prompt}
        !define Team: !fn
          !require members: "member list"
          !fn :
            agents:
              !each(m) ${members}:
                - !Agent { name: "${m}", prompt: "do ${m}" }
        result: !Team
          members:
            - alice
            - bob
        """
        config = _loads(yaml)
        agents = config['result']['agents']
        assert len(agents) == 2
        assert agents[0]['agent_name'] == 'alice'
        assert agents[1]['agent_prompt'] == 'do bob'

    def test_callable_reuse_across_separate_invocations(self):
        """Same outer callable invoked twice -- inner tags resolve both times."""
        yaml = """
        !define Inner: !fn
          !require x: "val"
          !fn : ${x}
        !define Outer: !fn
          !require a: "first"
          !require b: "second"
          !fn :
            first: !Inner { x: "${a}" }
            second: !Inner { x: "${b}" }
        r1: !Outer { a: hello, b: world }
        r2: !Outer { a: foo, b: bar }
        """
        config = _loads(yaml)
        assert config['r1']['first'] == 'hello'
        assert config['r1']['second'] == 'world'
        assert config['r2']['first'] == 'foo'
        assert config['r2']['second'] == 'bar'


# --- !fn file:$DIR/ bug (interpolated loader scheme) ---


class TestFnFileDollarDir:
    """!fn file:$DIR/... must load the file, not return the path string."""

    def test_fn_file_dollar_dir_basic(self, tmp_path):
        """Core reproduction: !fn file:$DIR/template.yaml creates a callable."""
        (tmp_path / "template.yaml").write_text(
            "!require x: 'val'\nresult: ${x * 2}\n"
        )
        (tmp_path / "main.yaml").write_text(
            "!define f: !fn file:$DIR/template.yaml\n"
            "out: ${f(x=21)}\n"
        )
        loader = DraconLoader()
        config = loader.load(str(tmp_path / "main.yaml"))
        config.resolve_all_lazy()
        assert config['out']['result'] == 42

    def test_fn_file_dollar_dir_returns_mapping(self, tmp_path):
        """Callable from file:$DIR returns proper template output, not path string."""
        (tmp_path / "endpoint.yaml").write_text(
            "!require name: 'svc'\nurl: https://${name}.example.com\n"
        )
        (tmp_path / "main.yaml").write_text(
            "!define make_ep: !fn file:$DIR/endpoint.yaml\n"
            "api: ${make_ep(name='api')}\n"
        )
        loader = DraconLoader()
        config = loader.load(str(tmp_path / "main.yaml"))
        config.resolve_all_lazy()
        assert config['api']['url'] == 'https://api.example.com'

    def test_fn_file_dollar_dir_tag_invocation(self, tmp_path):
        """Callable from file:$DIR works with tag-style invocation."""
        (tmp_path / "greet.yaml").write_text(
            "!require who: 'name'\nmsg: hello ${who}\n"
        )
        (tmp_path / "main.yaml").write_text(
            "!define greet: !fn file:$DIR/greet.yaml\n"
            "result: !greet { who: world }\n"
        )
        loader = DraconLoader()
        config = loader.load(str(tmp_path / "main.yaml"))
        config.resolve_all_lazy()
        assert config['result']['msg'] == 'hello world'

    def test_fn_file_dollar_dir_in_subdir(self, tmp_path):
        """$DIR resolves relative to the file containing the !fn."""
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "tmpl.yaml").write_text("!require v: 'v'\nval: ${v}\n")
        (sub / "main.yaml").write_text(
            "!define tmpl: !fn file:$DIR/tmpl.yaml\n"
            "out: ${tmpl(v='hello')}\n"
        )
        loader = DraconLoader()
        config = loader.load(str(sub / "main.yaml"))
        config.resolve_all_lazy()
        assert config['out']['val'] == 'hello'

    def test_fn_file_dollar_dir_multiple_calls(self, tmp_path):
        """Same $DIR-based callable invoked multiple times."""
        (tmp_path / "double.yaml").write_text(
            "!require x: 'val'\nresult: ${x * 2}\n"
        )
        (tmp_path / "main.yaml").write_text(
            "!define dbl: !fn file:$DIR/double.yaml\n"
            "a: ${dbl(x=5)}\n"
            "b: ${dbl(x=10)}\n"
        )
        loader = DraconLoader()
        config = loader.load(str(tmp_path / "main.yaml"))
        config.resolve_all_lazy()
        assert config['a']['result'] == 10
        assert config['b']['result'] == 20

    def test_fn_expression_lambda_still_works(self):
        """Pure ${expr} interpolable is still treated as expression lambda."""
        yaml = """
        !define dbl: !fn ${x * 2}
        result: ${dbl(x=21)}
        """
        config = _loads(yaml)
        assert config['result'] == 42

    def test_fn_pkg_still_works(self):
        """Regression: pkg: scheme still works (no InterpolableNode involved)."""
        yaml = """
        !define f: !fn pkg:dracon:tests/fn_double.yaml
        result: ${f(x=21)}
        """
        config = _loads(yaml)
        assert config['result']['result'] == 42

    def test_fn_file_dollar_dir_with_require(self, tmp_path):
        """Template loaded via file:$DIR respects !require."""
        (tmp_path / "strict.yaml").write_text(
            "!require name: 'service name'\n"
            "!require port: 'port number'\n"
            "addr: ${name}:${port}\n"
        )
        (tmp_path / "main.yaml").write_text(
            "!define mk: !fn file:$DIR/strict.yaml\n"
            "svc: ${mk(name='web', port=8080)}\n"
        )
        loader = DraconLoader()
        config = loader.load(str(tmp_path / "main.yaml"))
        config.resolve_all_lazy()
        assert config['svc']['addr'] == 'web:8080'
