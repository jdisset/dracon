# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""Tests: transactional composition layers."""

from __future__ import annotations

from pathlib import Path

import pytest

from dracon import DraconLoader
from dracon.stack import (
    CompositionStack, CompositionStackSnapshot, LayerInfo, LayerSpec, LayerScope,
    StackTransaction,
)


CONFIGS = Path(__file__).parent / "configs" / "stack"


@pytest.fixture
def loader():
    return DraconLoader(trace=True)


@pytest.fixture
def base_path():
    return str(CONFIGS / "base.yaml")


@pytest.fixture
def override_path():
    return str(CONFIGS / "override.yaml")


@pytest.fixture
def patch_path():
    return str(CONFIGS / "patch.yaml")


def _node_to_dict(node):
    """Helper: turn a node tree into a plain dict for equality comparison."""
    from dracon.nodes import DraconMappingNode, DraconScalarNode
    from dracon.composer import DraconSequenceNode
    if isinstance(node, DraconMappingNode):
        return {k.value: _node_to_dict(v) for k, v in node.value}
    if isinstance(node, DraconSequenceNode):
        return [_node_to_dict(v) for v in node.value]
    return getattr(node, 'value', node)


# ── LayerSpec.metadata ─────────────────────────────────────────────────────


class TestLayerSpecMetadata:
    def test_metadata_defaults_empty(self):
        spec = LayerSpec(source="x")
        assert spec.metadata == {}

    def test_metadata_survives_push(self, loader, base_path):
        stack = CompositionStack(loader)
        stack.push(LayerSpec(source=base_path, label="base", metadata={"author": "system"}))
        assert stack.layers[0].metadata == {"author": "system"}

    def test_metadata_survives_replace(self, loader, base_path, override_path):
        stack = CompositionStack(loader)
        stack.push(LayerSpec(source=base_path))
        stack.replace(0, LayerSpec(source=override_path, label="o", metadata={"k": 1}))
        assert stack.layers[0].metadata == {"k": 1}

    def test_metadata_survives_fork(self, loader, base_path):
        stack = CompositionStack(loader)
        stack.push(LayerSpec(source=base_path, metadata={"k": "v"}))
        forked = stack.fork()
        assert forked.layers[0].metadata == {"k": "v"}

    def test_metadata_and_layers_survive_snapshot_restore(self, loader, base_path, override_path):
        stack = CompositionStack(loader)
        stack.push(LayerSpec(source=base_path, metadata={"a": 1}))
        stack.push(LayerSpec(source=override_path, metadata={"b": 2}))
        snap = stack.snapshot()
        # mutate, then restore
        stack.pop()
        stack.restore(snap)
        assert stack.layers[0].metadata == {"a": 1}
        assert stack.layers[1].metadata == {"b": 2}

    def test_context_default_is_not_shared(self):
        a = LayerSpec(source="x")
        b = LayerSpec(source="y")
        a.context["k"] = "v"
        assert "k" not in b.context

    def test_metadata_default_is_not_shared(self):
        a = LayerSpec(source="x")
        b = LayerSpec(source="y")
        a.metadata["k"] = "v"
        assert "k" not in b.metadata


# ── snapshot / restore ─────────────────────────────────────────────────────


class TestSnapshotRestore:
    def test_restore_replays_layer_list_and_cache(self, loader, base_path, override_path, patch_path):
        stack = CompositionStack(loader)
        stack.push(base_path)
        stack.push(override_path)
        _ = stack.composed  # populate cache
        cached_count = len(stack._cache)
        snap = stack.snapshot()
        # mutate
        stack.push(patch_path)
        _ = stack.composed
        assert len(stack._layers) == 3
        # restore
        stack.restore(snap)
        assert len(stack._layers) == 2
        assert len(stack._cache) == cached_count

    def test_restore_after_failed_validation_returns_pre_state(self, loader, base_path, override_path):
        stack = CompositionStack(loader)
        stack.push(base_path)
        snap = stack.snapshot()
        try:
            stack.push(override_path)
            _ = stack.composed
            raise RuntimeError("validation failed")
        except RuntimeError:
            stack.restore(snap)
        assert len(stack._layers) == 1
        # cache for layer 1 must be cleared by restore
        assert len(stack._cache) <= 1


# ── transaction ────────────────────────────────────────────────────────────


class TestTransaction:
    def test_rolls_back_when_not_committed(self, loader, base_path, override_path):
        stack = CompositionStack(loader)
        stack.push(base_path)
        with stack.transaction():
            stack.push(override_path)
            assert len(stack._layers) == 2
        assert len(stack._layers) == 1

    def test_preserves_when_committed(self, loader, base_path, override_path):
        stack = CompositionStack(loader)
        stack.push(base_path)
        with stack.transaction() as tx:
            stack.push(override_path)
            tx.commit()
        assert len(stack._layers) == 2

    def test_propagates_exceptions(self, loader, base_path, override_path):
        stack = CompositionStack(loader)
        stack.push(base_path)
        with pytest.raises(ValueError, match="boom"):
            with stack.transaction():
                stack.push(override_path)
                raise ValueError("boom")
        assert len(stack._layers) == 1

    def test_nested_inner_rollback_outer_keeps(self, loader, base_path, override_path, patch_path):
        stack = CompositionStack(loader)
        stack.push(base_path)
        with stack.transaction() as outer:
            stack.push(override_path)
            with stack.transaction():  # not committed → rolls back
                stack.push(patch_path)
                assert len(stack._layers) == 3
            assert len(stack._layers) == 2
            outer.commit()
        assert len(stack._layers) == 2

    def test_nested_outer_rollback_drops_inner_committed(self, loader, base_path, override_path, patch_path):
        stack = CompositionStack(loader)
        stack.push(base_path)
        with stack.transaction():
            stack.push(override_path)
            with stack.transaction() as inner:
                stack.push(patch_path)
                inner.commit()
            assert len(stack._layers) == 3
            # outer not committed
        assert len(stack._layers) == 1

    def test_double_enter_raises(self, loader, base_path):
        stack = CompositionStack(loader)
        stack.push(base_path)
        tx = stack.transaction()
        with tx:
            with pytest.raises(RuntimeError, match="already entered"):
                with tx:
                    pass

    def test_cache_invalidation_after_pop_post_restore(self, loader, base_path, override_path, patch_path):
        stack = CompositionStack(loader)
        stack.push(base_path)
        stack.push(override_path)
        _ = stack.composed
        snap = stack.snapshot()
        stack.push(patch_path)
        _ = stack.composed
        # restore brings us back to 2 layers, both cached
        stack.restore(snap)
        assert len(stack._layers) == 2
        assert len(stack._cache) == 2
        # popping the last layer cuts the cache from that index (cache[:1])
        stack.pop()
        assert len(stack._cache) == 1
        # next compose still rebuilds layer 1 fresh after a re-push
        stack.push(patch_path)
        result = stack.composed
        assert "extra" in _node_to_dict(result.root)


# ── layer_info / composed_at ───────────────────────────────────────────────


class TestLayerInspection:
    def test_layer_info_by_index(self, loader, base_path, override_path):
        stack = CompositionStack(loader)
        stack.push(LayerSpec(source=base_path, label="base", metadata={"author": "sys"}))
        stack.push(LayerSpec(source=override_path, label="override", metadata={"author": "agent"}))
        info = stack.layer_info(1)
        assert isinstance(info, LayerInfo)
        assert info.index == 1
        assert info.label == "override"
        assert info.metadata == {"author": "agent"}
        assert info.prefix is not None  # layer 1 has a prefix
        assert info.contribution is not None
        assert info.composed is not None

    def test_layer_info_by_label(self, loader, base_path, override_path):
        stack = CompositionStack(loader)
        stack.push(LayerSpec(source=base_path, label="base"))
        stack.push(LayerSpec(source=override_path, label="override"))
        info = stack.layer_info("base")
        assert info.index == 0
        assert info.prefix is None  # first layer has no prefix
        assert info.label == "base"

    def test_layer_info_missing_label(self, loader, base_path):
        stack = CompositionStack(loader)
        stack.push(LayerSpec(source=base_path))
        with pytest.raises(KeyError):
            stack.layer_info("nope")

    def test_composed_at_returns_cumulative_state(self, loader, base_path, override_path, patch_path):
        stack = CompositionStack(loader)
        stack.push(base_path)
        stack.push(override_path)
        stack.push(patch_path)
        first = _node_to_dict(stack.composed_at(0).root)
        second = _node_to_dict(stack.composed_at(1).root)
        third = _node_to_dict(stack.composed_at(2).root)
        assert first["name"] == "base"
        assert second["name"] == "override"
        assert "extra" in third


# ── trace label / metadata ─────────────────────────────────────────────────


class TestTraceAttribution:
    def test_trace_carries_layer_label_and_metadata(self, loader, base_path, override_path):
        stack = CompositionStack(loader)
        stack.push(LayerSpec(source=base_path, label="base", metadata={"author": "sys"}))
        stack.push(LayerSpec(source=override_path, label="override", metadata={"author": "agent"}))
        comp = stack.composed
        trace = comp.trace
        assert trace is not None
        # locate any trace for a key written by the override layer
        entries = trace.get("name")
        assert entries
        last = entries[-1]
        assert last.layer is not None
        assert last.layer.label == "override"
        assert last.layer.metadata == {"author": "agent"}
