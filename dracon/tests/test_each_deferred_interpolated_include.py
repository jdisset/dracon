# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset
"""Regression tests for `<<: !include` with interpolated/varying paths under
`!each` + `!deferred`.

Background: two bug reports filed against the biocompiler paper-jobs
pipeline claimed that the `<<: !include "file:$DIR/tasks/${task_file}"`
pattern inside `!each` + `!deferred` silently dropped the include's
content -- bare-name `task_file` values produced an empty mapping, and
subdir-path values whose included file itself used `<<: !include` +
`<<{+<}:` produced a mapping with only the override content.

The bugs were never reproducible in isolation. These tests pin down the
intended behaviour for the **whole class** of patterns the bug reports
described, so any future regression along this axis surfaces as a
concrete test failure rather than a silently blank manuscript figure.

Coverage:
  - interpolated `<<: !include "file:.../${var}"` with bare-name and
    subdir-prefixed values, all inside one `!each` iteration
  - the inner file itself wrapped in `<<: !include` + `<<{+<}:`
  - the outer file itself loaded through a `<<: !include` + `<<{+<}:`
    wrapper (production wrapper-chain shape)
  - the top-level `!each` body wrapped in `!deferred::reroot=true`
    (production per-network shape)
  - hardcoded (non-interpolated) paths produce the same output as
    interpolated paths that resolve to the same file
"""
from __future__ import annotations

from pathlib import Path
import textwrap

import pytest

from dracon.loader import DraconLoader
from dracon.deferred import DeferredNode


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _w(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip("\n"))
    return path


@pytest.fixture
def tasks_tree(tmp_path: Path) -> Path:
    """Build a task-file tree shaped like the production layout:

    base/
      tasks/
        bare_inline.yaml             -- bare-name, inline content
        sub/
          subdir_inline.yaml         -- subdir path, inline content
          subdir_nested.yaml         -- subdir path, body uses <<: !include + <<{+<}:
      tasks_canonical/
        canonical_subdir_nested.yaml -- target of the nested include above
    """
    base = tmp_path / "base"

    # bare-name task: pure inline content
    _w(base / "tasks" / "bare_inline.yaml", """
        plot_method:
          func: render_bare
          kwargs:
            name: ${atomic['name']}
            ax: ${axnum}
    """)

    # subdir + inline
    _w(base / "tasks" / "sub" / "subdir_inline.yaml", """
        plot_method:
          func: render_sub_inline
          kwargs:
            name: ${atomic['name']}
            ax: ${axnum}
    """)

    # subdir + nested <<: !include + <<{+<}: override
    _w(base / "tasks" / "sub" / "subdir_nested.yaml", """
        !define D: ${atomic['name']}

        <<: !include file:$DIR/../../tasks_canonical/canonical_subdir_nested.yaml
        <<{+<}:
          plot_method:
            kwargs:
              title: from-nested-override
    """)

    # canonical target of the nested include -- provides plot_method.func + base kwargs
    _w(base / "tasks_canonical" / "canonical_subdir_nested.yaml", """
        !set_default axnum: 0
        plot_method:
          func: render_canonical
          kwargs:
            force_dim: 2
            data: ${D}
            ax: ${axnum}
    """)

    return base


@pytest.fixture
def outer_yaml(tasks_tree: Path) -> Path:
    """Outer file with `!each` + `!deferred` + interpolated `<<: !include`.
    Mirrors `autofig_dataset_row.yaml`'s `plot_tasks:` block."""
    return _w(tasks_tree / "outer.yaml", """
        !set_default outer_knob: 1.0

        !define _atomics:
          - {name: a, task_file: bare_inline}
          - {name: b, task_file: sub/subdir_inline}
          - {name: c, task_file: sub/subdir_nested}

        plot_tasks:
          - !each(_atomic) ${_atomics}:
              - !deferred
                !define atomic: ${_atomic}
                !define axnum: 0
                <<: !include "file:$DIR/tasks/${_atomic['task_file']}"
    """)


@pytest.fixture
def outer_yaml_helper_atomics(tasks_tree: Path) -> Path:
    """Same as `outer_yaml` but `_atomics` comes from a Python helper.
    Mirrors `!compose_atomics` in production."""
    return _w(tasks_tree / "outer_helper.yaml", """
        !define _atomics: ${make_atomics()}

        plot_tasks:
          - !each(_atomic) ${_atomics}:
              - !deferred
                !define atomic: ${_atomic}
                !define axnum: 0
                <<: !include "file:$DIR/tasks/${_atomic['task_file']}"
    """)


@pytest.fixture
def wrapper_yaml(tasks_tree: Path, outer_yaml: Path) -> Path:
    """A wrapper file that itself uses `<<: !include outer.yaml` + `<<{+<}:`.
    Mirrors `per_network_rows.yaml` -> `autofig_dataset_row.yaml`."""
    return _w(tasks_tree / "wrapper.yaml", """
        <<: !include file:$DIR/outer.yaml
        <<{+<}:
          wrapper_added: from-wrapper
    """)


@pytest.fixture
def top_deferred_reroot_yaml(tasks_tree: Path, wrapper_yaml: Path) -> Path:
    """Top-level `!each` per network, each wrapping the wrapper in a
    `!deferred::reroot=true`. Mirrors `dataset_prediction.yaml`."""
    return _w(tasks_tree / "top.yaml", """
        !define networks: ${[0, 1]}

        figures:
          !each(_n) ${networks}:
            - !deferred::reroot=true
              !define _net: ${_n}
              <<: !include file:$DIR/wrapper.yaml
    """)


def _construct_plot_tasks(loader_cfg) -> list[dict]:
    """Construct every plot_task entry to a plain dict, supporting both
    flat plot_tasks lists and the !each-wrapped list-of-lists shape."""
    out = []
    raw = loader_cfg["plot_tasks"]
    flat = []
    for item in raw:
        if isinstance(item, (list, tuple)) or (hasattr(item, "__iter__") and not isinstance(item, DeferredNode) and not isinstance(item, str)):
            try:
                flat.extend(list(item))
            except TypeError:
                flat.append(item)
        else:
            flat.append(item)
    for item in flat:
        if isinstance(item, DeferredNode):
            out.append(dict(item.construct()))
        else:
            out.append(dict(item) if hasattr(item, "keys") else item)
    return out


# ---------------------------------------------------------------------------
# the cases the bug reports called out
# ---------------------------------------------------------------------------

def test_each_deferred_interpolated_include_bare_name(outer_yaml: Path):
    """Bug 2: bare-name `task_file` resolved via `<<: !include "file:.../${var}"`
    must produce a non-empty mapping (the file's full top-level content)."""
    cfg = DraconLoader().load(str(outer_yaml))
    tasks = _construct_plot_tasks(cfg)
    bare = tasks[0]
    assert "plot_method" in bare, f"bare-name include silently produced empty: {bare}"
    assert dict(bare["plot_method"])["func"] == "render_bare"


def test_each_deferred_interpolated_include_subdir_inline(outer_yaml: Path):
    """Subdir-prefixed `task_file` whose body is fully inline."""
    cfg = DraconLoader().load(str(outer_yaml))
    tasks = _construct_plot_tasks(cfg)
    sub = tasks[1]
    assert dict(sub["plot_method"])["func"] == "render_sub_inline"


def test_each_deferred_interpolated_include_subdir_nested(outer_yaml: Path):
    """Bug 1: subdir-prefixed `task_file` whose body itself uses
    `<<: !include` + `<<{+<}:`. Both the inner-include's content AND
    the override must survive into the merged result."""
    cfg = DraconLoader().load(str(outer_yaml))
    tasks = _construct_plot_tasks(cfg)
    nested = tasks[2]
    pm = dict(nested["plot_method"])
    # the inner <<: !include carried `func: render_canonical` -- this was
    # the leaf that vanished in bug 1
    assert pm.get("func") == "render_canonical", (
        f"inner <<: !include's content vanished from nested merge: {pm}"
    )
    kwargs = dict(pm["kwargs"])
    # the inner kwargs (force_dim, data) must survive the outer override
    assert kwargs.get("force_dim") == 2
    # the outer <<{+<}: title override must survive too
    assert kwargs.get("title") == "from-nested-override"


def test_each_deferred_hardcoded_path_matches_interpolated(tasks_tree: Path):
    """Bug 2 explicitly states hardcoded paths reproduce the bare-name
    failure. Pin: hardcoded `<<: !include file:.../bare_inline` produces
    the same content as the interpolated form."""
    hardcoded = _w(tasks_tree / "outer_hardcoded.yaml", """
        plot_tasks:
          - !deferred
            !define atomic: { name: a }
            !define axnum: 0
            <<: !include file:$DIR/tasks/bare_inline
    """)
    cfg = DraconLoader().load(str(hardcoded))
    tasks = _construct_plot_tasks(cfg)
    assert dict(tasks[0]["plot_method"])["func"] == "render_bare"


def test_each_deferred_include_inside_deferred_reroot_wrapper(
    top_deferred_reroot_yaml: Path,
):
    """Production wrapper chain: top `!each + !deferred::reroot=true`
    -> wrapper `<<: !include + <<{+<}:` -> outer `!each + !deferred +
    <<: !include "file:.../${task_file}"`.  Both bare-name and
    nested-include task files must construct correctly across every
    figure iteration."""
    cfg = DraconLoader().load(str(top_deferred_reroot_yaml))
    figures = list(cfg["figures"])
    assert len(figures) == 2
    for fig in figures:
        constructed = dict(fig.construct())
        assert "plot_tasks" in constructed
        tasks = []
        # walk one !each-wrapped list-of-lists or flat list
        for item in constructed["plot_tasks"]:
            if hasattr(item, "construct"):
                tasks.append(dict(item.construct()))
            elif hasattr(item, "__iter__"):
                for sub in item:
                    if hasattr(sub, "construct"):
                        tasks.append(dict(sub.construct()))
                    else:
                        tasks.append(dict(sub))
            else:
                tasks.append(dict(item))
        # all three task types must have plot_method
        funcs = [dict(t["plot_method"]).get("func") for t in tasks if "plot_method" in t]
        assert "render_bare" in funcs
        assert "render_sub_inline" in funcs
        assert "render_canonical" in funcs


# ---------------------------------------------------------------------------
# adjacent invariants -- guard the class of bugs, not just the reported point
# ---------------------------------------------------------------------------

def test_each_deferred_inline_key_plus_include_both_survive(tasks_tree: Path):
    """The bug report observed: adding an inline key to the deferred body
    survives in the output, but the include's content STILL doesn't merge.
    Lock in the correct behaviour: BOTH the inline key AND the include's
    keys are present after construction."""
    src = _w(tasks_tree / "outer_inline_plus_include.yaml", """
        plot_tasks:
          - !each(t) ${['bare_inline']}:
              - !deferred
                !define atomic: { name: a }
                !define axnum: 0
                inline_only_key: 42
                <<: !include "file:$DIR/tasks/${t}"
    """)
    cfg = DraconLoader().load(str(src))
    tasks = _construct_plot_tasks(cfg)
    assert tasks[0].get("inline_only_key") == 42
    assert "plot_method" in tasks[0]


def test_each_iterations_each_include_freshly_resolved(outer_yaml: Path):
    """Lock in per-iteration freshness: different `task_file` values in the
    same `!each` produce different included content (no cross-iteration
    cache bleed)."""
    cfg = DraconLoader().load(str(outer_yaml))
    tasks = _construct_plot_tasks(cfg)
    funcs = [dict(t["plot_method"]).get("func") for t in tasks]
    assert funcs == ["render_bare", "render_sub_inline", "render_canonical"]


def test_helper_provided_atomics_with_interpolated_include(
    outer_yaml_helper_atomics: Path,
):
    """The production `_atomics` list comes from a Python helper
    (`!compose_atomics`) rather than a YAML literal. Verify the
    interpolated `<<: !include` form still works when the iterable
    comes from a callable."""
    def make_atomics():
        return [
            {"name": "x", "task_file": "bare_inline"},
            {"name": "y", "task_file": "sub/subdir_nested"},
        ]
    cfg = DraconLoader(context={"make_atomics": make_atomics}).load(
        str(outer_yaml_helper_atomics)
    )
    tasks = _construct_plot_tasks(cfg)
    funcs = [dict(t["plot_method"]).get("func") for t in tasks]
    assert funcs == ["render_bare", "render_canonical"]


def test_inner_include_override_survives_outer_iteration(outer_yaml: Path):
    """For the nested-include task, the `<<{+<}: { plot_method: { kwargs:
    { title: ... } } }` override must apply on top of the inner-included
    kwargs (force_dim, data), preserving both."""
    cfg = DraconLoader().load(str(outer_yaml))
    tasks = _construct_plot_tasks(cfg)
    nested = tasks[2]
    kw = dict(dict(nested["plot_method"])["kwargs"])
    # outer override
    assert kw["title"] == "from-nested-override"
    # inner include's base kwargs
    assert kw["force_dim"] == 2


# ---------------------------------------------------------------------------
# include-path interpolation invariants
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("task_file", [
    "bare_inline",
    "sub/subdir_inline",
    "sub/subdir_nested",
])
def test_single_iteration_each_path_shape(tasks_tree: Path, task_file: str):
    """Each `task_file` shape, on its own (single-iteration !each), gives
    non-empty content. Catches asymmetric failures where bare paths
    silently empty but subdir paths work (or vice-versa)."""
    src = _w(
        tasks_tree / f"outer_one_{task_file.replace('/', '_')}.yaml",
        f"""
        !define _atomics:
          - {{name: n, task_file: {task_file}}}

        plot_tasks:
          - !each(_a) ${{_atomics}}:
              - !deferred
                !define atomic: ${{_a}}
                !define axnum: 0
                <<: !include "file:$DIR/tasks/${{_a['task_file']}}"
    """,
    )
    cfg = DraconLoader().load(str(src))
    tasks = _construct_plot_tasks(cfg)
    assert "plot_method" in tasks[0], (
        f"single-iteration include for task_file={task_file!r} returned "
        f"empty mapping; expected to contain plot_method"
    )
