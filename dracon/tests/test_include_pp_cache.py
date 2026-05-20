# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset
"""Tests for the post-process cache reuse path on `!include`d files.

These exercise the optimization in `loader._reuse_post_processed` where a
cached, fully post-processed composition of an included file is reused
across loads. The hazard is that `!define`/`!set_default` inside an
included file is a *subtree-scoped* injection -- so the cache must not
replay accumulated `defined_vars` globally on reuse, because that
pollutes every node with whichever child happened to be processed last.
"""
import textwrap
from pathlib import Path

import pytest

from dracon import DraconLoader, resolve_all_lazy
from dracon import loader as _loader_mod


@pytest.fixture(autouse=True)
def _reset_caches():
    """Wipe loader-module caches between tests so two tests with identical
    parent-file content but different included-file content can't collide
    on the cache key, and so cached composed trees don't leak mutated
    state into later tests in the file."""
    _loader_mod._post_process_cache.clear()
    _loader_mod._cached_compose_config_from_str.cache_clear()
    yield
    _loader_mod._post_process_cache.clear()
    _loader_mod._cached_compose_config_from_str.cache_clear()


def _write(d: Path, name: str, content: str) -> Path:
    p = d / name
    p.write_text(textwrap.dedent(content).lstrip())
    return p


def _load(parent: Path):
    loader = DraconLoader()
    return resolve_all_lazy(loader.load([f"file:{parent.as_posix()}"]), permissive=False)


def test_cached_include_local_define_repeats_correctly(tmp_path: Path):
    """Two siblings each !define the same name with different values.
    The cache must not collapse them to a single global value on reuse.
    """
    _write(tmp_path, "a.yaml", """
        !define x:
          - foo
          - bar
        states: ${x}
    """)
    _write(tmp_path, "b.yaml", """
        !define x:
          - baz
        states: ${x}
    """)
    parent = _write(tmp_path, "parent.yaml", """
        items:
          - !include file:$DIR/a.yaml
          - !include file:$DIR/b.yaml
    """)

    first = _load(parent)
    assert list(first["items"][0]["states"]) == ["foo", "bar"]
    assert list(first["items"][1]["states"]) == ["baz"]

    # second load (cache hit) must produce the same result
    second = _load(parent)
    assert list(second["items"][0]["states"]) == ["foo", "bar"]
    assert list(second["items"][1]["states"]) == ["baz"]

    # third load too -- once the cache snapshot is wrong it stays wrong
    third = _load(parent)
    assert list(third["items"][0]["states"]) == ["foo", "bar"]
    assert list(third["items"][1]["states"]) == ["baz"]


def test_cached_include_set_default_repeats_correctly(tmp_path: Path):
    """Same as above but with !set_default (soft) instead of !define."""
    _write(tmp_path, "a.yaml", """
        !set_default x: alpha
        states: ${x}
    """)
    _write(tmp_path, "b.yaml", """
        !set_default x: beta
        states: ${x}
    """)
    parent = _write(tmp_path, "parent.yaml", """
        items:
          - !include file:$DIR/a.yaml
          - !include file:$DIR/b.yaml
    """)

    first = _load(parent)
    assert first["items"][0]["states"] == "alpha"
    assert first["items"][1]["states"] == "beta"

    second = _load(parent)
    assert second["items"][0]["states"] == "alpha"
    assert second["items"][1]["states"] == "beta"


def test_cached_include_same_file_twice_independent(tmp_path: Path):
    """Including the same file twice -- each instance must keep its own
    local scope; the cache key collision must not cross-contaminate."""
    _write(tmp_path, "child.yaml", """
        !define x: foo
        states: ${x}
    """)
    parent = _write(tmp_path, "parent.yaml", """
        items:
          - !include file:$DIR/child.yaml
          - !include file:$DIR/child.yaml
    """)

    first = _load(parent)
    assert first["items"][0]["states"] == "foo"
    assert first["items"][1]["states"] == "foo"

    second = _load(parent)
    assert second["items"][0]["states"] == "foo"
    assert second["items"][1]["states"] == "foo"


def test_cached_include_outer_caller_context_overrides(tmp_path: Path):
    """When the included file does NOT define the name itself, the
    caller's loader.context should still propagate into the include on
    a cache reuse. (Regression guard: ensuring we don't over-preserve.)"""
    _write(tmp_path, "child.yaml", """
        states: ${y}
    """)
    parent = _write(tmp_path, "parent.yaml", """
        item: !include file:$DIR/child.yaml
    """)

    loader1 = DraconLoader(context={"y": "first"})
    r1 = resolve_all_lazy(loader1.load([f"file:{parent.as_posix()}"]), permissive=False)
    assert r1["item"]["states"] == "first"

    loader2 = DraconLoader(context={"y": "second"})
    r2 = resolve_all_lazy(loader2.load([f"file:{parent.as_posix()}"]), permissive=False)
    assert r2["item"]["states"] == "second"
