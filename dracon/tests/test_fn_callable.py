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
