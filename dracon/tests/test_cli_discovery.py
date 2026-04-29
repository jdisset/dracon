"""Tests for the CLI discovery pre-pass.

Step 02 of the yaml-cli-args feature set: a pure function that composes
the user's `+`-layered configs far enough to collect the
`CliDirective` records. No argparse work here.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from dracon import CliDirective, DraconLoader
from dracon.cli_discovery import discover_cli_directives


def _write(tmp_path: Path, name: str, content: str) -> str:
    p = tmp_path / name
    p.write_text(textwrap.dedent(content).lstrip())
    return f"file:{p.as_posix()}"


def test_discover_from_single_file(tmp_path):
    src = _write(
        tmp_path,
        "layer.yaml",
        """
        !require port:
          help: "bind port"
          short: -p
        !set_default workers: 4
        x: 1
        """,
    )
    out = discover_cli_directives([src], seed_context={})
    names = {d.name for d in out}
    assert names == {"port", "workers"}
    by_name = {d.name: d for d in out}
    assert by_name["port"].kind == "require"
    assert by_name["port"].help == "bind port"
    assert by_name["port"].short == "-p"
    assert by_name["workers"].kind == "set_default"
    assert by_name["workers"].default == 4


def test_discover_from_multiple_files_merge(tmp_path):
    """Two layers both declare `port`; last layer's record wins."""
    a = _write(
        tmp_path,
        "a.yaml",
        """
        !set_default port:
          default: 8080
          help: "first layer"
        """,
    )
    b = _write(
        tmp_path,
        "b.yaml",
        """
        !set_default port:
          default: 9090
          help: "second layer"
          short: -p
        """,
    )
    out = discover_cli_directives([a, b], seed_context={})
    assert len(out) == 1
    d = out[0]
    assert d.name == "port"
    assert d.help == "second layer"
    assert d.short == "-p"
    assert d.default == 9090


def test_discover_skips_inner_scopes(tmp_path):
    """A !require inside an !fn body is not surfaced."""
    src = _write(
        tmp_path,
        "fn.yaml",
        """
        !define greet: !fn
          !require name: "who"
          !fn :
            msg: "hi ${name}"
        top: 1
        """,
    )
    out = discover_cli_directives([src], seed_context={})
    assert out == []


def test_discover_with_seed_context_satisfies_require(tmp_path):
    """Seeded context satisfies the require, but the CLI record is still emitted."""
    src = _write(
        tmp_path,
        "req.yaml",
        """
        !require port: "bind port"
        used: ${port}
        """,
    )
    out = discover_cli_directives([src], seed_context={"port": 8080})
    assert [d.name for d in out] == ["port"]
    assert out[0].kind == "require"


def test_discover_empty_no_layers():
    assert discover_cli_directives([], seed_context={}) == []


def test_discover_unsatisfied_require_does_not_raise(tmp_path):
    """The pre-pass is fail-soft: unsatisfied !require still returns the
    directive instead of raising. The real CLI run re-validates later."""
    src = _write(
        tmp_path,
        "req.yaml",
        """
        !require port: "bind port"
        used: ${port}
        """,
    )
    out = discover_cli_directives([src], seed_context={})
    assert [d.name for d in out] == ["port"]
    assert out[0].help == "bind port"


def test_discover_missing_file_in_help_mode(tmp_path):
    """A missing file is reported as a soft error: discovery returns whatever
    it could collect from the layers that did compose."""
    good = _write(tmp_path, "good.yaml", "!set_default port: 8080\n")
    missing = "file:" + (tmp_path / "nope.yaml").as_posix()
    # default: errors propagate
    with pytest.raises(Exception):
        discover_cli_directives([good, missing], seed_context={})
    # soft mode: return partial directives, no exception
    out = discover_cli_directives([good, missing], seed_context={}, soft=True)
    assert [d.name for d in out] == ["port"]


def test_discovery_is_pure(tmp_path):
    """Same inputs -> same records. Caller's seed context is not mutated."""
    src = _write(
        tmp_path,
        "p.yaml",
        """
        !set_default port:
          default: 8080
          help: "bind port"
        """,
    )
    seed = {"existing": "x"}
    a = discover_cli_directives([src], seed_context=seed)
    b = discover_cli_directives([src], seed_context=seed)
    assert [(d.name, d.kind, d.help, d.default) for d in a] == \
           [(d.name, d.kind, d.help, d.default) for d in b]
    assert seed == {"existing": "x"}


def test_discover_uses_custom_loader_factory(tmp_path):
    """`loader_factory` allows callers to inject context types / schemes."""
    src = _write(
        tmp_path,
        "p.yaml",
        '!set_default:int port:\n  default: "4242"\n  help: "p"\n',
    )

    seen = []

    def factory(**kwargs):
        seen.append(kwargs)
        return DraconLoader(**kwargs)

    out = discover_cli_directives([src], seed_context={}, loader_factory=factory)
    assert seen, "loader_factory must be invoked"
    assert out[0].python_type is int
    assert out[0].default == 4242


# ── flag discovery walks through `!include` (and `<<(<): !include`) ──────


def test_discover_walks_through_propagating_include(tmp_path):
    """A wrapper file that pulls in a vocabulary via ``<<(<): !include``
    must surface that vocabulary's CLI directives. This is the natural
    "wrapper file" pattern: ship a vocabulary, override a few values in
    a thin wrapper, still get the vocabulary's flags in ``--help``.
    """
    extras = _write(
        tmp_path,
        "extras.yaml",
        """
        !set_default greeting:
          default: "hello"
          help: "what to print"
          short: -g
        !set_default count:
          default: 1
          help: "how many times"
          short: -n
        result: "${greeting} x ${count}"
        """,
    )
    wrapper = _write(
        tmp_path,
        "wrapper.yaml",
        f"""
        !define count: 5
        <<(<): !include {extras}
        """,
    )
    out = discover_cli_directives([wrapper], seed_context={})
    names = {d.name for d in out}
    assert {"greeting", "count"} <= names, (
        f"vocabulary flags not propagated through propagating include; got {names}"
    )


def test_discover_walks_through_plain_merge_include(tmp_path):
    """``<<: !include other.yaml`` must also surface other.yaml's flags."""
    extras = _write(
        tmp_path,
        "extras.yaml",
        """
        !set_default port:
          default: 8080
          help: "bind port"
          short: -p
        """,
    )
    wrapper = _write(
        tmp_path,
        "wrapper.yaml",
        f"""
        <<: !include {extras}
        """,
    )
    out = discover_cli_directives([wrapper], seed_context={})
    names = {d.name for d in out}
    assert "port" in names, f"flags not propagated through plain merge include; got {names}"


def test_discover_walks_through_top_level_include(tmp_path):
    """``!include other.yaml`` at the top level surfaces other.yaml's flags."""
    extras = _write(
        tmp_path,
        "extras.yaml",
        """
        !set_default level:
          default: "info"
          help: "log level"
        """,
    )
    wrapper = _write(
        tmp_path,
        "wrapper.yaml",
        f"""
        !include {extras}
        """,
    )
    out = discover_cli_directives([wrapper], seed_context={})
    names = {d.name for d in out}
    assert "level" in names, f"flags not propagated through top-level include; got {names}"
