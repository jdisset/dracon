import pytest
from pathlib import Path
from dracon import DraconLoader, CompositionResult
from dracon.stack import CompositionStack, LayerSpec, LayerScope
from dracon.nodes import DraconMappingNode, DraconScalarNode

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


# -- 1. basic fold matches loader.compose --

def test_basic_fold_matches_compose(loader, base_path, override_path):
    expected = loader.compose([base_path, override_path])
    stack = CompositionStack(loader, [
        LayerSpec(source=base_path),
        LayerSpec(source=override_path),
    ])
    result = stack.composed
    assert _node_to_dict(result.root) == _node_to_dict(expected.root)


# -- 2. push extends --

def test_push_extends(loader, base_path, override_path, patch_path):
    stack = CompositionStack(loader)
    stack.push(base_path)
    stack.push(override_path)
    two_layer = _node_to_dict(stack.composed.root)
    stack.push(patch_path)
    three_layer = _node_to_dict(stack.composed.root)
    assert "extra" in three_layer
    assert "extra" not in two_layer


# -- 3. pop removes last --

def test_pop_removes_last(loader, base_path, override_path, patch_path):
    stack = CompositionStack(loader)
    stack.push(base_path)
    stack.push(override_path)
    two_layer = _node_to_dict(stack.composed.root)
    stack.push(patch_path)
    stack.pop()
    assert _node_to_dict(stack.composed.root) == two_layer


# -- 4. pop mid-stack --

def test_pop_mid_stack(loader, base_path, override_path, patch_path):
    stack = CompositionStack(loader)
    stack.push(base_path)
    stack.push(override_path)
    stack.push(patch_path)
    stack.pop(1)  # remove override
    result = _node_to_dict(stack.composed.root)
    # base merged with patch: name stays "base", extra appears
    assert result["name"] == "base"
    assert "extra" in result


# -- 5. replace --

def test_replace(loader, base_path, override_path, patch_path):
    stack = CompositionStack(loader)
    stack.push(base_path)
    stack.push(override_path)
    assert _node_to_dict(stack.composed.root)["name"] == "override"
    stack.replace(1, patch_path)
    result = _node_to_dict(stack.composed.root)
    # patch doesn't set name, so base's name survives
    assert result["name"] == "base"
    assert "extra" in result


# -- 6. fork diverges --

def test_fork_diverges(loader, base_path, override_path, patch_path):
    stack = CompositionStack(loader)
    stack.push(base_path)
    stack.push(override_path)
    original_result = _node_to_dict(stack.composed.root)

    branch = stack.fork()
    branch.push(patch_path)
    branch_result = _node_to_dict(branch.composed.root)
    assert "extra" in branch_result
    # original unchanged
    assert _node_to_dict(stack.composed.root) == original_result


# -- 7. prefix cache grows incrementally --

def test_prefix_cache(loader, base_path, override_path, patch_path):
    stack = CompositionStack(loader)
    stack.push(base_path)
    _ = stack.composed
    assert len(stack._cache) == 1

    stack.push(override_path)
    _ = stack.composed
    assert len(stack._cache) == 2

    stack.push(patch_path)
    _ = stack.composed
    assert len(stack._cache) == 3

    # pop invalidates from that index
    stack.pop()
    assert len(stack._cache) == 2


# -- 8. pre-composed layer --

def test_precomposed_layer(loader, base_path, override_path):
    precomp = loader.compose(override_path)
    stack = CompositionStack(loader)
    stack.push(base_path)
    stack.push(LayerSpec(source=precomp))
    result = _node_to_dict(stack.composed.root)
    assert result["name"] == "override"


# -- 9. node layer --

def test_node_layer(loader, base_path):
    key = DraconScalarNode(tag="tag:yaml.org,2002:str", value="injected")
    val = DraconScalarNode(tag="tag:yaml.org,2002:str", value="yes")
    node = DraconMappingNode(tag="tag:yaml.org,2002:map", value=[(key, val)])
    stack = CompositionStack(loader)
    stack.push(base_path)
    stack.push(LayerSpec(source=node))
    result = _node_to_dict(stack.composed.root)
    assert result["injected"] == "yes"
    assert result["name"] == "base"


# -- 10. layer context --

def test_layer_context(loader):
    # ctx.yaml uses !set_default x: 0, so context x=99 should win
    stack = CompositionStack(loader)
    stack.push(str(CONFIGS / "ctx.yaml"), x=99)
    result = stack.construct()
    assert result["value"] == 99


# -- 11. trace labels --

def test_trace_labels(loader, base_path, override_path):
    stack = CompositionStack(loader)
    stack.push(LayerSpec(source=base_path, label="base-layer"))
    stack.push(LayerSpec(source=override_path, label="override-layer"))
    comp = stack.composed
    if comp.trace is not None:
        all_traces = comp.trace.all()
        # check that at least some trace entries reference the override label
        has_label = any(
            "override-layer" in e.detail
            for entries in all_traces.values()
            for e in entries
            if e.detail
        )
        assert has_label


# -- 12. construct matches loader.load --

def test_construct_matches_load(loader, base_path, override_path):
    loaded = loader.load([base_path, override_path], merge_key="<<{<+}[<~]")
    loader2 = DraconLoader(trace=True)
    stack = CompositionStack(loader2)
    stack.push(base_path)
    stack.push(override_path)
    constructed = stack.construct()
    # compare as dicts
    assert dict(loaded) == dict(constructed)


# -- 13. empty stack raises --

def test_empty_stack_raises(loader):
    stack = CompositionStack(loader)
    with pytest.raises(ValueError, match="empty"):
        _ = stack.composed


# -- 14. single layer --

def test_single_layer(loader, base_path):
    stack = CompositionStack(loader)
    stack.push(base_path)
    result = _node_to_dict(stack.composed.root)
    assert result["name"] == "base"
    assert result["items"] == [1, 2]


# -- 15. merge key per layer --

def test_merge_key_per_layer(loader, base_path, override_path):
    # default merge: new wins, list replace
    stack_default = CompositionStack(loader)
    stack_default.push(base_path)
    stack_default.push(override_path)
    default_result = _node_to_dict(stack_default.composed.root)
    # override.yaml sets items: [3], with default merge (new wins) this replaces [1,2]
    assert default_result["items"] == [3]

    # use list append merge key
    loader2 = DraconLoader(trace=True)
    stack_append = CompositionStack(loader2)
    stack_append.push(base_path)
    stack_append.push(LayerSpec(source=override_path, merge_key="<<{<+}[<+]"))
    append_result = _node_to_dict(stack_append.composed.root)
    # with list append + new-first, items should be [3, 1, 2]
    assert append_result["items"] == [3, 1, 2]


# -- convenience: DraconLoader.stack() --

def test_loader_stack_method():
    loader = DraconLoader(trace=True)
    stack = loader.stack(str(CONFIGS / "base.yaml"), str(CONFIGS / "override.yaml"))
    result = _node_to_dict(stack.composed.root)
    assert result["name"] == "override"


# -- public API imports --

def test_public_imports():
    from dracon import CompositionStack, LayerSpec, LayerScope
    assert CompositionStack is not None
    assert LayerSpec is not None
    assert LayerScope is not None


# -- helpers --

def _node_to_dict(node):
    return dict(DraconLoader().load_node(node))
