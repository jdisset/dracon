import pytest
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel
from dracon.loader import DraconLoader
from dracon.commandline import make_program, Arg


class ModelConfig(BaseModel):
    learning_rate: float
    batch_size: int
    optimizer: str


def test_basic_generator():
    """Test basic generator functionality"""
    yaml_content = """
    model:
      learning_rate: !generate ${[0.1, 0.01]}
      batch_size: 32
    """

    loader = DraconLoader(enable_interpolation=True)
    configs, gpaths = loader.loads_all(yaml_content, with_generator_paths=True)

    assert len(configs) == 2
    assert len(gpaths) == 1
    assert configs[0].model.learning_rate == 0.1
    assert configs[0].model.batch_size == 32
    assert configs[1].model.learning_rate == 0.01
    assert configs[1].model.batch_size == 32


def test_basic_generator_expr():
    """Should also work with regular yaml lists"""

    yaml_content = """
    model:
      learning_rate: !generate [0.1, 0.01]
      batch_size: 32
    """

    loader = DraconLoader(enable_interpolation=True)
    configs = loader.loads_all(yaml_content)

    assert len(configs) == 2
    assert configs[0].model.learning_rate == 0.1
    assert configs[0].model.batch_size == 32
    assert configs[1].model.learning_rate == 0.01
    assert configs[1].model.batch_size == 32


def test_generator_with_define():
    """Test generator with define instruction"""
    yaml_content = """
    !define rates: !generate ${[0.1, 0.01]}
    model:
      learning_rate: ${rates}
      nested:
        also_rate: ${rates}
    """

    loader = DraconLoader(enable_interpolation=True)
    configs = loader.loads_all(yaml_content)

    assert len(configs) == 2
    assert configs[0].model.learning_rate == 0.1
    assert configs[0].model.nested.also_rate == 0.1
    assert configs[1].model.learning_rate == 0.01
    assert configs[1].model.nested.also_rate == 0.01


def test_multiple_generators():
    yaml_content = """
    model:
      learning_rate: !generate ${[0.1, 0.01]}
      optimizer: !generate ['adam', 'sgd']
    """

    loader = DraconLoader(enable_interpolation=True)
    configs = loader.loads_all(yaml_content)

    assert len(configs) == 4  # Cartesian product
    expected = [(0.1, 'adam'), (0.1, 'sgd'), (0.01, 'adam'), (0.01, 'sgd')]
    actual = [(c.model.learning_rate, c.model.optimizer) for c in configs]
    assert sorted(actual) == sorted(expected)


def test_chained_generator():
    yaml_content = """
    !define a: !generate ${[1, 2]}
    !define b: !generate ${[i for i in range(a)]}
    c: ${b}
    """

    loader = DraconLoader(enable_interpolation=True)
    configs = loader.loads_all(yaml_content)

    assert len(configs) == 3
    assert configs[0].c == 0
    assert configs[1].c == 0
    assert configs[2].c == 1


def test_multi_generator_key():
    yaml_content = """
    !generate ${['name_1', 'name_2']}: !generate [1, 2]
    """

    loader = DraconLoader(enable_interpolation=True)
    configs = loader.loads_all(yaml_content)

    assert len(configs) == 4
    assert configs[0] == {'name_1': 1}
    assert configs[1] == {'name_1': 2}
    assert configs[2] == {'name_2': 1}
    assert configs[3] == {'name_2': 2}


def test_generator_in_deferred():
    """Test generator within deferred nodes"""
    yaml_content = """
    training: !deferred:ModelConfig
      learning_rate: !generate [0.1, 0.01]
      batch_size: 32
      optimizer: 'adam'
    """

    loader = DraconLoader(enable_interpolation=True, context={'ModelConfig': ModelConfig})
    config = loader.loads(yaml_content)

    # Initially, should be a single deferred node
    assert len(config) == 1

    # When constructing, should generate multiple configs
    constructed = config.training.construct()
    assert isinstance(constructed, list)
    assert len(constructed) == 2
    assert all(isinstance(c, ModelConfig) for c in constructed)
    assert [c.learning_rate for c in constructed] == [0.1, 0.01]


def test_generator_in_deferred_with_context():
    """Test generator using runtime context in deferred nodes"""

    def get_rates():
        return [0.1, 0.01]

    yaml_content = """
    training: !deferred:ModelConfig
      learning_rate: !generate ${get_rates()}
      batch_size: 32
      optimizer: 'adam'
    """

    loader = DraconLoader(enable_interpolation=True, context={'ModelConfig': ModelConfig})
    config = loader.loads(yaml_content)

    # Update context before construction
    config.training.update_context({'get_rates': get_rates})
    constructed = config.training.construct()

    assert len(constructed) == 2
    assert [c.learning_rate for c in constructed] == [0.1, 0.01]


def test_generator_expression_types():
    """Test different types of generator expressions"""
    yaml_content = """
    # List literal
    v1: !generate [1, 2, 3]
    
    # Range
    v2: !generate ${range(1, 4)}
    
    """

    loader = DraconLoader(enable_interpolation=True)
    configs = loader.loads_all(yaml_content)

    assert len(configs) == 3 * 3
    assert [c.v1 for c in configs] == [1, 2, 3]
    assert [c.v2 for c in configs] == [1, 2, 3]


def test_nested_structure_with_generator():
    """Test generator in nested structure"""
    yaml_content = """
    outer:
      middle:
        inner: !generate ${range(1, 4)}
    other: fixed
    """

    loader = DraconLoader(enable_interpolation=True)
    configs = loader.loads_all(yaml_content)

    assert len(configs) == 3
    assert [c.outer.middle.inner for c in configs] == [1, 2, 3]
    assert all(c.other == "fixed" for c in configs)


def test_generator_in_sequence():
    """Test generator in sequence context"""
    yaml_content = """
    models:
      - name: model1
        rate: !generate [0.1, 0.01]
      - name: model2
        rate: 0.001
    """

    loader = DraconLoader(enable_interpolation=True)
    configs = loader.loads_all(yaml_content)

    assert len(configs) == 2
    assert [(c.models[0].rate, c.models[0].name) for c in configs] == [
        (0.1, "model1"),
        (0.01, "model1"),
    ]
    assert all(c.models[1].rate == 0.001 for c in configs)


def test_generator_with_dependencies():
    """Test generator with dependencies on other config values"""
    yaml_content = """
    base_rate: 0.1
    model:
      learning_rate: !generate ${[@/base_rate / 10, @/base_rate, @/base_rate * 10]}
    """

    loader = DraconLoader(enable_interpolation=True)
    configs = loader.loads_all(yaml_content)

    assert len(configs) == 3
    assert [c.model.learning_rate for c in configs] == [0.01, 0.1, 1.0]


def test_generator_config_inner():
    inner_config = "pkg:dracon:tests/configs/generators"

    # content is:
    # !set_default n: 3
    # !noconstruct value: &val
    #   b: ${a}
    # wrapper: !generate ${[&val:a=i for i in range(n)]}

    loader = DraconLoader(enable_interpolation=True)
    configs = loader.load_all(inner_config)

    assert len(configs) == 3
    for i, config in enumerate(configs):
        assert config.wrapper == {"value": {"b": i}}


def test_generator_config_outer():
    outer_config = "pkg:dracon:tests/configs/generator_include"

    # !define n: !generate [1, 2]
    # <<: !include file:$DIR/generators
    # !if ${n == 2}:
    #  n_is_2: true

    loader = DraconLoader(enable_interpolation=True)
    configs, gpaths = loader.load_all(outer_config, with_generator_paths=True)

    assert len(configs) == 3
    assert len(gpaths) == 3
    c0 = {"wrapper": {"value": {"b": 0}}}
    c1 = {"wrapper": {"value": {"b": 0}}, "n_is_2": True}
    c2 = {"wrapper": {"value": {"b": 1}}, "n_is_2": True}
    assert configs == [c0, c1, c2]


def test_error_handling():
    """Test error handling for invalid generators"""
    yaml_content = """
    value: !generate not_an_iterable
    """

    loader = DraconLoader(enable_interpolation=True)
    with pytest.raises(ValueError):
        loader.loads_all(yaml_content)


def test_empty_generator():
    """Test behavior with empty generator"""
    yaml_content = """
    value: !generate ${[]}
    """

    loader = DraconLoader(enable_interpolation=True)
    configs = loader.loads_all(yaml_content)

    assert len(configs) == 1
    assert configs[0].value is None
