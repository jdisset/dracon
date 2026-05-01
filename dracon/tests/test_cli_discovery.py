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


# ── flag discovery walks into !deferred subtrees ─────────────────────────


def test_discover_walks_into_deferred_with_include(tmp_path):
    """A `!deferred` subtree that pulls in a sub-task vocabulary via
    `<<: !include` must still surface the included vocabulary's CLI
    directives. The wrapper "list of tasks" pattern depends on this."""
    panel = _write(
        tmp_path,
        "panel.yaml",
        """
        !set_default panel_title:
          default: "default-title"
          help: "title shown above each panel"
          short: -t
        !set_default panel_color:
          default: "blue"
          help: "panel color"
        result: "${panel_title} (${panel_color})"
        """,
    )
    entry = _write(
        tmp_path,
        "entry.yaml",
        f"""
        !set_default n: 3
        panels:
          - !each(i) ${{list(range(n))}}:
              - !deferred
                !define _i: ${{i}}
                <<: !include {panel}
        """,
    )
    out = discover_cli_directives([entry], seed_context={})
    names = {d.name for d in out}
    assert {"n", "panel_title", "panel_color"} <= names, (
        f"deferred-include directives not surfaced; got {names}"
    )
    by_name = {d.name: d for d in out}
    assert by_name["panel_title"].short == "-t"
    assert by_name["panel_title"].help == "title shown above each panel"
    assert by_name["panel_color"].help == "panel color"


def test_discover_walks_into_plain_deferred_block(tmp_path):
    """A `!deferred` block that declares its own flags inline (no include)
    must still surface them. This is the simpler shape of the same bug."""
    src = _write(
        tmp_path,
        "entry.yaml",
        """
        outer: 1
        task: !deferred
          !set_default port:
            default: 8080
            help: "bind port"
            short: -p
          !require run_id: "runtime id"
          path: /runs/${run_id}:${port}
        """,
    )
    out = discover_cli_directives([src], seed_context={})
    names = {d.name for d in out}
    assert {"port", "run_id"} <= names, (
        f"flags inside a !deferred block not surfaced; got {names}"
    )


def test_discover_walks_into_each_deferred_include(tmp_path):
    """`!each` over `!deferred` items, each pulling a sub-vocabulary, must
    surface the sub-vocabulary's flags exactly once (deduped)."""
    sub = _write(
        tmp_path,
        "sub.yaml",
        """
        !set_default knob:
          default: 1
          help: "a knob"
          short: -k
        v: ${knob}
        """,
    )
    entry = _write(
        tmp_path,
        "entry.yaml",
        f"""
        !set_default n: 2
        items:
          - !each(i) ${{list(range(n))}}:
              - !deferred
                <<: !include {sub}
        """,
    )
    out = discover_cli_directives([entry], seed_context={})
    names = [d.name for d in out]
    assert names.count("knob") == 1, f"knob should appear once after dedup; got {names}"
    assert "n" in names


def test_discover_robust_to_runtime_dependent_deferred(tmp_path):
    """Discovery is structural -- it harvests `!set_default` / `!require`
    declarations from a deferred subtree without composing it. So even
    when the deferred contains compose-time code that references
    runtime-only context (e.g. `!define _items: ${runtime_only}`), every
    declared flag still surfaces, and sibling deferreds are unaffected.

    This is a strict improvement over the previous compose-per-deferred
    approach, which would silently drop flags from any deferred whose
    inner subtree couldn't compose without runtime input."""
    src = _write(
        tmp_path,
        "entry.yaml",
        """
        !set_default top_level:
          default: 1
          help: "top-level always visible"
        risky: !deferred
          !define _items: ${list(range(int(missing_runtime_var)))}
          !set_default risky_flag:
            default: 0
            help: "still declared, still surfaces"
        good: !deferred
          !set_default kept_flag:
            default: 1
            help: "should still surface"
        """,
    )
    out = discover_cli_directives([src], seed_context={})
    names = {d.name for d in out}
    assert "top_level" in names
    assert "kept_flag" in names
    assert "risky_flag" in names, (
        f"declared flag inside runtime-dependent deferred should still surface; got {names}"
    )


# ── static-fallback recursion: cold --help when full compose fails ─────


def test_static_fallback_walks_into_deferred_includes(tmp_path):
    """Cold `--help` case: the entry yaml has a `!require` whose value
    drives a compose-time `!define` (so full composition fails until the
    user provides it). Discovery must still surface flags reachable
    through `!deferred` + `!include` via the static fallback."""
    panel = _write(
        tmp_path,
        "panel.yaml",
        """
        !set_default panel_title:
          default: "default-title"
          help: "title shown above each panel"
          short: -t
        !set_default panel_color:
          default: "blue"
          help: "panel color"
        result: "${panel_title} (${panel_color})"
        """,
    )
    entry = _write(
        tmp_path,
        "entry.yaml",
        f"""
        !require path: "absolute path to something that must exist"
        !define _content: !include file:${{path}}
        panels:
          - !each(i) ${{list(range(3))}}:
              - !deferred
                !define _i: ${{i}}
                <<: !include {panel}
        """,
    )
    out = discover_cli_directives([entry], seed_context={})
    names = {d.name for d in out}
    assert {"path", "panel_title", "panel_color"} <= names, (
        f"static fallback didn't reach deferred-include flags; got {names}"
    )
    by_name = {d.name: d for d in out}
    assert by_name["panel_title"].short == "-t"
    assert by_name["panel_title"].help == "title shown above each panel"


def test_static_fallback_walks_into_top_level_include(tmp_path):
    """When full compose fails, static fallback must still follow a
    top-level `<<: !include` so the included vocab's flags surface."""
    extras = _write(
        tmp_path,
        "extras.yaml",
        """
        !set_default greeting:
          default: "hello"
          help: "what to print"
          short: -g
        """,
    )
    wrapper = _write(
        tmp_path,
        "wrapper.yaml",
        f"""
        !require runtime_path: "needed at compose time"
        !define _bind: ${{open(runtime_path).read()}}
        <<: !include {extras}
        """,
    )
    out = discover_cli_directives([wrapper], seed_context={})
    names = {d.name for d in out}
    assert {"runtime_path", "greeting"} <= names, (
        f"static fallback didn't follow top-level include; got {names}"
    )


def test_static_fallback_skips_interpolated_include_paths(tmp_path):
    """Includes whose paths use `${...}` cannot be resolved statically.
    The fallback must skip them gracefully (no error, no false flags)
    while still surfacing every flag it CAN reach."""
    entry = _write(
        tmp_path,
        "entry.yaml",
        """
        !require which: "which file"
        !set_default visible:
          default: 1
          help: "always visible"
        bound: !include file:${which}
        """,
    )
    out = discover_cli_directives([entry], seed_context={})
    names = {d.name for d in out}
    assert {"which", "visible"} <= names
    # nothing else should appear
    assert names == {"which", "visible"}


def test_static_fallback_handles_include_cycle(tmp_path):
    """A cycle of !includes between two files must not loop forever."""
    a_path = tmp_path / "a.yaml"
    b_path = tmp_path / "b.yaml"
    a_path.write_text(textwrap.dedent(f"""
        !set_default flag_a:
          default: 1
          help: "from a"
        <<: !include file:{b_path.as_posix()}
        """).lstrip())
    b_path.write_text(textwrap.dedent(f"""
        !set_default flag_b:
          default: 2
          help: "from b"
        <<: !include file:{a_path.as_posix()}
        """).lstrip())
    entry = _write(
        tmp_path,
        "entry.yaml",
        f"""
        !require boom: "compose-time fail"
        !define _x: ${{boom + 1}}
        <<: !include file:{a_path.as_posix()}
        """,
    )
    out = discover_cli_directives([entry], seed_context={})
    names = {d.name for d in out}
    # cycle is broken; both flags surface, no infinite recursion
    assert {"boom", "flag_a", "flag_b"} <= names, (
        f"static fallback failed on include cycle; got {names}"
    )


def test_discover_perf_many_deferred_clones(tmp_path):
    """Locks in O(tree size) discovery cost: 100 `!each`-generated
    deferred clones, each with `<<: !include file:./panel.yaml`, must
    discover in well under a second. Earlier versions ran a full
    `post_process_composed` per deferred, which scaled to ~22s for
    real-world configs (one full compose per clone)."""
    import time

    panel = _write(
        tmp_path,
        "panel.yaml",
        """
        !set_default panel_title:
          default: "default-title"
          help: "title"
          short: -t
        !set_default panel_color:
          default: "blue"
          help: "color"
        result: "${panel_title} (${panel_color})"
        """,
    )
    entry = _write(
        tmp_path,
        "entry.yaml",
        f"""
        !set_default n: 100
        panels:
          - !each(i) ${{list(range(n))}}:
              - !deferred
                !define _i: ${{i}}
                <<: !include {panel}
        """,
    )
    t0 = time.perf_counter()
    out = discover_cli_directives([entry], seed_context={})
    elapsed = time.perf_counter() - t0
    names = {d.name for d in out}
    assert {"n", "panel_title", "panel_color"} <= names
    assert elapsed < 1.0, (
        f"discovery took {elapsed:.2f}s for 100 deferred clones; "
        f"should be sub-second (was previously O(N) full composes)"
    )


def test_discover_walks_through_force_deferred_paths(tmp_path):
    """`force_deferred_at` paths are also wrapped during normal compose.
    Discovery should walk through those too: the same SSOT propagation
    chain that surfaces directives from a non-deferred subtree must keep
    working when the user pre-declares the path as deferred."""
    panel = _write(
        tmp_path,
        "panel.yaml",
        """
        !set_default panel_title:
          default: "default-title"
          help: "title"
        result: ${panel_title}
        """,
    )
    entry = _write(
        tmp_path,
        "entry.yaml",
        f"""
        task:
          <<: !include {panel}
        """,
    )

    from dracon import DraconLoader

    def factory(**kwargs):
        kwargs.setdefault("deferred_paths", ["/task"])
        return DraconLoader(**kwargs)

    out = discover_cli_directives([entry], seed_context={}, loader_factory=factory)
    names = {d.name for d in out}
    assert "panel_title" in names, (
        f"flags inside a force-deferred subtree not surfaced; got {names}"
    )
