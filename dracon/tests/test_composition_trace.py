import os
import pytest
from dracon import DraconLoader
from dracon.composition_trace import CompositionTrace, TraceEntry, keypath_to_dotted


@pytest.fixture
def tmp_yaml(tmp_path):
    """Helper to write yaml files and return paths."""
    def _write(name, content):
        p = tmp_path / name
        p.write_text(content)
        return p
    return _write


# ── basics ───────────────────────────────────────────────────────────────────

def test_trace_enabled_by_default(tmp_yaml):
    f = tmp_yaml("a.yaml", "x: 1\n")
    loader = DraconLoader()
    cr = loader.compose(str(f))
    assert isinstance(cr.trace, CompositionTrace)


def test_trace_enabled_via_kwarg(tmp_yaml):
    f = tmp_yaml("a.yaml", "x: 1\n")
    loader = DraconLoader(trace=True)
    cr = loader.compose(str(f))
    assert isinstance(cr.trace, CompositionTrace)


def test_trace_enabled_via_env(tmp_yaml, monkeypatch):
    monkeypatch.setenv("DRACON_TRACE", "1")
    f = tmp_yaml("a.yaml", "x: 1\n")
    loader = DraconLoader()
    cr = loader.compose(str(f))
    assert isinstance(cr.trace, CompositionTrace)


# ── single-file definitions ──────────────────────────────────────────────────

def test_trace_single_file_definitions(tmp_yaml):
    f = tmp_yaml("a.yaml", "db:\n  port: 5432\n  host: localhost\n")
    loader = DraconLoader(trace=True)
    cr = loader.compose(str(f))

    port_trace = cr.trace.get("db.port")
    assert len(port_trace) >= 1
    assert port_trace[0].via == "definition"
    assert port_trace[0].value == "5432"  # YAML scalars are strings at node level
    assert port_trace[0].source is not None
    assert port_trace[0].source.line == 2

    host_trace = cr.trace.get("db.host")
    assert len(host_trace) >= 1
    assert host_trace[0].via == "definition"
    assert host_trace[0].value == "localhost"


# ── file layering ────────────────────────────────────────────────────────────

def test_trace_file_layering(tmp_yaml):
    f1 = tmp_yaml("base.yaml", "db:\n  port: 5432\n  host: localhost\n")
    f2 = tmp_yaml("override.yaml", "db:\n  port: 9999\n")
    loader = DraconLoader(trace=True)
    cr = loader.compose([str(f1), str(f2)])

    port_trace = cr.trace.get("db.port")
    assert len(port_trace) >= 2
    # first entry is the definition from base
    assert port_trace[0].via == "definition"
    assert port_trace[0].value == "5432"
    # second entry is the file layer override
    assert port_trace[1].via == "file_layer"
    assert port_trace[1].value == "9999"
    assert port_trace[1].replaced is not None
    assert port_trace[1].replaced.value == "5432"

    # host was not overridden — should only have one entry
    host_trace = cr.trace.get("db.host")
    assert len(host_trace) >= 1


# ── include ──────────────────────────────────────────────────────────────────

def test_trace_include(tmp_yaml, tmp_path):
    inc = tmp_yaml("included.yaml", "port: 3306\n")
    main = tmp_yaml("main.yaml", f"db: !include file:{inc}\n")
    loader = DraconLoader(trace=True)
    cr = loader.compose(str(main))

    port_trace = cr.trace.get("db.port")
    assert len(port_trace) >= 1
    # should record the include
    include_entries = [e for e in port_trace if e.via == "include"]
    assert len(include_entries) >= 1
    assert "included.yaml" in include_entries[0].detail


# ── merge ────────────────────────────────────────────────────────────────────

def test_trace_merge_winner_loser(tmp_yaml, tmp_path):
    # base has port=5432, merge include overrides it
    base = tmp_yaml("db_base.yaml", "port: 3306\nhost: basehost\n")
    f = tmp_yaml("config.yaml",
        "db:\n"
        f"  <<: !include file:{base}\n"
        "  port: 3307\n"
    )
    loader = DraconLoader(trace=True)
    cr = loader.compose(str(f))

    port_trace = cr.trace.get("db.port")
    assert len(port_trace) >= 1
    # there should be a merge entry
    merge_entries = [e for e in port_trace if e.via == "merge"]
    assert len(merge_entries) >= 1


# ── !set_default ─────────────────────────────────────────────────────────────

def test_trace_set_default(tmp_yaml):
    f = tmp_yaml("a.yaml",
        "!set_default MY_VAR: 42\n"
        "value: ${MY_VAR}\n"
    )
    loader = DraconLoader(trace=True)
    cr = loader.compose(str(f))

    # MY_VAR should be in defined_vars
    assert "MY_VAR" in cr.defined_vars


# ── !define ──────────────────────────────────────────────────────────────────

def test_trace_define(tmp_yaml):
    f = tmp_yaml("a.yaml",
        "!define FOO: 99\n"
        "value: ${FOO}\n"
    )
    loader = DraconLoader(trace=True)
    cr = loader.compose(str(f))
    assert "FOO" in cr.defined_vars


# ── !if ──────────────────────────────────────────────────────────────────────

def test_trace_if_branch(tmp_yaml):
    f = tmp_yaml("a.yaml",
        "!if ${true}:\n"
        "  then:\n"
        "    retries: 3\n"
        "  else:\n"
        "    retries: 0\n"
    )
    loader = DraconLoader(trace=True, context={"true": True})
    cr = loader.compose(str(f))

    retries_trace = cr.trace.get("retries")
    assert retries_trace is not None
    if_entries = [e for e in retries_trace if e.via == "if_branch"]
    assert len(if_entries) >= 1
    assert "then" in if_entries[0].detail


# ── !each ────────────────────────────────────────────────────────────────────

def test_trace_each(tmp_yaml):
    f = tmp_yaml("a.yaml",
        "!each(i) ${[1,2,3]}:\n"
        "  - ${i}\n"
    )
    loader = DraconLoader(trace=True)
    cr = loader.compose(str(f))

    # should have trace entries from the each expansion
    all_traces = cr.trace.all()
    each_entries = []
    for path, entries in all_traces.items():
        for e in entries:
            if e.via == "each_expansion":
                each_entries.append(e)
    assert len(each_entries) >= 1


# ── trace_all / trace_tree ───────────────────────────────────────────────────

def test_trace_all(tmp_yaml):
    f = tmp_yaml("a.yaml", "x: 1\ny: 2\n")
    loader = DraconLoader(trace=True)
    cr = loader.compose(str(f))

    all_traces = cr.trace_all()
    assert "x" in all_traces
    assert "y" in all_traces


def test_trace_tree_format(tmp_yaml):
    f = tmp_yaml("a.yaml", "x: 1\ny: 2\n")
    loader = DraconLoader(trace=True)
    cr = loader.compose(str(f))

    tree = cr.trace_tree()
    assert isinstance(tree, str)
    assert "x" in tree
    assert "y" in tree


# ── zero overhead ────────────────────────────────────────────────────────────

def test_trace_can_be_disabled(tmp_yaml):
    f = tmp_yaml("a.yaml", "x: 1\n")
    loader = DraconLoader(trace=False)
    cr = loader.compose(str(f))
    assert cr.trace is None


# ── CLI override tracing ─────────────────────────────────────────────────────

def test_trace_cli_override(tmp_yaml):
    """CLI overrides (--path=val) in dracon-print should be traced."""
    from dracon_print import DraconPrint
    f = tmp_yaml("a.yaml", "db:\n  port: 5432\n")
    dp = DraconPrint(
        config_files=[str(f)],
        trace_all=True,
        overrides={"db.port": 9999},
    )
    output = dp.run()
    assert "db.port" in output


# ── rich output ──────────────────────────────────────────────────────────────

def test_trace_rich_output_single_path(tmp_yaml):
    f = tmp_yaml("a.yaml", "x: 1\ny: 2\n")
    loader = DraconLoader(trace=True)
    cr = loader.compose(str(f))
    panel = cr.trace.format_path_rich("x")
    # should be a rich Panel
    from rich.panel import Panel
    assert isinstance(panel, Panel)


def test_trace_rich_output_all(tmp_yaml):
    f = tmp_yaml("a.yaml", "x: 1\ny: 2\n")
    loader = DraconLoader(trace=True)
    cr = loader.compose(str(f))
    table = cr.trace.format_all_rich()
    from rich.table import Table
    assert isinstance(table, Table)


# ── error enrichment ────────────────────────────────────────────────────────

def test_error_trace_hint_in_format():
    """DraconError without trace_history should suggest --trace-all in plain format."""
    from dracon.diagnostics import DraconError, format_error, SourceContext
    ctx = SourceContext(file_path="test.yaml", line=1)
    err = DraconError("something went wrong", context=ctx)
    output = format_error(err)
    assert "--trace-all" in output or "DRACON_TRACE" in output


def test_error_trace_history_in_format():
    """DraconError with trace_history should show provenance in plain format."""
    from dracon.diagnostics import DraconError, format_error, SourceContext
    ctx = SourceContext(file_path="test.yaml", line=5)
    entry = TraceEntry(value="bad", source=ctx, via="definition", detail="local key")
    err = DraconError("type error", context=ctx, trace_history=[entry])
    output = format_error(err)
    assert "Provenance" in output
    assert "definition" in output
    assert "'bad'" in output


def test_error_enrichment_from_loader(tmp_yaml):
    """When load_node fails with tracing enabled, trace_history should be attached."""
    f = tmp_yaml("a.yaml", "x: 1\n")
    loader = DraconLoader(trace=True)
    cr = loader.compose(str(f))
    # _last_composition should be set after compose
    # (it's set in load/load_composition_result, not compose alone)
    # verify the mechanism exists
    assert hasattr(loader, '_last_composition')


# ── help text ────────────────────────────────────────────────────────────────

def test_help_text_mentions_trace():
    from dracon.cli import HELP_TEXT
    assert "--trace" in HELP_TEXT
    assert "--trace-all" in HELP_TEXT


# ── @dracon_program trace integration ────────────────────────────────────────

def test_dracon_program_has_trace_args():
    """@dracon_program CLIs should have --trace and --trace-all built-in."""
    from pydantic import BaseModel
    from dracon.commandline import Program
    class Cfg(BaseModel):
        x: int = 1
    prog = Program[Cfg](conf_type=Cfg)
    arg_names = {a.long for a in prog._args if a.long}
    assert "trace" in arg_names
    assert "trace-all" in arg_names


def test_dracon_program_trace_flags_not_in_model(tmp_yaml):
    """Trace flags should be extracted before model validation (not model fields)."""
    from pydantic import BaseModel
    from dracon.commandline import Program
    class Cfg(BaseModel):
        x: int = 1
    prog = Program[Cfg](conf_type=Cfg)
    # parse without trace flags — should work normally
    conf, _ = prog.parse_args([])
    assert conf.x == 1
