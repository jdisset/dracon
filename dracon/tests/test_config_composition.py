# filename: tests/test_config_composition.py
# (Showing only changed sections)

import os
from pathlib import Path
import pytest
from ruamel.yaml import YAML
from dracon.loader import DraconLoader
from dracon.resolvable import Resolvable
from pydantic import BaseModel
from dracon.include import compose_from_include_str
from dracon.utils import deepcopy
import tempfile

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


def main_config_ok(config):
    # check if the composition result matches the expected values
    # note: keys with literal dots remain accessed with the dot
    assert config["base"]["setting.with.dot"] == "baseval3"
    assert config["config"]["setting1"] == "newval1"
    assert config["config"]["setting2"] == "baseval2"
    assert config["config"]["setting2_incl"] == "baseval2"
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

    # note: key access uses the literal key name 'setting.with.dot'
    # the reference in main.yaml was changed from */base.setting\.with\.dot to */base/setting.with.dot
    assert config["config"]["new_with.dot"] == "baseval3"

    assert config["other_base"]["default_settings"]["param1"] == "value1_overriden"
    assert config["other_base"]["default_settings"]["setting1"] == "default_value1"
    assert config["other_base"]["default_settings"]["setting2"] == "default_value2"
    assert config["other_base"]["default_settings"]["again"]["setting2"] == "value_params_2"
    assert (
        config["other_base"]["default_settings"]["just_simple"]["setting3"] == "additional_value3"
    )
    # check list resolution with new keypath syntax: */root/a and *./0
    assert config["other_base"]["default_settings"]["just_simple"]["setting_list"] == [
        "item_lol",
        3,  # This comes from */root/a in simple.yaml via base.yaml -> params.yaml
        "item_lol",  # This comes from *./0 resolving to the first item in the list itself
    ]

    assert config["new_simple"]["root"] == {"a": "new_a"}
    # check list resolution again
    assert config["new_simple"]["additional_settings"]["setting_list"] == [
        "item_lol",
        3,  # This comes from */root/a in simple.yaml
        "item_lol",  # This comes from *./0 resolving to the first item in the list itself
    ]

    assert config["other_base"]["scalar"] == "hello"


def get_config(config_path):
    loader = DraconLoader(enable_interpolation=True)
    compres = compose_from_include_str(loader, f"pkg:{config_path}")
    config = loader.load_composition_result(compres)
    return config


def test_main_config_composition():
    config = get_config(main_config_path)
    main_config_ok(config)


def test_copy_composition_result():
    loader = DraconLoader()
    composition = compose_from_include_str(loader, f"pkg:{main_config_path}")

    # Copy the composition result and the loader
    comp_copy = deepcopy(composition)
    loader_copy = deepcopy(loader)

    origconf = loader.load_composition_result(composition)
    confcopy = loader_copy.load_composition_result(comp_copy)

    assert origconf == confcopy


def test_simple_config_inclusion():
    config = get_config(simple_config_path)

    assert 'root' in config
    assert 'inner' in config['root']
    assert 'a' in config['root']
    assert 'b' in config['root']
    assert 'c' in config['root']['inner']
    assert 'd' in config['root']['inner']

    # check if the extra configuration is composed correctly
    assert config["root"]["a"] == 3
    assert config["root"]["b"] == 4
    assert config["root"]["inner"]["c"] == 5
    assert config["root"]["inner"]["d"] == 6
    assert config["additional_settings"]["setting3"] == "additional_value3"
    # check list resolution with new keypath syntax: */root/a and *./0
    assert config["additional_settings"]["setting_list"] == [
        "item_lol",
        3,  # This comes from */root/a
        "item_lol",  # This comes from *./0 resolving to the first item in the list itself
    ]


def test_params_config():
    config = get_config(params_config_path)

    # check if the params configuration is composed correctly
    assert config["param1"] == "value1_overriden"
    assert config["param2"] == "value2"
    assert config["simple_params"]["root"]["a"] == 3
    # check list resolution with new keypath syntax: */root/a and *./0
    assert config["simple_params"]["additional_settings"]["setting_list"] == [
        "item_lol",
        3,  # This comes from */root/a in simple.yaml
        "item_lol",  # This comes from *./0 resolving to the first item in the list itself
    ]

    assert config["list2"] == [7, 8, 9]


def test_include_contexts():
    loader = DraconLoader(enable_interpolation=True)
    config_path = "pkg:dracon:tests/configs/incl_contexts.yaml"
    compres = compose_from_include_str(loader, config_path)
    # print(f"Composition result: {compres}") # Keep for debugging if needed
    config = loader.load_composition_result(compres)
    # print(f"Config: {config}") # Keep for debugging if needed

    assert config.fstem_basedir == "incl_contexts"
    assert config.fstem_subdir.fstem_here == "subincl"
    assert config.fstem_subdir.fstem_above.here == "fstem"

    # references like @a, @b are not affected by path separator change
    assert config.avar_from_sub == 3
    assert config.bvar_from_sub == 2

    assert config.vars.a == 5
    assert config.vars.b == 2


def test_composition_through_interpolation():
    loader = DraconLoader(enable_interpolation=True)
    config = loader.load(f"pkg:{interp_config_path}")

    assert "default_settings" in config["base"]
    assert "param1" in config["base"]["default_settings"]
    assert "setting1" in config["base"]["default_settings"]

    assert config.base.file_stem == "interpolation"
    assert config.base.interpolated_addition == 4

    assert config.loaded_base.default_settings.param1 == "value1_overriden"

    assert type(config.int4) is int
    assert config.int4 == 4
    assert config.floatstr == 'float'

    assert config.nested_int4 == 4

    assert isinstance(config.tag_interp, float)
    assert config.tag_interp == 4.0

    assert config.interp_later == 5
    assert type(config.interp_later) is int

    assert config.interp_later_tag == 5.0
    assert type(config.interp_later_tag) is float

    # The fstem test was inside subbase.yaml which is included in interpolation.yaml's base
    assert config.base.fstem.here == "fstem"


def test_override():
    loader = DraconLoader()
    config = loader.load(f"pkg:{override_config_path}")

    # check overrides using new syntax like @default_settings/setting1
    assert config["default_settings"]["setting1"] == "override_value1"
    assert config["default_settings"]["setting2"] == "default_value2"
    assert config["default_settings"]["setting3"] == "override_value3"
    # check list override @default_settings/setting_list/0 and list merge
    # Original list: [item1, item2, item3] from override.yaml
    # Merged with simple@additional_settings: [item_lol, */root/a -> 3, *./0 -> item_lol] using <<{<}[<] (new priority, append list)
    #   -> result before override: [item1, item2, item3, item_lol, 3, item_lol]
    # Override setting3: adds setting3=override_value3
    # Override setting_list with [item4] using <<[>+] (existing priority, append list)
    #   -> result after this override: [item1, item2, item3, item_lol, 3, item_lol, item4]
    # Override setting_list[0] with override_item1 using <<@...
    #   -> final result: [override_item1, item2, item3, item_lol, 3, item_lol, item4]
    assert config["default_settings"]["setting_list"] == [
        "override_item1",
        "item2",
        "item3",
        "item_lol",
        3,
        "item_lol",
        "item4",
    ]


class Person(BaseModel):
    name: str
    age: int


class WithResolvable(BaseModel):
    ned: Resolvable[Person]


def test_resolvable():
    loader = DraconLoader(
        enable_interpolation=True, context={"Person": Person, "WithResolvable": WithResolvable}
    )
    config = loader.load(f"pkg:{resolvable_config_path}")

    assert type(config.ned) is Resolvable
    ned = config.ned.resolve()
    assert type(ned) is Person
    assert ned.name == "Eddard"
    assert ned.age == 40


def test_include_interpolation():
    config = get_config('dracon:tests/configs/include_interpolations.yaml')
    # check that config.base is the base config:
    assert config.base.default_settings.setting1 == "default_value1"
    assert config.base.default_settings.simple_params.root.a == 3
    # check reference with path separator: @simple_params/additional_settings
    assert config.just_simple.setting3 == "additional_value3"
    # check list resolution with new keypath syntax: */root/a and *./0
    assert config.just_simple.setting_list == [
        "item_lol",
        3,  # */root/a from simple.yaml
        "item_lol",  # *./0 from simple.yaml
    ]


if __name__ == "__main__":
    pytest.main([__file__])
