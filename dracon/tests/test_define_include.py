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
