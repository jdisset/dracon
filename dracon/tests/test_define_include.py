import pytest
from dracon.loader import DraconLoader
from dracon.include import compose_from_include_str
from dracon.deferred import DeferredNode


def get_config(config_path):
    loader = DraconLoader(enable_interpolation=True)
    compres = compose_from_include_str(loader, f"pkg:{config_path}")
    config = loader.load_composition_result(compres)
    return config


def test_define_propagates_within_file():
    """Variables defined with !define are available in the same file"""
    config = get_config("dracon:tests/test_define_propagation.yaml")
    assert config["bar"] == 42


def test_define_propagates_through_merge_include():
    """Variables from included file should be available after merge include"""
    config = get_config("dracon:tests/test_define_propagation_main.yaml")
    assert config["bar"] == 42  # from included file
    assert config["test"] == 43  # FOO + 1 using FOO from included file


def test_setdefault_propagates_through_merge_include():
    config = get_config("dracon:tests/test_setdefault_propagation_main.yaml")
    assert config["greeting"] == "hello"
    assert config["test"] == 43


def test_setdefault_propagates_to_deferred_reroot():
    config = get_config("dracon:tests/test_setdefault_deferred_main.yaml")
    assert isinstance(config["result"], DeferredNode)
    constructed = config["result"].construct()
    assert constructed["value"] == 42


# vocabulary tags (!fn templates pulled in via `<<(<): !include vocab.yaml`)
# must be resolvable from inside !define bodies too, not only at direct-use
# sites. this exercises the class of bugs where instruction processing resolves
# tag-dependent values eagerly, before merges have injected the vocabulary.


def test_vocab_greet_direct_use():
    config = get_config("dracon:tests/test_vocab_define_propagation_direct.yaml")
    assert config["result"] == "Hello, world!"


def test_vocab_greet_inside_define_body():
    """`!define g: !greet ...` where !greet comes from a merge-included vocab"""
    config = get_config("dracon:tests/test_vocab_define_propagation_via_define.yaml")
    assert config["result"] == "Hello, world!"


def test_vocab_greet_inside_set_default_body():
    """SetDefault extends Define — same deferral must apply to vocab tags."""
    config = get_config("dracon:tests/test_vocab_define_propagation_setdefault.yaml")
    assert config["result"] == "Hello, world!"


def test_vocab_greet_nested_define_chain():
    """Two !defines whose bodies both reference the same merge-included vocab tag,
    where the second also interpolates the first's result."""
    config = get_config("dracon:tests/test_vocab_define_propagation_nested.yaml")
    assert config["result"]["a"] == "Hello, alice!"
    assert config["result"]["b"] == "Hello, alice!"
