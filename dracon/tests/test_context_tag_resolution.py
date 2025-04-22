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
