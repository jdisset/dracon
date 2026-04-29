# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""Unit tests for the NodeRewriter helper."""

from dracon.composer import CompositionResult
from dracon.nodes import DraconMappingNode, DraconScalarNode, DraconSequenceNode
from dracon.rewriter import (
    MutationKind,
    NodeRewriter,
    RewriteHandler,
    RewriteResult,
)


def _scalar(v, tag='tag:yaml.org,2002:str'):
    return DraconScalarNode(tag=tag, value=v)


def _mapping(pairs):
    items = []
    for k, v in pairs:
        kn = _scalar(k) if isinstance(k, str) else k
        vn = _scalar(v) if not hasattr(v, 'tag') else v
        items.append((kn, vn))
    return DraconMappingNode(tag='tag:yaml.org,2002:map', value=items)


def test_rewriter_runs_until_quiescent():
    # mark every scalar with tag '!up' to value '__seen__'; rewriter loops until none left
    root = _mapping([(_scalar('a'), _scalar('1', tag='!up')), (_scalar('b'), _scalar('2', tag='!up'))])
    comp = CompositionResult(root=root)

    def discover(node, path):
        return getattr(node, 'tag', None) == '!up'

    def apply(comp, path, node):
        node.tag = 'tag:yaml.org,2002:str'
        node.value = '__seen__'
        return RewriteResult.MUTATED

    handler = RewriteHandler(
        name='test',
        discover=discover,
        apply=apply,
        trace_label='test',
        mutation_kind=MutationKind.REPLACE,
    )
    outcome = NodeRewriter(comp, handler).run()
    assert outcome.mutated
    values = [v.value for _, v in root.value]
    assert values == ['__seen__', '__seen__']


def test_rewriter_no_match_no_iterations():
    root = _mapping([(_scalar('a'), _scalar('1'))])
    comp = CompositionResult(root=root)
    calls = []

    def discover(node, path):
        return False

    def apply(comp, path, node):
        calls.append(path)
        return RewriteResult.MUTATED

    handler = RewriteHandler(
        name='nop', discover=discover, apply=apply,
        trace_label='nop', mutation_kind=MutationKind.REPLACE,
    )
    outcome = NodeRewriter(comp, handler).run()
    assert not outcome.mutated
    assert calls == []


def test_rewriter_deferred_collected():
    # one match defers, another mutates; deferred list returned for caller to retry
    root = _mapping([
        (_scalar('a'), _scalar('1', tag='!defer')),
        (_scalar('b'), _scalar('2', tag='!do')),
    ])
    comp = CompositionResult(root=root)

    def discover(node, path):
        return getattr(node, 'tag', None) in ('!defer', '!do')

    def apply(comp, path, node):
        if node.tag == '!defer':
            return RewriteResult.DEFERRED
        node.tag = 'tag:yaml.org,2002:str'
        return RewriteResult.MUTATED

    handler = RewriteHandler(
        name='mixed', discover=discover, apply=apply,
        trace_label='mixed', mutation_kind=MutationKind.REPLACE,
    )
    outcome = NodeRewriter(comp, handler).run()
    assert outcome.mutated
    assert len(outcome.deferred) == 1
    deferred_path, deferred_node = outcome.deferred[0]
    assert deferred_node.tag == '!defer'


def test_rewriter_longest_first_default():
    # nested structure: outer and inner both match. longest path (inner) hits first.
    inner = _mapping([(_scalar('x'), _scalar('1', tag='!hit'))])
    outer = _mapping([(_scalar('a'), _scalar('top', tag='!hit')), (_scalar('nested'), inner)])
    comp = CompositionResult(root=outer)

    visited = []

    def discover(node, path):
        return getattr(node, 'tag', None) == '!hit'

    def apply(comp, path, node):
        visited.append(str(path))
        node.tag = 'tag:yaml.org,2002:str'
        return RewriteResult.MUTATED

    handler = RewriteHandler(
        name='depth', discover=discover, apply=apply,
        trace_label='depth', mutation_kind=MutationKind.REPLACE,
    )
    NodeRewriter(comp, handler).run()
    # inner path is longer, processed first
    assert len(visited) == 2
    assert len(visited[0]) > len(visited[1])


def test_rewriter_skip_under():
    # paths under the skip subtree are ignored
    inner = _mapping([(_scalar('x'), _scalar('1', tag='!hit'))])
    outer = _mapping([(_scalar('a'), _scalar('top', tag='!hit')), (_scalar('nested'), inner)])
    comp = CompositionResult(root=outer)

    def discover(node, path):
        return getattr(node, 'tag', None) == '!hit'

    def skip_under(comp):
        # skip the 'nested' subtree
        from dracon.keypath import KeyPath
        return [KeyPath('/nested')]

    matches = []

    def apply(comp, path, node):
        matches.append(str(path))
        node.tag = 'tag:yaml.org,2002:str'
        return RewriteResult.MUTATED

    handler = RewriteHandler(
        name='skip', discover=discover, apply=apply,
        trace_label='skip', mutation_kind=MutationKind.REPLACE,
        skip_under=skip_under,
    )
    NodeRewriter(comp, handler).run()
    # only the top-level match was applied; nested.x was skipped
    assert len(matches) == 1
    # confirm the inner node still has the original tag
    inner_node = inner.value[0][1]
    assert inner_node.tag == '!hit'


def test_rewriter_no_change_does_not_loop():
    # apply returns NO_CHANGE; rewriter must not infinite-loop on the same node
    root = _mapping([(_scalar('a'), _scalar('1', tag='!touch'))])
    comp = CompositionResult(root=root)
    counter = {'n': 0}

    def discover(node, path):
        return getattr(node, 'tag', None) == '!touch'

    def apply(comp, path, node):
        counter['n'] += 1
        return RewriteResult.NO_CHANGE

    handler = RewriteHandler(
        name='nochange', discover=discover, apply=apply,
        trace_label='nochange', mutation_kind=MutationKind.REPLACE,
    )
    outcome = NodeRewriter(comp, handler, max_passes=20).run()
    assert counter['n'] == 1
    assert not outcome.mutated


def test_rewriter_max_passes_guard():
    # apply always reports MUTATED but never actually changes the tag, so the
    # same node would be picked forever. seen_ids guards against this naturally;
    # exhaust the budget by yielding fresh nodes — drive a pathological case
    # where each iteration creates a new matching node.
    root = _mapping([(_scalar('a'), _scalar('1', tag='!grow'))])
    comp = CompositionResult(root=root)

    def discover(node, path):
        return getattr(node, 'tag', None) == '!grow'

    def apply(comp, path, node):
        # add a new sibling with the same tag every time -> infinite growth
        new_key = _scalar(f'k{len(root.value)}')
        new_val = _scalar('v', tag='!grow')
        root.value.append((new_key, new_val))
        return RewriteResult.MUTATED

    handler = RewriteHandler(
        name='grow', discover=discover, apply=apply,
        trace_label='grow', mutation_kind=MutationKind.REPLACE,
    )
    import pytest
    with pytest.raises(RuntimeError, match='exceeded max_passes'):
        NodeRewriter(comp, handler, max_passes=5).run()
