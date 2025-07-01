import pytest
from pydantic import BaseModel
from dracon import DraconLoader, DraconError


class MyContextModel(BaseModel):
    name: str
    value: int


yaml_string_with_custom_tag = """
!MyCustomTagInContext
name: TestModel
value: 123
"""


def test_type_resolution_via_context():
    """
    Verify that the loader's context is used by the constructor
    to resolve type tags.
    """
    loader = DraconLoader(context={'MyCustomTagInContext': MyContextModel})

    loaded_obj = loader.loads(yaml_string_with_custom_tag)
    assert isinstance(loaded_obj, MyContextModel)
    assert loaded_obj.name == "TestModel"
    assert loaded_obj.value == 123


def test_type_resolution_missing_context():
    """Verify failure when the context doesn't contain the tag."""
    loader_no_context = DraconLoader()  # No context provided

    with pytest.raises((ValueError, DraconError)):
        loader_no_context.loads(yaml_string_with_custom_tag)


def test_type_resolution_context_added_after_init():
    """
    Verify if context added *after* initialization is used for type resolution.
    This mimics the commandline.py behavior.
    """
    loader = DraconLoader()  # Initialize with empty context
    loader.context['MyCustomTagInContext'] = MyContextModel
    loader.loads(yaml_string_with_custom_tag)


def test_type_resolution_context_updated_via_method():
    """
    Verify if using loader.update_context works after init.
    """
    loader = DraconLoader()
    loader.update_context({'MyCustomTagInContext': MyContextModel})

    loader.loads(yaml_string_with_custom_tag)


# YAML string where the root has the custom tag
yaml_string_root_tag = """
!MyRootTagInContext
name: RootModel
value: 456
"""


def test_type_resolution_root_tag_context_added_after_init():
    """
    Verify context added after init works for a ROOT tag.
    """
    loader = DraconLoader()
    loader.context['MyRootTagInContext'] = MyContextModel

    loaded_obj = loader.loads(yaml_string_root_tag)

    assert isinstance(loaded_obj, MyContextModel)
    assert loaded_obj.name == "RootModel"
    assert loaded_obj.value == 456


def test_type_resolution_via_include_and_context(tmp_path):
    """
    Verify context is available when resolving types within included files.
    """
    include_file = tmp_path / "include_me.yaml"
    include_file.write_text(yaml_string_with_custom_tag)  # Uses !MyCustomTagInContext

    main_yaml = f"""
    included_data: !include file:{include_file}
    """

    loader = DraconLoader()
    loader.context['MyCustomTagInContext'] = MyContextModel

    loaded_obj = loader.loads(main_yaml)

    assert isinstance(loaded_obj.included_data, MyContextModel)
    assert loaded_obj.included_data.name == "TestModel"


# Tests for package path resolution
yaml_string_with_package_path = """
!pydantic.BaseModel
name: TestModel
value: 123
"""

yaml_string_root_with_package_path = """
!dracon.tests.test_context_tag_resolution.MyContextModel
name: RootPackageModel
value: 789
"""


def test_package_path_resolution():
    """
    Verify that tags with package paths (e.g., !some.package.Class) are resolved correctly.
    """
    loader = DraconLoader()
    
    loaded_obj = loader.loads(yaml_string_with_package_path)
    assert isinstance(loaded_obj, BaseModel)
    # pydantic.BaseModel won't have name/value fields, so we just check the type


def test_root_tag_with_package_path():
    """
    Verify that root-level tags with full package paths work correctly.
    """
    loader = DraconLoader()
    
    loaded_obj = loader.loads(yaml_string_root_with_package_path)
    # the class might be reimported, so check by class name instead
    assert type(loaded_obj).__name__ == 'MyContextModel'
    assert loaded_obj.name == "RootPackageModel"
    assert loaded_obj.value == 789


def test_package_path_resolution_with_context_override():
    """
    Verify that context can override package path resolution.
    """
    class MyOverrideModel(BaseModel):
        override_name: str
        override_value: int
    
    yaml_with_override = """
!pydantic.BaseModel
override_name: OverrideTest
override_value: 999
"""
    
    loader = DraconLoader(context={'pydantic.BaseModel': MyOverrideModel})
    
    loaded_obj = loader.loads(yaml_with_override)
    assert isinstance(loaded_obj, MyOverrideModel)
    assert loaded_obj.override_name == "OverrideTest"
    assert loaded_obj.override_value == 999


def test_nested_package_path_resolution():
    """
    Verify package path resolution works for nested structures.
    """
    yaml_nested = """
main_model:
  !dracon.tests.test_context_tag_resolution.MyContextModel
  name: NestedModel
  value: 555
other_data:
  - !pydantic.BaseModel {}
  - regular: data
"""
    
    loader = DraconLoader()
    
    loaded_obj = loader.loads(yaml_nested)
    # check by class name due to potential reimport issues
    assert type(loaded_obj.main_model).__name__ == 'MyContextModel'
    assert loaded_obj.main_model.name == "NestedModel"
    assert loaded_obj.main_model.value == 555
    assert isinstance(loaded_obj.other_data[0], BaseModel)


def test_package_path_with_file_loading(tmp_path):
    """
    Verify package path resolution works when loading from files.
    """
    yaml_file = tmp_path / "package_path_test.yaml"
    yaml_file.write_text(yaml_string_root_with_package_path)
    
    loader = DraconLoader()
    
    loaded_obj = loader.load(yaml_file)
    # check by class name due to potential reimport issues
    assert type(loaded_obj).__name__ == 'MyContextModel'
    assert loaded_obj.name == "RootPackageModel"
    assert loaded_obj.value == 789
