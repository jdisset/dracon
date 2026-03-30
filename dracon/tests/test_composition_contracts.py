"""Tests for !require and !assert composition-time contract instructions."""

import pytest
import tempfile
import os
from dracon import loads, DraconLoader, resolve_all_lazy
from dracon.diagnostics import CompositionError


# ── !require ──────────────────────────────────────────────────────────────────


def test_require_satisfied_by_define_same_file():
    """!require is satisfied when !define provides the var in the same file."""
    config = loads("""
!define db_engine: postgres
!require db_engine: "must set db_engine"

engine: ${db_engine}
""", raw_dict=True)
    resolve_all_lazy(config)
    assert config["engine"] == "postgres"


def test_require_satisfied_by_define_in_included_file():
    """!require in base file satisfied by !define in an included file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # write the included file that provides the var
        provider = os.path.join(tmpdir, "provider.yaml")
        with open(provider, "w") as f:
            f.write("!define environment: staging\nhost: db.staging.local\n")

        base = os.path.join(tmpdir, "base.yaml")
        with open(base, "w") as f:
            f.write(f"""
<<(<): !include file:{provider}
!require environment: "set environment"

endpoint: https://${{environment}}.api.example.com
""")

        loader = DraconLoader()
        config = loader.load(base)
        resolve_all_lazy(config)
        assert config["endpoint"] == "https://staging.api.example.com"


def test_require_satisfied_by_cli_context_var():
    """!require is satisfied by a context variable (simulating ++var=value)."""
    loader = DraconLoader(context={"runname": "exp1"})
    config = loader.loads("""
!require runname: "pass ++runname=<name> on the command line"

name: ${runname}
""")
    resolve_all_lazy(config)
    assert config["name"] == "exp1"


def test_require_unsatisfied_raises_composition_error():
    """Unsatisfied !require raises CompositionError with hint."""
    with pytest.raises(CompositionError, match="environment"):
        loads("""
!require environment: "set via ++environment or overlay"

endpoint: https://${environment}.api.example.com
""")


def test_require_unsatisfied_error_includes_hint():
    """Error message contains the user-provided hint string."""
    with pytest.raises(CompositionError, match="set via \\+\\+environment or overlay"):
        loads("""
!require environment: "set via ++environment or overlay"

value: ${environment}
""")


def test_require_satisfied_by_set_default():
    """!set_default counts as providing the variable for !require."""
    config = loads("""
!set_default db_engine: mysql
!require db_engine: "must set db_engine"

engine: ${db_engine}
""", raw_dict=True)
    resolve_all_lazy(config)
    assert config["engine"] == "mysql"


def test_require_multiple_same_var():
    """Multiple !require for the same var all pass if any source provides it."""
    with tempfile.TemporaryDirectory() as tmpdir:
        a = os.path.join(tmpdir, "a.yaml")
        with open(a, "w") as f:
            f.write('!require env: "needed in a"\nfrom_a: true\n')

        b = os.path.join(tmpdir, "b.yaml")
        with open(b, "w") as f:
            f.write('!require env: "needed in b"\nfrom_b: true\n')

        main = os.path.join(tmpdir, "main.yaml")
        with open(main, "w") as f:
            f.write(f"""
!define env: prod
<<: !include file:{a}
<<: !include file:{b}
""")

        loader = DraconLoader()
        config = loader.load(main)
        # no error -- both requirements satisfied by the single !define


def test_require_removed_from_final_tree():
    """!require nodes are removed from the composed config (pure validation)."""
    config = loads("""
!define x: 42
!require x: "need x"

value: ${x}
""", raw_dict=True)
    resolve_all_lazy(config)
    assert list(config.keys()) == ["value"]


def test_require_invalid_var_name_raises():
    """!require with non-identifier var name raises CompositionError."""
    with pytest.raises(CompositionError, match="Invalid variable name"):
        loads('!require 123bad: "hint"\nval: 1\n')


# ── !assert ───────────────────────────────────────────────────────────────────


def test_assert_passing_condition():
    """!assert with a truthy expression passes silently."""
    config = loads("""
!define port: 8080
!assert ${port > 0 and port < 65536}: "port out of range"

port: ${port}
""", raw_dict=True)
    resolve_all_lazy(config)
    assert config["port"] == 8080


def test_assert_failing_condition():
    """!assert with a falsy expression raises CompositionError."""
    with pytest.raises(CompositionError, match="port out of range"):
        loads("""
!define port: -1
!assert ${port > 0 and port < 65536}: "port out of range"

value: ${port}
""")


def test_assert_with_interpolation_referencing_config():
    """!assert can reference context variables."""
    config = loads("""
!define engine: postgres
!assert ${engine in ('postgres', 'mysql', 'sqlite')}: "unknown db engine"

db: ${engine}
""", raw_dict=True)
    resolve_all_lazy(config)
    assert config["db"] == "postgres"


def test_assert_after_if_branch():
    """!assert validates context set by !define inside an !if branch."""
    config = loads("""
!define env: prod

!if ${env == 'prod'}:
  !define retries: 5

!assert ${env == 'prod'}: "expected prod env"

retries: ${retries}
""", raw_dict=True)
    resolve_all_lazy(config)
    assert config["retries"] == 5


def test_assert_after_each_expansion():
    """!assert validates after !each has expanded."""
    config = loads("""
!define ports: [80, 443, 8080]
!define n_ports: 3

services:
  !each(p) ${ports}:
    svc_${p}:
      port: ${p}

!assert ${n_ports == 3}: "expected 3 ports"
""", raw_dict=True)
    resolve_all_lazy(config)
    assert len(config["services"]) == 3


def test_assert_removed_from_final_tree():
    """!assert nodes are removed from the final config."""
    config = loads("""
!define x: 1
!assert ${x > 0}: "x must be positive"

value: ${x}
""", raw_dict=True)
    resolve_all_lazy(config)
    assert list(config.keys()) == ["value"]


def test_assert_with_complex_expression():
    """!assert with function calls and compound comparisons."""
    config = loads("""
!define name: hello_world
!assert ${len(name) > 0 and '_' in name}: "name must be non-empty with underscore"

label: ${name}
""", raw_dict=True)
    resolve_all_lazy(config)
    assert config["label"] == "hello_world"


def test_assert_failing_complex_expression():
    """!assert with a complex expression that is falsy raises error."""
    with pytest.raises(CompositionError, match="name must be non-empty"):
        loads("""
!define name: ""
!assert ${len(name) > 0}: "name must be non-empty"

label: ${name}
""")


# ── !assert + !require combined ───────────────────────────────────────────────


def test_assert_and_require_in_same_file():
    """Both !require and !assert work together in one file."""
    config = loads("""
!define port: 443
!define env: prod
!require port: "must set port"
!require env: "must set env"
!assert ${port > 0 and port < 65536}: "port out of range"
!assert ${env in ('dev', 'staging', 'prod')}: "invalid env"

config:
  port: ${port}
  env: ${env}
""", raw_dict=True)
    resolve_all_lazy(config)
    assert config["config"]["port"] == 443
    assert config["config"]["env"] == "prod"


def test_require_unsatisfied_with_passing_assert():
    """Unsatisfied !require raises even if !assert passes."""
    with pytest.raises(CompositionError, match="must provide api_key"):
        loads("""
!define port: 80
!require api_key: "must provide api_key"
!assert ${port > 0}: "port must be positive"

port: ${port}
""")


# ── !require satisfied by cascade overlay ─────────────────────────────────────


def test_require_satisfied_by_cascade_overlay():
    """!require satisfied by a !define in a file merged via <<."""
    with tempfile.TemporaryDirectory() as tmpdir:
        overlay = os.path.join(tmpdir, "overlay.yaml")
        with open(overlay, "w") as f:
            f.write("!define region: us-east-1\n")

        base = os.path.join(tmpdir, "base.yaml")
        with open(base, "w") as f:
            f.write(f"""
<<(<): !include file:{overlay}
!require region: "must set region"

region: ${{region}}
""")

        loader = DraconLoader()
        config = loader.load(base)
        resolve_all_lazy(config)
        assert config["region"] == "us-east-1"
