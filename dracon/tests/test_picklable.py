import pickle
import pytest
from ruamel.yaml import YAML
from dracon.yaml import PicklableYAML
import io
import multiprocessing
from pathlib import Path
from dracon.loader import DraconLoader
from pydantic import BaseModel
from dracon.resolvable import Resolvable
from dracon.deferred import DeferredNode
from dracon.lazy import LazyInterpolable
from dracon.keypath import ROOTPATH
import os

# Set a dummy environment variable for testing purposes
os.environ["TESTVAR1"] = "test_var_1"
os.environ["TESTVAR2"] = "test_var_2"

# Test file paths
simple_config_path = 'dracon:tests/configs/simple.yaml'

main_config_path = 'dracon:tests/configs/main.yaml'
params_config_path = 'dracon:tests/configs/params.yaml'
base_config_path = 'dracon:tests/configs/base.yaml'
interp_config_path = 'dracon:tests/configs/interpolation.yaml'
resolvable_config_path = 'dracon:tests/configs/resolvable.yaml'
override_config_path = 'dracon:tests/configs/override.yaml'


# Move CustomType to module level
class CustomType:
    """A custom type for YAML serialization testing"""

    yaml_tag = '!custom'

    def __init__(self, value):
        self.value = int(value)

    def __eq__(self, other):
        return isinstance(other, CustomType) and self.value == other.value

    @classmethod
    def from_yaml(cls, constructor, node):
        return cls(int(constructor.construct_scalar(node)))

    @classmethod
    def to_yaml(cls, representer, data):
        return representer.represent_scalar(cls.yaml_tag, str(data.value))


# Main test fixtures
@pytest.fixture
def yaml_instance():
    yaml = PicklableYAML()
    yaml.indent = 4
    yaml.width = 80
    yaml.preserve_quotes = True
    yaml.default_flow_style = False
    return yaml


@pytest.fixture
def test_data():
    return {
        'string': 'test',
        'number': 42,
        'list': [1, 2, 3],
        'nested': {'a': 1, 'b': 2},
        'multiline': """line1
        line2
        line3""",
    }


def test_basic_pickle_unpickle(yaml_instance):
    """Test basic pickling and unpickling of the YAML instance"""
    pickled = pickle.dumps(yaml_instance)
    unpickled = pickle.loads(pickled)

    assert unpickled.old_indent == yaml_instance.old_indent
    assert unpickled.width == yaml_instance.width
    assert unpickled.preserve_quotes == yaml_instance.preserve_quotes
    assert unpickled.default_flow_style == yaml_instance.default_flow_style


def test_pickle_with_dump_load(yaml_instance, test_data):
    """Test that dumping and loading work correctly after pickling"""
    output_before = io.StringIO()
    yaml_instance.dump(test_data, output_before)

    pickled = pickle.dumps(yaml_instance)
    unpickled = pickle.loads(pickled)

    output_after = io.StringIO()
    unpickled.dump(test_data, output_after)

    assert output_before.getvalue() == output_after.getvalue()


def test_pickle_with_custom_types(yaml_instance):
    """Test pickling with custom registered types"""
    # Register the custom type
    yaml_instance.register_class(CustomType)

    # Test data with custom type
    test_data = {'custom': CustomType(42)}

    # Pickle and unpickle
    pickled = pickle.dumps(yaml_instance)
    unpickled = pickle.loads(pickled)

    # Test dumping and loading with custom type
    output = io.StringIO()
    unpickled.dump(test_data, output)

    # Load and verify
    input_stream = io.StringIO(output.getvalue())
    loaded_data = unpickled.load(input_stream)
    assert isinstance(loaded_data['custom'], CustomType)
    assert loaded_data['custom'].value == 42


def test_pickle_with_different_configurations():
    """Test pickling with different YAML configurations"""
    configs = [
        {'typ': 'safe'},
        {'typ': 'rt'},
        {'typ': 'base'},
    ]

    for config in configs:
        yaml = PicklableYAML(**config)
        pickled = pickle.dumps(yaml)
        unpickled = pickle.loads(pickled)
        assert unpickled.typ == yaml.typ


def test_deep_pickle_state():
    """Test that internal state and buffers are properly pickled"""
    yaml = PicklableYAML()

    test_data = {'test': 'value'}
    output = io.StringIO()
    yaml.dump(test_data, output)

    pickled = pickle.dumps(yaml)
    unpickled = pickle.loads(pickled)

    assert not hasattr(unpickled, '_reader')
    assert not hasattr(unpickled, '_scanner')
    assert unpickled.allow_unicode == yaml.allow_unicode
    assert unpickled.encoding == yaml.encoding


def process_yaml(pickled_yaml):
    """Process YAML in a separate process"""
    yaml = pickle.loads(pickled_yaml)
    output = io.StringIO()
    yaml.dump({'test': 'value'}, output)
    return output.getvalue()


def test_pickle_cross_process():
    """Test pickling and unpickling across processes"""
    import multiprocessing

    yaml = PicklableYAML()
    pickled = pickle.dumps(yaml)

    with multiprocessing.Pool(1) as pool:
        result = pool.apply(process_yaml, (pickled,))

    assert isinstance(result, str)
    assert 'test: value' in result


#####################################################
#            PICKLING A LOADER
#####################################################


# Helper function for multiprocessing tests - must be at module level
def load_config_in_process(config_path):
    """Load a config in a separate process"""
    loader = DraconLoader()
    config = loader.load(f"pkg:{config_path}")
    return config


def pickle_unpickle(obj):
    """Helper to pickle and unpickle an object"""
    pickled = pickle.dumps(obj)
    return pickle.loads(pickled)


def test_loader_pickling():
    """Test that DraconLoader can be pickled and unpickled"""
    loader = DraconLoader()
    loader.enable_interpolation = True

    # Pickle and unpickle the loader
    unpickled_loader = pickle_unpickle(loader)

    # Check if attributes are preserved
    assert unpickled_loader.enable_interpolation == loader.enable_interpolation

    # Test that the unpickled loader can still load configs
    config = unpickled_loader.load(f"pkg:{simple_config_path}")
    assert config["root"]["a"] == 3
    assert config["root"]["inner"]["d"] == 6


def test_loaded_config_pickling():
    """Test that loaded configurations can be pickled and unpickled"""
    loader = DraconLoader()
    config = loader.load(f"pkg:{main_config_path}")

    # Pickle and unpickle the config
    unpickled_config = pickle_unpickle(config)

    # Verify the unpickled config matches the original
    assert unpickled_config["config"]["setting1"] == "newval1"
    assert unpickled_config["config"]["setting2"] == "baseval2"
    assert unpickled_config["config"]["extra"]["root"]["inner"]["d"] == 6
    assert unpickled_config["config"]["a_list"] == ["item1", "item2", "item3", "item4"]


def test_composition_result_pickling():
    """Test that composition results can be pickled and unpickled"""
    loader = DraconLoader()
    compres = loader.compose_from_include_str(f"pkg:{main_config_path}")

    # Pickle and unpickle the composition result
    unpickled_compres = pickle_unpickle(compres)

    # Load the unpickled composition result
    config = loader.load_composition_result(unpickled_compres)

    # Verify the config loaded from unpickled composition is correct
    assert config["config"]["setting1"] == "newval1"
    assert config["config"]["extra"]["root"]["inner"]["d"] == 6


def test_multiprocess_loading():
    """Test that configs can be loaded in separate processes"""
    with multiprocessing.Pool(2) as pool:
        # Load multiple configs in parallel
        configs = pool.map(load_config_in_process, [simple_config_path, params_config_path])

    # Verify the configs loaded correctly
    simple_config, params_config = configs

    # Check simple config
    assert simple_config["root"]["a"] == 3
    assert simple_config["root"]["inner"]["d"] == 6

    # Check params config
    assert params_config["param1"] == "value1_overriden"
    assert params_config["param2"] == "value2"


def test_pickle_with_interpolation():
    """Test pickling configs with interpolation enabled"""
    loader = DraconLoader(enable_interpolation=True)
    config = loader.load(f"pkg:{interp_config_path}")

    # Store any values we want to compare after unpickling
    pre_pickle_values = {
        'file_stem': config.base.file_stem,
        'interpolated_addition': config.base.interpolated_addition
        if hasattr(config.base, 'interpolated_addition')
        else None,
    }

    # Pickle and unpickle
    unpickled_config = pickle_unpickle(config)

    # Verify the structure is preserved
    assert hasattr(unpickled_config, 'base')

    # Compare values that should be preserved
    for key, value in pre_pickle_values.items():
        if value is not None:
            assert getattr(unpickled_config.base, key) == value


def test_lazy_interpolable_pickling():
    """Test pickling of individual LazyInterpolable objects"""
    # Create a simple LazyInterpolable
    lazy = LazyInterpolable(
        value="${2+2}",
        name="test",
        current_path=ROOTPATH,
        permissive=False,
        context={"some_context": "value"},
    )

    # Pickle and unpickle
    unpickled = pickle_unpickle(lazy)

    # Verify the basic attributes are preserved
    assert unpickled.value == "${2+2}"
    assert unpickled.name == "test"
    assert unpickled.permissive is False
    assert unpickled.context == {"some_context": "value"}


def test_lazy_interpolable_with_validator():
    """Test pickling of LazyInterpolable with validator"""

    def simple_validator(x):
        return int(x)

    # Create LazyInterpolable with validator
    lazy = LazyInterpolable(value="${2+2}", validator=simple_validator, name="test")

    # Pickle and unpickle
    unpickled = pickle_unpickle(lazy)

    # Reattach validator
    unpickled.reattach_validator(simple_validator)

    # Verify it still works
    resolved = unpickled.resolve()
    assert isinstance(resolved, int)
    assert resolved == 4


def load_with_interpolation(config_path):
    loader = DraconLoader(enable_interpolation=True)
    return loader.load(f"pkg:{config_path}")


def test_multiprocess_with_interpolation():
    """Test multiprocess loading with interpolation enabled"""

    with multiprocessing.Pool(1) as pool:
        config = pool.apply(load_with_interpolation, (interp_config_path,))

    assert config.base.file_stem == "interpolation"


def test_large_config_pickling():
    """Test pickling with a large nested configuration"""
    loader = DraconLoader()
    config = loader.load(f"pkg:{main_config_path}")

    # Create a large nested structure
    large_config = {
        "original": config,
        "nested": {
            "level1": {"level2": {"level3": config.copy()}},
            "array": [config.copy() for _ in range(10)],
        },
    }

    # Pickle and unpickle
    unpickled = pickle_unpickle(large_config)

    # Verify deep nested structures
    assert unpickled["original"]["config"]["setting1"] == "newval1"
    assert unpickled["nested"]["level1"]["level2"]["level3"]["config"]["setting1"] == "newval1"
    assert unpickled["nested"]["array"][5]["config"]["setting1"] == "newval1"


class ConfigModel(BaseModel):
    setting1: str
    setting2: str


def test_pydantic_model_pickling():
    """Test pickling when using Pydantic models"""

    loader = DraconLoader()
    config = loader.load(f"pkg:{simple_config_path}")
    model = ConfigModel(setting1="test1", setting2="test2")

    config_with_model = {"config": config, "model": model}

    # Pickle and unpickle
    unpickled = pickle_unpickle(config_with_model)

    # Verify both config and model are preserved
    assert unpickled["config"]["root"]["a"] == 3
    assert isinstance(unpickled["model"], ConfigModel)
    assert unpickled["model"].setting1 == "test1"


