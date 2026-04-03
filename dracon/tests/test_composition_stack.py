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


# -- 18. compose() uses stack internally (migration equivalence) --

class TestComposeUsesStack:
    """Verify compose() delegates to CompositionStack and produces identical results."""

    def test_compose_three_files(self, tmp_path):
        """3-layer merge via compose() matches expected values."""
        (tmp_path / "a.yaml").write_text("a: 1\nb:\n  x: 10\nl: [1, 2]")
        (tmp_path / "b.yaml").write_text("a: 2\nb:\n  y: 20\nl: [3, 4]")
        (tmp_path / "c.yaml").write_text("l: [5, 6]\nb:\n  x: 100\n  z: 30")
        loader = DraconLoader(trace=True)
        result = loader.load(
            [str(tmp_path / "a.yaml"), str(tmp_path / "b.yaml"), str(tmp_path / "c.yaml")],
        )
        assert dict(result) == {
            "a": 2,
            "b": {"x": 100, "y": 20, "z": 30},
            "l": [5, 6],
        }

    def test_compose_single_file(self, loader, base_path):
        """Single-file compose still works after migration."""
        result = loader.compose(base_path)
        d = _node_to_dict(result.root)
        assert d["name"] == "base"
        assert d["items"] == [1, 2]

    def test_compose_pathlib(self, tmp_path):
        """Path objects are handled correctly."""
        (tmp_path / "p.yaml").write_text("key: val")
        loader = DraconLoader(trace=True)
        result = loader.compose(tmp_path / "p.yaml")
        assert _node_to_dict(result.root)["key"] == "val"

    def test_compose_empty_raises(self, loader):
        with pytest.raises(ValueError, match="No configuration"):
            loader.compose([])

    def test_compose_resets_context(self, loader, base_path):
        """compose() calls reset_context() so each call starts clean."""
        loader.update_context({"custom_key": 42})
        loader.compose(base_path)
        # after compose, default context should be restored (reset_context was called)
        assert "getenv" in loader.context  # default context present

    def test_compose_with_define(self, tmp_path):
        """!define in layers works through compose()."""
        (tmp_path / "d.yaml").write_text("!define x: 42\nval: ${x}")
        loader = DraconLoader(trace=True)
        result = loader.load(str(tmp_path / "d.yaml"))
        assert result["val"] == 42

    def test_compose_stores_last_composition(self, loader, base_path, override_path):
        """compose() sets _last_composition."""
        result = loader.compose([base_path, override_path])
        assert loader._last_composition is result

    def test_compose_custom_merge_key(self, tmp_path):
        """Custom merge key propagates through stack layers."""
        (tmp_path / "x.yaml").write_text("items: [1, 2]")
        (tmp_path / "y.yaml").write_text("items: [3, 4]")
        loader = DraconLoader(trace=True)
        # list append
        result = loader.load(
            [str(tmp_path / "x.yaml"), str(tmp_path / "y.yaml")],
            merge_key="<<{<+}[+>]",
        )
        assert list(result["items"]) == [1, 2, 3, 4]

    def test_compose_non_mapping_base(self, tmp_path):
        """List base + dict override replaces correctly."""
        (tmp_path / "lst.yaml").write_text("- item1\n- item2")
        (tmp_path / "dct.yaml").write_text("a: 1")
        loader = DraconLoader(trace=True)
        result = loader.load([str(tmp_path / "lst.yaml"), str(tmp_path / "dct.yaml")])
        assert dict(result) == {"a": 1}


# -- EXPORTS scope tests --

class TestExportsScope:
    """EXPORTS scope: later layers see !define/!set_default from earlier layers."""

    def test_basic_exports(self, loader):
        """Layer 2 with EXPORTS sees layer 1's !define."""
        stack = CompositionStack(loader, [
            LayerSpec(source=str(CONFIGS / "exports_base.yaml")),
            LayerSpec(source=str(CONFIGS / "exports_conditional.yaml"), scope=LayerScope.EXPORTS),
        ])
        result = stack.construct()
        assert result["augmentation"] == "heavy"
        assert result["lr_used"] == 0.001

    def test_soft_hard_priority(self, loader):
        """!define overrides earlier !set_default, !set_default doesn't override earlier !define."""
        stack = CompositionStack(loader, [
            LayerSpec(source=str(CONFIGS / "exports_base.yaml")),
            LayerSpec(source=str(CONFIGS / "exports_override_lr.yaml"), scope=LayerScope.EXPORTS),
        ])
        result = stack.construct()
        # layer 1: !define model: resnet (hard), !set_default lr: 0.001 (soft)
        # layer 2: !define lr: 0.01 (hard overrides soft), !set_default model: vgg (soft, doesn't override hard)
        assert result["name"] == "base"
        assert result["training"] is True
        # check the accumulated vars on the composed result
        comp = stack.composed
        assert comp.defined_vars["model"] == "resnet"  # hard from layer 1 survives
        assert comp.defined_vars["lr"] == 0.01  # hard from layer 2 overrides soft from layer 1

    def test_isolated_no_exports(self, loader):
        """Layer with ISOLATED scope cannot see earlier layer's !define."""
        stack = CompositionStack(loader, [
            LayerSpec(source=str(CONFIGS / "exports_base.yaml")),
            LayerSpec(source=str(CONFIGS / "exports_conditional.yaml"), scope=LayerScope.ISOLATED),
        ])
        # model is undefined in layer 2 -> !if should fail
        with pytest.raises(Exception):
            stack.construct()

    def test_dynamic_include_on_export(self, tmp_path, loader):
        """!include file:${dataset}.yaml in layer 2, dataset defined in layer 1."""
        (tmp_path / "train.yaml").write_text("split: train\nsamples: 1000")
        define_layer = tmp_path / "define_dataset.yaml"
        define_layer.write_text("!define dataset_file: " + str(tmp_path / "train.yaml"))
        include_layer = tmp_path / "use_dataset.yaml"
        include_layer.write_text("data: !include file:${dataset_file}")
        stack = CompositionStack(loader, [
            LayerSpec(source=str(define_layer)),
            LayerSpec(source=str(include_layer), scope=LayerScope.EXPORTS),
        ])
        result = stack.construct()
        assert result["data"]["split"] == "train"
        assert result["data"]["samples"] == 1000

    def test_export_override_by_layer_context(self, loader):
        """Layer context overrides exported vars."""
        stack = CompositionStack(loader, [
            LayerSpec(source=str(CONFIGS / "exports_base.yaml")),
            LayerSpec(
                source=str(CONFIGS / "exports_conditional.yaml"),
                scope=LayerScope.EXPORTS,
                context={"model": "vgg"},
            ),
        ])
        result = stack.construct()
        # layer context model=vgg overrides exported model=resnet
        assert result["augmentation"] == "light"

    def test_mixed_scopes(self, loader, tmp_path):
        """[ISOLATED, EXPORTS, ISOLATED, EXPORTS] -- each EXPORTS sees accumulated state."""
        (tmp_path / "l1.yaml").write_text("!define a: 1\nfrom_l1: yes")
        (tmp_path / "l2.yaml").write_text("a_val: ${a}\nfrom_l2: yes")
        (tmp_path / "l3.yaml").write_text("from_l3: yes")
        (tmp_path / "l4.yaml").write_text("a_val_again: ${a}\nfrom_l4: yes")
        stack = CompositionStack(loader, [
            LayerSpec(source=str(tmp_path / "l1.yaml")),                         # ISOLATED
            LayerSpec(source=str(tmp_path / "l2.yaml"), scope=LayerScope.EXPORTS), # sees a=1
            LayerSpec(source=str(tmp_path / "l3.yaml")),                         # ISOLATED
            LayerSpec(source=str(tmp_path / "l4.yaml"), scope=LayerScope.EXPORTS), # sees a=1
        ])
        result = stack.construct()
        assert result["a_val"] == 1
        assert result["a_val_again"] == 1
        assert result["from_l3"] == "yes"

    def test_push_with_exports(self, loader):
        """Push an EXPORTS layer at runtime, verify it sees accumulated state."""
        stack = CompositionStack(loader)
        stack.push(str(CONFIGS / "exports_base.yaml"))
        _ = stack.composed  # cache layer 0
        stack.push(LayerSpec(
            source=str(CONFIGS / "exports_conditional.yaml"),
            scope=LayerScope.EXPORTS,
        ))
        result = stack.construct()
        assert result["augmentation"] == "heavy"
        assert result["lr_used"] == 0.001


# -- helpers --

def _node_to_dict(node):
    return dict(DraconLoader().load_node(node))
