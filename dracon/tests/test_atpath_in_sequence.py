# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset
"""`${@/abs.path}` inside a block-sequence of scalars must resolve.

The leading `/` resets the keypath to root, so the lazy's PARENT_PATH
should be irrelevant -- it always lands on the constructed config root.
Used to fail because `recursive_update_lazy_container` iterated Dracon
sequences via `__iter__`, which resolved each item through `_handle_lazy`
BEFORE the lazy's root_obj/current_path could be updated to the outer
container. Lazies inside the inner stage were left rooted at that stage.
"""
import pytest
from dracon import loads, resolve_all_lazy


def test_atpath_inside_block_sequence_of_scalars():
    cfg = loads("""
        stages:
          - id: load
          - id: clean
            inputs:
              - ${@/stages.0.id}
    """)
    resolve_all_lazy(cfg)
    assert list(cfg["stages"][1]["inputs"]) == ["load"]


def test_atpath_as_scalar_field_still_works():
    cfg = loads("""
        stages:
          - id: load
          - id: clean
            upstream: ${@/stages.0.id}
    """)
    resolve_all_lazy(cfg)
    assert cfg["stages"][1]["upstream"] == "load"


def test_atpath_deep_in_block_sequence_of_mappings():
    cfg = loads("""
        items:
          - name: a
            value: 1
          - name: b
            deps:
              - upstream: ${@/items.0.name}
                weight: ${@/items.0.value}
    """)
    resolve_all_lazy(cfg)
    dep = cfg["items"][1]["deps"][0]
    assert dep["upstream"] == "a"
    assert dep["weight"] == 1


def test_atpath_in_double_nested_sequence():
    cfg = loads("""
        grid:
          - - ${@/grid.0.1}
            - actual
    """)
    resolve_all_lazy(cfg)
    assert cfg["grid"][0][0] == "actual"
