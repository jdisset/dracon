import os
from pathlib import Path
import pytest
from ruamel.yaml import YAML
from dracon.loader import DraconLoader
from dracon.resolvable import Resolvable
from pydantic import BaseModel
from dracon.include import compose_from_include_str
from dracon.utils import deepcopy

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


class Person(BaseModel):
    name: str
    age: int


class WithResolvable(BaseModel):
    ned: Resolvable[Person]


def main_config_ok(config):
    # Check if the composition result matches the expected values
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

    assert config["config"]["new_with.dot"] == "baseval3"

    assert config["other_base"]["default_settings"]["param1"] == "value1_overriden"
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
    assert config["param1"] == "value1_overriden"
    assert config["param2"] == "value2"
    assert config["simple_params"]["root"]["a"] == 3
    assert config["simple_params"]["additional_settings"]["setting_list"] == [
        "item_lol",
        3,
        "item_lol",
    ]

    assert config["list2"] == [7, 8, 9]


def test_include_contexts():
    loader = DraconLoader(enable_interpolation=True)
    config_path = "pkg:dracon:tests/configs/incl_contexts.yaml"
    compres = compose_from_include_str(loader, config_path)
    print(f"Composition result: {compres}")
    config = loader.load_composition_result(compres)
    print(f"Config: {config}")

    assert config.fstem_basedir == "incl_contexts"
    assert config.fstem_subdir.fstem_here == "subincl"
    assert config.fstem_subdir.fstem_above.here == "fstem"

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

    # assert config.base.fstem == "fstem"


def test_override():
    loader = DraconLoader()
    config = loader.load(f"pkg:{override_config_path}")

    print(f"Config: {config}")

    assert config["default_settings"]["setting1"] == "override_value1"
    assert config["default_settings"]["setting2"] == "default_value2"
    assert config["default_settings"]["setting3"] == "additional_value3"
    # assert config["default_settings"]["setting_list"] == ["override_item1", 3, "item_lol", "item4"]

    assert config["default_settings"]["setting_list"] == [
        "override_item1",
        3,
        "item_lol",
        "item1",
        "item2",
        "item3",
        "item4",
    ]


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
    assert config.just_simple.setting3 == "additional_value3"
    assert config.just_simple.setting_list == ["item_lol", 3, "item_lol"]


def test_construct_copy_vs_ref(tmp_path):
    from dracon import load
    from pydantic import BaseModel
    from dracon import make_program

    base = tmp_path / "base"
    sub = base / "sub"
    base.mkdir()
    sub.mkdir()

    # Nested file using $(DIR) to reference target
    nested_file = sub / "nested.yaml"
    nested_file.write_text("""
- $(DIR)
- $DIR
""")

    main_file = base / "main.yaml"
    main_file.write_text("""
here: $DIR
incl: !include file:$DIR/sub/nested.yaml
val_incl: !include file:$DIR/sub/nested@0
!noconstruct nct: !include file:$DIR/sub/nested.yaml
constructed_ref: ${construct(@/val_incl)}
constructed_cpy: ${construct(&/val_incl)}
constructed_full_ref: ${@/incl}
constructed_full_cpy: ${&/incl}
constructed_full_cpy_nct: $(construct(&/nct))


each:
    !each(dname) "${construct(@/incl)}":
    - $(dname)

""")

    direct_config = load(str(main_file))
    from dracon import resolve_all_lazy

    resolve_all_lazy(direct_config)
    assert direct_config['here'] == str(base)
    assert direct_config['incl'][0] == str(sub)
    assert direct_config['incl'][1] == str(sub)
    assert direct_config['val_incl'] == str(sub)
    assert direct_config['constructed_ref'] == str(sub)
    assert direct_config['constructed_cpy'] == str(
        sub
    )  # the node itself is copied, even before evaluation
    assert direct_config['constructed_full_ref'] == [str(sub), str(sub)]
    assert direct_config['constructed_full_cpy'] == [str(sub), str(sub)]
    assert direct_config['constructed_full_cpy_nct'] == [str(sub), str(sub)]

    assert direct_config['each'] == [str(sub), str(sub)]


def test_nested_dir_context_preservation(tmp_path):
    from dracon import load

    train_dir = tmp_path / "train"
    matrices_dir = train_dir / "matrices"
    composite_dir = matrices_dir / "composite_sets"
    basic_sets_dir = matrices_dir / "basic_sets"

    train_dir.mkdir()
    matrices_dir.mkdir()
    composite_dir.mkdir()
    basic_sets_dir.mkdir()

    basic_set_content = """
name: basic_set
data:
  - item1
  - item2
"""
    basic_set_file = basic_sets_dir / "basic.yaml"
    basic_set_file.write_text(basic_set_content)

    composite_set_content = """
name: composite_set
includes:
  - !include file:$DIR/../basic_sets/basic.yaml
"""
    composite_set_file = composite_dir / "composite.yaml"
    composite_set_file.write_text(composite_set_content)

    main_config_content = """
training_set: !include file:$DIR/matrices/composite_sets/composite.yaml
"""
    main_config_file = train_dir / "main.yaml"
    main_config_file.write_text(main_config_content)

    config = load(str(main_config_file))

    assert config["training_set"]["name"] == "composite_set"
    assert config["training_set"]["includes"][0]["name"] == "basic_set"
    assert config["training_set"]["includes"][0]["data"] == ["item1", "item2"]


def test_deeply_nested_dir_context(tmp_path):
    from dracon import load

    # create deeper directory structure
    level1_dir = tmp_path / "level1"
    level2_dir = level1_dir / "level2"
    level3_dir = level2_dir / "level3"
    sibling_dir = level2_dir / "sibling"

    level1_dir.mkdir()
    level2_dir.mkdir()
    level3_dir.mkdir()
    sibling_dir.mkdir()

    sibling_content = """
name: sibling_data
value: 42
"""
    sibling_file = sibling_dir / "data.yaml"
    sibling_file.write_text(sibling_content)

    level3_content = """
name: level3_config
sibling_ref: !include file:$DIR/../sibling/data.yaml
"""
    level3_file = level3_dir / "config.yaml"
    level3_file.write_text(level3_content)

    level2_content = """
name: level2_config
nested: !include file:$DIR/level3/config.yaml
"""
    level2_file = level2_dir / "config.yaml"
    level2_file.write_text(level2_content)

    level1_content = """
name: level1_config
deep: !include file:$DIR/level2/config.yaml
"""
    level1_file = level1_dir / "config.yaml"
    level1_file.write_text(level1_content)

    config = load(str(level1_file))

    assert config["name"] == "level1_config"
    assert config["deep"]["name"] == "level2_config"
    assert config["deep"]["nested"]["name"] == "level3_config"
    assert config["deep"]["nested"]["sibling_ref"]["name"] == "sibling_data"
    assert config["deep"]["nested"]["sibling_ref"]["value"] == 42


def test_dir_context_with_merge_operations(tmp_path):
    from dracon import load

    base_dir = tmp_path / "base"
    includes_dir = base_dir / "includes"

    base_dir.mkdir()
    includes_dir.mkdir()

    included_content = """
included_key: included_value
nested:
  key1: value1
"""
    included_file = includes_dir / "included.yaml"
    included_file.write_text(included_content)

    another_content = """
another_key: another_value
"""
    another_file = includes_dir / "another.yaml"
    another_file.write_text(another_content)

    composite_content = """
name: composite
nested:
  key2: value2
  <<: !include file:$DIR/another.yaml
<<: !include file:$DIR/../includes/included.yaml
"""
    composite_file = includes_dir / "composite.yaml"
    composite_file.write_text(composite_content)

    main_content = """
main_key: main_value
composite_ref: !include file:$DIR/includes/composite.yaml
"""
    main_file = base_dir / "main.yaml"
    main_file.write_text(main_content)

    config = load(str(main_file))

    assert config["main_key"] == "main_value"
    assert config["composite_ref"]["name"] == "composite"
    assert config["composite_ref"]["included_key"] == "included_value"
    assert config["composite_ref"]["nested"]["key1"] == "value1"
    assert config["composite_ref"]["nested"]["key2"] == "value2"
    assert config["composite_ref"]["nested"]["another_key"] == "another_value"


# TODO: context propagation feature.
# It should allow to propagate any context upstream when the merge operation is used with (<) operator (i.e. merge context of node into parent node).
# That probably requires having a context holder at the CompositionResult level?
# Or maybe every node should have a context? I think at least a MappingNode should have a context.
# This way, everytime there's a !define (or !set_default, or similar) operation, it should already be able to
# modify the context of the parent node (which should be a MappingNode). Then, we need to make sure that modifying the context of a parent node does also propagate the context to all the children nodes.
# For `<<(<): !include ...` type stuff, we need to make sure that the loader-specific context is NOT propagated upstream.


def test_context_propagation(tmp_path):
    from dracon import load

    base_dir = tmp_path / "base"
    base_dir.mkdir()

    main_default = """
    !set_default var1: 0
    var1value: ${var1}
    <<:
        !define var1: 42
        included_key: included_value
"""
    main1 = base_dir / "main_default.yaml"
    main1.write_text(main_default)

    main_with_prop = """
    !set_default var1: 0
    var1value: ${var1}
    <<(<):
        !define var1: 42
        included_key: included_value
    """
    main2 = base_dir / "main_with_prop.yaml"
    main2.write_text(main_with_prop)

    config_default = load(str(main1))
    config_with_prop = load(str(main2))
    assert config_default["var1value"] == 0
    assert config_default["included_key"] == "included_value"
    assert config_with_prop["var1value"] == 42
    assert config_with_prop["included_key"] == "included_value"


def test_context_propagation_w_includes(tmp_path):
    from dracon import load

    base_dir = tmp_path / "base"
    includes_dir = base_dir / "includes"

    base_dir.mkdir()
    includes_dir.mkdir()

    included_content = """
!define var1: 42
included_dir: $DIR
"""
    included_file = includes_dir / "included.yaml"
    included_file.write_text(included_content)

    main_content_with_context_prop = """
!set_default var1: 0
var1value: ${var1}
current_dir: $DIR
<<(<): !include file:$DIR/includes/included.yaml
"""
    main1 = base_dir / "main.yaml"
    main1.write_text(main_content_with_context_prop)

    main_content_without_context_prop = """
    !set_default var1: 0
    var1value: $var1
    current_dir: $DIR
    <<: !include file:$DIR/includes/included.yaml
"""
    main2 = base_dir / "main_no_context.yaml"
    main2.write_text(main_content_without_context_prop)

    config_with_context = load(str(main1))
    config_without_context = load(str(main2))

    assert config_with_context["var1value"] == 42
    assert config_with_context["included_key"] == "included_value"
    assert config_with_context["nested"]["key1"] == "value1"

    # loader-specific variables should be preserved
    assert config_with_context["current_dir"] == str(base_dir)
    assert config_with_context["included_dir"] == str(includes_dir)

    assert config_without_context["var1value"] == 0
    assert config_without_context["included_key"] == "included_value"
    assert config_without_context["nested"]["key1"] == "value1"

    assert config_without_context["current_dir"] == str(base_dir)
    assert config_without_context["included_dir"] == str(includes_dir)


if __name__ == "__main__":
    pytest.main([__file__])
