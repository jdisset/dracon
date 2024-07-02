import os
from pathlib import Path
import pytest
from ruamel.yaml import YAML
from dracon import *

# Set a dummy environment variable for testing purposes
os.environ["TESTVAR1"] = "test_var_1"
os.environ["TESTVAR2"] = "test_var_2"

# Test file paths
simple_config_path = 'dracon:tests/configs/simple.yaml'

main_config_path = 'dracon:tests/configs/main.yaml'
params_config_path = 'dracon:tests/configs/params.yaml'
base_config_path = 'dracon:tests/configs/base.yaml'

def test_simple_config_composition():

    simple_config_content = read_from_pkg(main_config_path)


def test_main_config_composition():
    # Load and compose the simple configuration
    main_config_content = read_from_pkg(main_config_path)
    compres = compose_config_from_str(main_config_content)
    config = load_from_composition_result(compres)

    # Check if the composition result matches the expected values
    assert config["config"]["setting1"] == "newval1"
    assert config["config"]["setting2"] == "baseval2"
    assert config["config"]["setting3"]["setting1"] == "baseval"
    assert config["config"]["setting3"]["setting2"] == "baseval2"
    assert config["config"]["extra"]["root"]["a"] == 3
    assert config["config"]["extra"]["root"]["b"] == 4
    assert config["config"]["extra"]["root"]["inner"]["c"] == 5
    assert config["config"]["extra"]["root"]["inner"]["d"] == 6
    assert config["config"]["extra"]["additional_settings"]["setting3"] == "additional_value3"
    assert config["config"]["home"] == "test_var_1"
    assert config["config"]["a_list"] == ["item1", "item2", "item3", "item4"]

    assert config["other_base"]["default_settings"]["param1"] == "value1"
    assert config["other_base"]["default_settings"]["setting1"] == "default_value1"
    assert config["other_base"]["default_settings"]["setting2"] == "default_value2"
    assert config["other_base"]["default_settings"]["again"]["setting2"] == "value_params_2"

def test_simple_config_inclusion():
    # Load and compose the extra configuration
    simple_config_content = read_from_pkg(simple_config_path)
    compres = compose_config_from_str(simple_config_content)
    config = load_from_composition_result(compres)

    assert 'root' in config
    assert 'inner' in config['root']
    assert 'a' in config['root']
    assert 'b' in config['root']
    assert 'c' in config['root']['inner']
    assert 'd' in config['root']['inner']

    # Check if the extra configuration is composed correctly
    assert config["root"]["a"] == 3
    assert config["root"]["b"] == 4
    assert config["root"]["inner"]["c"] == 5
    assert config["root"]["inner"]["d"] == 6
    assert config["additional_settings"]["setting3"] == "additional_value3"
    assert config["additional_settings"]["setting_list"] == ["item_lol", 3, "item_lol"]

def test_params_config():
    # Load and compose the params configuration
    params_config_content = read_from_pkg(params_config_path)
    compres = compose_config_from_str(params_config_content)
    config = load_from_composition_result(compres)

    # Check if the params configuration is composed correctly
    assert config["param1"] == "value1"
    assert config["param2"] == "value2"
    assert config["simple_params"]["root"]["a"] == 3
    assert config["simple_params"]["additional_settings"]["setting_list"] == ["item_lol", 3, "item_lol"]

def test_env_variable_inclusion():
    # Load and compose the base configuration
    base_config_content = read_from_pkg(base_config_path)
    compres = compose_config_from_str(base_config_content)
    config = load_from_composition_result(compres)

    # Check if the environment variable is included correctly
    assert config["ppath"] == "test_var_2"

if __name__ == "__main__":
    pytest.main([__file__])
