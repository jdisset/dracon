# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset

import copy
import pickle
import pytest

from dracon.merge import MergeKey, merged, cached_merge_key
from dracon.cascade import cascade_inherit


def _strip_params(s: str):
    return s.removesuffix('_params') or None


def test_merge_key_normalize_collapses_keys_new_wins():
    op = MergeKey(raw='<<{+<}[~<]', key_normalize=_strip_params)
    existing = {'smooth_2d_params': {'a': 1, 'b': 2}}
    new = {'smooth_2d': {'b': 99, 'c': 3}}
    result = merged(existing, new, op)
    assert len(result) == 1
    key = next(iter(result))
    assert result[key] == {'a': 1, 'b': 99, 'c': 3}


def test_merge_key_normalize_collapses_keys_existing_wins():
    op = MergeKey(raw='<<{+>}[~>]', key_normalize=_strip_params)
    existing = {'smooth_2d_params': {'a': 1, 'b': 2}}
    new = {'smooth_2d': {'b': 99, 'c': 3}}
    result = merged(existing, new, op)
    assert len(result) == 1
    # existing-wins: scalar collisions keep existing, missing keys still added
    key = next(iter(result))
    assert result[key] == {'a': 1, 'b': 2, 'c': 3}


def test_normalizer_returns_none_leaves_keys_alone():
    op = MergeKey(raw='<<{+<}', key_normalize=lambda s: s if s.startswith('cfg_') else None)
    existing = {'foo': 1, 'cfg_x': 10}
    new = {'foo': 2, 'cfg_x': 20}
    result = merged(existing, new, op)
    # foo: normalizer returns None on both sides -> normal name-equality merge
    assert result['foo'] == 2  # new-wins
    assert result['cfg_x'] == 20


def test_normalizer_no_op_when_none():
    op = MergeKey(raw='<<{+<}')
    existing = {'a': 1}
    new = {'b': 2}
    assert merged(existing, new, op) == {'a': 1, 'b': 2}


def test_normalizer_does_not_touch_non_string_keys():
    op = MergeKey(raw='<<{+<}', key_normalize=lambda s: s.upper())
    existing = {1: 'one', 'a': 'A'}
    new = {1: 'ONE', 'a': 'AA'}
    result = merged(existing, new, op)
    assert result[1] == 'ONE'
    assert result['a'] == 'AA'


def test_merge_key_not_cached_when_normalize_set():
    # cache only memoizes by raw -- normalize-bearing keys must not poison it
    cached = cached_merge_key('<<{+<}')
    assert cached.key_normalize is None
    custom = MergeKey(raw='<<{+<}', key_normalize=_strip_params)
    assert custom is not cached
    # cached_merge_key still returns the cached, unhooked one
    assert cached_merge_key('<<{+<}') is cached


def test_merge_key_dump_excludes_normalize():
    op = MergeKey(raw='<<{+<}', key_normalize=_strip_params)
    assert 'key_normalize' not in op.model_dump()


def test_merge_key_copy_roundtrip():
    op = MergeKey(raw='<<{+<}', key_normalize=_strip_params)
    op2 = copy.copy(op)
    assert op2.key_normalize is _strip_params
    op3 = copy.deepcopy(op)
    assert op3.key_normalize is _strip_params


def test_cascade_inherit_python_api():
    tree = {
        'smooth_2d_params': {
            'draw_colorbar': True,
            'heatmap_params': {'contours': 0},
        },
        'smooth_3d_params': {
            'smooth_2d_params': {
                'draw_colorbar': False,
            },
        },
    }
    out = cascade_inherit(tree, key_normalize=_strip_params)
    inner = out['smooth_3d_params']['smooth_2d_params']
    assert inner['draw_colorbar'] is False  # local pin wins
    assert inner['heatmap_params'] == {'contours': 0}  # inherited from ancestor


def test_cascade_inherit_preserves_unrelated_keys():
    tree = {
        'smooth_2d_params': {'x': 1},
        'unrelated': 'leave alone',
    }
    out = cascade_inherit(tree, key_normalize=_strip_params)
    assert out['unrelated'] == 'leave alone'
    assert out['smooth_2d_params'] == {'x': 1}


def test_cascade_inherit_does_not_mutate_input():
    tree = {
        'smooth_2d_params': {'a': 1},
        'smooth_3d_params': {
            'smooth_2d_params': {'b': 2},
        },
    }
    snap = copy.deepcopy(tree)
    cascade_inherit(tree, key_normalize=_strip_params)
    assert tree == snap


def test_cascade_inherit_deep_chain():
    # ancestor at depth 0 should reach the leaf via two levels of nesting
    tree = {
        'smooth_2d_params': {
            'xlims': [0, 1],
            'smooth_3d_params': {
                'smooth_2d_params': {
                    'draw_colorbar': False,
                },
            },
        },
    }
    out = cascade_inherit(tree, key_normalize=_strip_params)
    leaf = out['smooth_2d_params']['smooth_3d_params']['smooth_2d_params']
    assert leaf['draw_colorbar'] is False
    assert leaf['xlims'] == [0, 1]


def test_cascade_inherit_local_pins_win_over_ancestor():
    tree = {
        'smooth_2d_params': {
            'a': 'outer',
            'smooth_2d_params': {
                'a': 'inner',
            },
        },
    }
    out = cascade_inherit(tree, key_normalize=_strip_params)
    assert out['smooth_2d_params']['smooth_2d_params']['a'] == 'inner'
