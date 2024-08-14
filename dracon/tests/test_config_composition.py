import os
from pathlib import Path
import pytest
from ruamel.yaml import YAML
from dracon import DraconLoader

# Set a dummy environment variable for testing purposes
os.environ["TESTVAR1"] = "test_var_1"
os.environ["TESTVAR2"] = "test_var_2"

# Test file paths
simple_config_path = 'dracon:tests/configs/simple.yaml'

main_config_path = 'dracon:tests/configs/main.yaml'
params_config_path = 'dracon:tests/configs/params.yaml'
base_config_path = 'dracon:tests/configs/base.yaml'
interp_config_path = 'dracon:tests/configs/interpolation.yaml'

def get_config(config_path):
    from dracon.loader import DraconLoader
    loader = DraconLoader()
    compres = loader.compose_from_include_str(f"pkg:{config_path}")
    config = loader.load_from_composition_result(compres)
    return config


def test_main_config_composition():

    config = get_config(main_config_path)

    # Check if the composition result matches the expected values
    assert config["base"]["setting.with.dot"] == "baseval3"
    assert config["config"]["setting1"] == "newval1"
    assert config["config"]["setting2"] == "baseval2"
    assert config["config"]["setting3"]["setting1"] == "baseval"
    assert config["config"]["setting3"]["setting2"] == "baseval2"
    assert config["config"]["setting3"]["setting.with.dot"] == "baseval3"

    assert config["config"]["extra"]["root"]["a"] == 3
    assert config["config"]["extra"]["root"]["b"] == 4
    assert config["config"]["extra"]["root"]["inner"]["c"] == 5
    assert config["config"]["extra"]["root"]["inner"]["d"] == 6
    assert config["config"]["extra"]["additional_settings"]["setting3"] == "additional_value3"
    assert config["config"]["home"] == "test_var_1"
    assert config["config"]["a_list"] == ["item1", "item2", "item3", "item4"]

    assert config["config"]["new_with.dot"] == "baseval3"

    assert config["other_base"]["default_settings"]["param1"] == "value1"
    assert config["other_base"]["default_settings"]["setting1"] == "default_value1"
    assert config["other_base"]["default_settings"]["setting2"] == "default_value2"
    assert config["other_base"]["default_settings"]["again"]["setting2"] == "value_params_2"
    assert (
        config["other_base"]["default_settings"]["just_simple"]["setting3"] == "additional_value3"
    )
    assert config["other_base"]["default_settings"]["just_simple"]["setting_list"] == [
        "item_lol",
        3,
        "item_lol",
    ]

    assert config["new_simple"]["root"] == {"a": "new_a"}
    assert config["new_simple"]["additional_settings"]["setting_list"] == [
        "item_lol",
        3,
        "item_lol",
    ]


def test_simple_config_inclusion():
    config = get_config(simple_config_path)

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
    config = get_config(params_config_path)

    # Check if the params configuration is composed correctly
    assert config["param1"] == "value1"
    assert config["param2"] == "value2"
    assert config["simple_params"]["root"]["a"] == 3
    assert config["simple_params"]["additional_settings"]["setting_list"] == [
        "item_lol",
        3,
        "item_lol",
    ]


def test_env_variable_inclusion():
    config = get_config(base_config_path)

    # Check if the environment variable is included correctly
    assert config["ppath"] == "test_var_2"



def test_composition_through_interpolation():
    loader = DraconLoader(enable_interpolation=True)
    config = loader.load(f"pkg:{interp_config_path}")

    assert "default_settings" in config["base"]
    assert "param1" in config["base"]["default_settings"]
    assert "setting1" in config["base"]["default_settings"]

    assert config.base.file_stem == "interpolation"
    assert config.base.interpolated_addition == 4

    assert config.loaded_base.default_settings.param1 == "value1"


if __name__ == "__main__":
    pytest.main([__file__])

