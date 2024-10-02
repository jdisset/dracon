import pytest
from dracon import DraconLoader
from dracon.resolvable import Resolvable
from pydantic import BaseModel


class MyClass(BaseModel):
    attr1: dict
    attr2: str
    subattr_1: str
    subattr_2: str


def test_resolvable_merge_attrs():
    yaml_content = """
    !MyClass
    attr1:
      key1: value1
    attr2: some_value
    subattr_1: subvalue1
    subattr_2: subvalue2
    """

    loader = DraconLoader(context={'MyClass': MyClass})
    obj = loader.loads(yaml_content)
    assert isinstance(obj, MyClass)

    # Create a Resolvable instance for testing
    compo_result = loader.compose_config_from_str(yaml_content)
    resolvable_obj = Resolvable(
        node=compo_result.root,
        ctor=loader.yaml.constructor,
        inner_type=MyClass,
    )

    new_resolvable = resolvable_obj.merge_attrs(
        attr='attr1',
        subattrs=['subattr_1', 'subattr_2'],
        merge_key='<<{+>}',
    )

    final_obj = new_resolvable.resolve()

    # Check that the merged attributes are present in attr1
    assert 'subattr_1' in final_obj.attr1
    assert 'subattr_2' in final_obj.attr1
    assert final_obj.attr1['subattr_1'] == 'subvalue1'
    assert final_obj.attr1['subattr_2'] == 'subvalue2'

    # Ensure other attributes remain unchanged
    assert final_obj.attr2 == 'some_value'
    assert final_obj.subattr_1 == 'subvalue1'
    assert final_obj.subattr_2 == 'subvalue2'

    # attr1 should also contain its original content
    assert 'key1' in final_obj.attr1
    assert final_obj.attr1['key1'] == 'value1'


def test_resolvable_merge_attrs_custom_merge_key():
    yaml_content = """
    !MyClass
    attr1:
      key1: value1
    attr2: some_value
    subattr_1: subvalue1
    subattr_2: subvalue2
    """

    loader = DraconLoader(context={'MyClass': MyClass})
    obj = loader.loads(yaml_content)
    assert isinstance(obj, MyClass)

    compo_result = loader.compose_config_from_str(yaml_content)
    resolvable_obj = Resolvable(
        node=compo_result.root,
        ctor=loader.yaml.constructor,
        inner_type=MyClass,
    )

    # Use the merge_attrs method with a custom merge key
    new_resolvable = resolvable_obj.merge_attrs(
        attr='attr1',
        subattrs=['subattr_1', 'subattr_2'],
        merge_key='<<{~<}',
    )

    final_obj = new_resolvable.resolve()

    # Since we used a replace mode, attr1 should be replaced with the new subattributes
    assert 'key1' not in final_obj.attr1
    assert 'subattr_1' in final_obj.attr1
    assert 'subattr_2' in final_obj.attr1
    assert final_obj.attr1['subattr_1'] == 'subvalue1'
    assert final_obj.attr1['subattr_2'] == 'subvalue2'
