# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset

"""Portable (cross-process) deferred nodes: a deferred subtree composed under a
loader with live scope still pickles, ships, and constructs elsewhere — its
plain-data scope intact, builtins regenerated, live values re-supplied at
construct."""

import os
import pickle
import multiprocessing

import pytest

import dracon
from dracon import DraconLoader, is_user_symbol, is_portable, portable_scope
from dracon.utils import deepcopy
from dracon.keypath import ROOTPATH


def make_closure():
    seed = 7
    return lambda v: v + seed


def _node(ctx=None, recipe=None, **loader_kw):
    recipe = recipe or (
        "job: !deferred\n"
        "  !require run_id: 'runtime id'\n"
        "  !define lr: 0.01\n"
        "  lr: ${lr}\n"
        "  path: /runs/${run_id}\n"
    )
    loader = DraconLoader(enable_interpolation=True, context=ctx or {}, **loader_kw)
    return loader.loads(recipe)["job"]


# ── the primitive ────────────────────────────────────────────────────────────

def test_is_portable_partition():
    assert is_portable(0.01) and is_portable("x") and is_portable(DraconLoader)
    assert is_portable(os.getcwd)              # importable function
    assert not is_portable(lambda v: v)        # lambda
    assert not is_portable(make_closure())     # closure over <locals>


def test_portable_scope_drops_builtins_and_live():
    scope = {'lr': 0.01, 'now': lambda: 0, 'live': make_closure(),
             '__DRACON_NODES': {'k': 1}, 'getenv': os.getenv}
    out = portable_scope(scope)
    assert out == {'lr': 0.01, '__DRACON_NODES': {'k': 1}}  # builtins + live gone, data kept


def test_is_user_symbol_unchanged():
    assert is_user_symbol('lr') and not is_user_symbol('now') and not is_user_symbol('__scope__')


# ── pickling with live loader scope (the core gap) ───────────────────────────

def test_live_object_in_loader_context_pickles():
    node = _node({'live': make_closure(), 'plain': lambda v: v})  # both live
    blob = pickle.dumps(node)                  # previously raised PicklingError
    assert dict(pickle.loads(blob).construct(context={'run_id': 'x'})) == {'lr': 0.01, 'path': '/runs/x'}


def test_portable_roundtrip_invariant():
    node = _node({'live': make_closure()})
    here = dict(node.copy().construct(context={'run_id': 'x'}))
    there = dict(pickle.loads(pickle.dumps(node)).construct(context={'run_id': 'x'}))
    assert here == there == {'lr': 0.01, 'path': '/runs/x'}


def test_builtins_regenerated_far_side():
    node = _node(recipe=(
        "job: !deferred\n"
        "  year: ${now('%Y')}\n"
        "  home: ${getenv('HOME', 'none')}\n"
    ))
    out = pickle.loads(pickle.dumps(node)).construct()
    assert len(out['year']) == 4 and out['home']  # fresh builtins resolved


def test_dropped_live_value_resupplied():
    # helper is live in the launcher; it's dropped on pickle and re-supplied far-side
    node = _node({'helper': make_closure()}, recipe=(
        "job: !deferred\n"
        "  out: ${helper(35)}\n"
    ))
    blob = pickle.dumps(node)
    assert pickle.loads(blob).construct(context={'helper': make_closure()})['out'] == 42
    with pytest.raises(Exception):
        pickle.loads(blob).construct()['out']   # not supplied -> loud failure on access


def test_deepcopy_keeps_live_scope():
    node = _node({'live': make_closure()})
    # deepcopy/copy must NOT slim (in-process keeps live refs); only pickle slims
    assert 'live' in deepcopy(node).context or 'live' in node.copy().context


# ── detach: self-containment + blob size for fan-out ─────────────────────────

def test_detach_rejects_outer_ref():
    loader = DraconLoader(enable_interpolation=True, deferred_paths=['/job'])
    node = loader.loads("outer:\n  x: 5\njob:\n  v: ${@/outer.x}\n")["job"]
    with pytest.raises(dracon.DraconError):
        node.detach()


def test_detach_reroots_and_constructs_standalone():
    loader = DraconLoader(enable_interpolation=True)
    cfg = loader.loads(
        "jobs:\n  !each(i) ${range(4)}:\n    - !deferred\n      idx: ${i}\n"
    )
    det = cfg["jobs"][2].detach()
    assert det.path == ROOTPATH                                     # rerooted for the receiver
    assert dict(pickle.loads(pickle.dumps(det)).construct()) == {'idx': 2}


# ── sandbox: dynamic import must not silently re-enable across a roundtrip ────

def _roundtrip_source_names(**loader_kw):
    ctx = DraconLoader(enable_interpolation=True, **loader_kw).context
    return [s.name for s in pickle.loads(pickle.dumps(ctx)).sources()]


def test_sandbox_sources_fail_closed():
    # a sandboxed table must not silently regain ad-hoc imports across a roundtrip
    assert 'dynamic_import' not in _roundtrip_source_names(symbol_sources=[])


def test_default_loader_keeps_dynamic_import_across_roundtrip():
    assert 'dynamic_import' in _roundtrip_source_names()


# ── subprocess fan-out (the driving use case) ────────────────────────────────

def _construct_in_worker(arg):
    blob, ctx = arg
    obj = pickle.loads(blob).construct(context=ctx)
    return dict(obj), os.getpid()


def test_subprocess_construct():
    loader = DraconLoader(enable_interpolation=True, context={'live': make_closure()})
    cfg = loader.loads(
        "jobs:\n"
        "  !each(i) ${range(3)}:\n"
        "    - !deferred\n"
        "      idx: ${i}\n"
        "      path: /runs/${run_id}/${i}\n"
    )
    work = [(pickle.dumps(cfg["jobs"][i].detach()), {'run_id': 'exp'}) for i in range(3)]
    with multiprocessing.Pool(processes=2) as pool:
        results = pool.map(_construct_in_worker, work)
    payloads = [r[0] for r in results]
    assert payloads == [{'idx': i, 'path': f'/runs/exp/{i}'} for i in range(3)]
    assert all(pid != os.getpid() for _, pid in results)  # built in workers, not here
