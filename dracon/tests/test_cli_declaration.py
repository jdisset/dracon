"""Tests for the CliDirective record and the extended grammar on
`!require` / `!set_default` (mapping body for CLI metadata).

Step 01 of the yaml-cli-args feature set: grammar + record only. No
argparse / discovery integration here.
"""

import pytest

from dracon import DraconLoader, loads, CliDirective
from dracon.loader import compose_config_from_str
from dracon.diagnostics import CompositionError


# helpers


def _compose(content: str, **ctx):
    """Compose + post-process. compose_config_from_str already runs the full
    pipeline, so callers must provide any !require'd context themselves."""
    loader = DraconLoader(context=ctx) if ctx else DraconLoader()
    return loader.compose_config_from_str(content), loader


def _directives(content: str, **ctx) -> list[CliDirective]:
    comp, _ = _compose(content, **ctx)
    return list(comp.cli_directives)


# scalar form -- existing semantics preserved


def test_scalar_require_hint_preserved():
    """!require port : "bind port" still produces a CliDirective whose help
    carries the legacy hint string."""
    comp, _ = _compose('!require port: "bind port"\nx: 1\n', port=8080)
    # require was satisfied via context, so pending_requirements is empty
    # (the legacy "satisfied" semantics are unchanged).
    assert comp.pending_requirements == []
    assert len(comp.cli_directives) == 1
    d = comp.cli_directives[0]
    assert d.name == "port"
    assert d.kind == "require"
    assert d.help == "bind port"
    assert d.short is None
    assert d.default is None
    assert d.python_type is None
    assert d.hidden is False


def test_scalar_require_unsatisfied_still_records_directive():
    """When the context cannot satisfy the !require we still want the directive
    to have been recorded (so the CLI flag stays visible). We capture the
    composition just before the unsatisfied-check raises."""
    loader = DraconLoader()
    raw = compose_config_from_str(loader.yaml, '!require port: "bind port"\nx: 1\n')
    # post_process_composed runs the instructions and then check_pending_requirements;
    # by the time the error is raised, cli_directives is already populated.
    with pytest.raises(CompositionError, match="port"):
        loader.post_process_composed(raw)
    # the in-place mutation on `raw` carries the recorded directive.
    assert len(raw.cli_directives) == 1
    assert raw.cli_directives[0].name == "port"
    assert raw.cli_directives[0].help == "bind port"


def test_scalar_set_default_value():
    """!set_default port: 8080 still applies the default and adds a record."""
    comp, loader = _compose('!set_default port: 8080\nused: ${port}\n')
    assert "port" in comp.defined_vars
    assert comp.defined_vars["port"] == 8080
    assert len(comp.cli_directives) == 1
    d = comp.cli_directives[0]
    assert d.name == "port"
    assert d.kind == "set_default"
    assert d.default == 8080
    assert d.python_type is None


def test_scalar_typed_set_default_coerces_and_records_type():
    """!set_default:int port: 8080 stays coerced; record carries python_type=int."""
    comp, loader = _compose('!set_default:int port: "8080"\n')
    assert comp.defined_vars["port"] == 8080
    d = comp.cli_directives[0]
    assert d.kind == "set_default"
    assert d.python_type is int


# mapping form -- new


def test_mapping_require_full():
    """All mapping keys parsed onto the record."""
    loader = DraconLoader()
    raw = compose_config_from_str(
        loader.yaml,
        '!require port:\n'
        '  help: "bind port"\n'
        '  short: -p\n'
        'x: 1\n',
    )
    with pytest.raises(CompositionError):
        loader.post_process_composed(raw)
    d = raw.cli_directives[0]
    assert d.name == "port"
    assert d.kind == "require"
    assert d.help == "bind port"
    assert d.short == "-p"
    # pending_requirements should still receive the help as the hint.
    assert raw.pending_requirements[0][1] == "bind port"


def test_mapping_set_default_full():
    """!set_default mapping body: default honoured, help + short captured."""
    comp, loader = _compose(
        '!set_default workers:\n'
        '  default: 4\n'
        '  help: "worker count"\n'
        '  short: -w\n'
    )
    assert comp.defined_vars["workers"] == 4
    d = comp.cli_directives[0]
    assert d.name == "workers"
    assert d.kind == "set_default"
    assert d.default == 4
    assert d.help == "worker count"
    assert d.short == "-w"


def test_typed_set_default_mapping_coerces():
    """!set_default:int with mapping body still coerces default the same way."""
    comp, loader = _compose(
        '!set_default:int limit:\n'
        '  default: "100"\n'
        '  help: "max items"\n'
    )
    assert comp.defined_vars["limit"] == 100
    d = comp.cli_directives[0]
    assert d.python_type is int
    assert d.default == 100
    assert d.help == "max items"


def test_mapping_require_with_default_rejected():
    """!require may not carry a default."""
    with pytest.raises(CompositionError, match="default"):
        loads('!require port:\n  default: 8080\n  help: bind port\n')


def test_mapping_unknown_key_rejected():
    """Unknown body keys raise, naming the offending key."""
    with pytest.raises(CompositionError, match="bogus"):
        loads('!require port:\n  help: "bind port"\n  bogus: 1\n')


def test_short_normalisation():
    """`short: p`, `short: "-p"` both yield `"-p"`. `--port` rejected."""
    comp, _ = _compose('!require a:\n  short: -a\n', a=1)
    assert comp.cli_directives[0].short == "-a"

    comp, _ = _compose('!require b:\n  short: b\n', b=1)
    assert comp.cli_directives[0].short == "-b"

    # composition raises during the parse itself, before the require check.
    loader = DraconLoader(context={"port": 1})
    with pytest.raises(CompositionError, match="short"):
        loader.compose_config_from_str('!require port:\n  short: "--port"\n')

    loader = DraconLoader(context={"port": 1})
    with pytest.raises(CompositionError, match="short"):
        loader.compose_config_from_str('!require port:\n  short: "ab"\n')


def test_hidden_flag_default_and_set():
    comp, loader = _compose('!set_default port:\n  default: 8080\n  hidden: true\n')
    assert comp.cli_directives[0].hidden is True

    comp, loader = _compose('!set_default port: 8080\n')
    assert comp.cli_directives[0].hidden is False


# scope: directives inside !fn body are not collected


def test_inner_scope_fn_not_collected():
    """A !require inside an !fn template body is invisible to the outer
    cli_directives list."""
    content = (
        '!define greet: !fn\n'
        '  !require name: "who"\n'
        '  !fn :\n'
        '    msg: "hi ${name}"\n'
        'top: 1\n'
    )
    comp, loader = _compose(content)
    # No outer-level !require -- nothing collected.
    assert comp.cli_directives == []


def test_require_collected_even_when_satisfied():
    """A satisfied !require still surfaces as a CLI directive (CLI flag stays
    visible for override)."""
    comp, loader = _compose('!require port: "bind port"\n', port=8080)
    # satisfied, so pending_requirements stays empty
    assert comp.pending_requirements == []
    # but the directive is still recorded
    assert len(comp.cli_directives) == 1
    assert comp.cli_directives[0].name == "port"


def test_cli_directive_exported_from_dracon():
    """CliDirective is reachable from the package root."""
    import dracon
    assert hasattr(dracon, "CliDirective")
    assert dracon.CliDirective is CliDirective
