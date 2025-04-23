import pytest
from dracon import DraconLoader, dump, loads
from dracon.representer import DraconRepresenter, DraconDumpable
from dracon.nodes import (
    DraconMappingNode,
    DraconSequenceNode,
    DraconScalarNode,
    DEFAULT_MAP_TAG,
    DEFAULT_SEQ_TAG,
    DEFAULT_SCALAR_TAG,
)
from dracon.dracontainer import Mapping as DraconMapping, Sequence as DraconSequence
from dracon.lazy import LazyInterpolable
from dracon.resolvable import Resolvable
from dracon.deferred import DeferredNode, make_deferred
from dracon.interpolation import InterpolableNode
from pydantic import BaseModel, Field
from typing import List, Optional


# --- Models and Custom Types ---


class SimpleModel(BaseModel):
    name: str
    value: int = 10


class NestedModel(BaseModel):
    id: int
    simple: SimpleModel
    optional_simple: Optional[SimpleModel] = None
    items: List[str] = Field(default_factory=list)


class CustomDump(DraconDumpable):
    def __init__(self, data):
        self.data = data

    def dracon_dump_to_node(self, representer):
        # represent as a mapping with a custom tag (tag name doesn't matter much)
        return representer.represent_mapping('!CustomDump', {'custom_data': self.data})

    def __eq__(self, other):
        if isinstance(other, CustomDump):
            return self.data == other.data
        return False


# --- Fixtures ---


@pytest.fixture
def representer_default():
    return DraconRepresenter(full_module_path=False, exclude_defaults=True)


@pytest.fixture
def representer_full_path():
    return DraconRepresenter(full_module_path=True, exclude_defaults=True)


@pytest.fixture
def representer_include_defaults():
    return DraconRepresenter(full_module_path=False, exclude_defaults=False)


# --- Tests ---


def test_represent_basic_types(representer_default):
    assert isinstance(representer_default.represent_data(123), DraconScalarNode)
    # ruamel represents numbers as strings internally, but tags them
    assert representer_default.represent_data(123).value == '123'
    assert representer_default.represent_data(123).tag == 'tag:yaml.org,2002:int'

    assert isinstance(representer_default.represent_data("hello"), DraconScalarNode)
    assert representer_default.represent_data("hello").value == 'hello'
    assert representer_default.represent_data("hello").tag == DEFAULT_SCALAR_TAG

    assert isinstance(representer_default.represent_data(True), DraconScalarNode)
    assert representer_default.represent_data(True).value == 'true'
    assert representer_default.represent_data(True).tag == 'tag:yaml.org,2002:bool'

    list_node = representer_default.represent_data([1, "a"])
    assert isinstance(list_node, DraconSequenceNode)
    assert len(list_node.value) == 2
    assert list_node.value[0].value == '1'
    assert list_node.value[1].value == 'a'
    assert list_node.tag == DEFAULT_SEQ_TAG

    dict_node = representer_default.represent_data({"x": 1, "y": "b"})
    assert isinstance(dict_node, DraconMappingNode)
    assert len(dict_node.value) == 2
    represented_items = {k.value: v.value for k, v in dict_node.value}
    assert represented_items == {"x": '1', "y": 'b'}
    assert dict_node.tag == DEFAULT_MAP_TAG


def test_represent_dracon_containers(representer_default):
    dmap = DraconMapping({'a': 1, 'b': DraconSequence([2, 3])})
    node = representer_default.represent_data(dmap)
    assert isinstance(node, DraconMappingNode)
    assert node.tag == DEFAULT_MAP_TAG
    represented_items = {k.value: v for k, v in node.value}
    assert represented_items['a'].value == '1'
    assert isinstance(represented_items['b'], DraconSequenceNode)
    assert represented_items['b'].value[0].value == '2'

    dseq = DraconSequence([4, DraconMapping({'x': 5})])
    node = representer_default.represent_data(dseq)
    assert isinstance(node, DraconSequenceNode)
    assert node.tag == DEFAULT_SEQ_TAG
    assert node.value[0].value == '4'
    assert isinstance(node.value[1], DraconMappingNode)
    assert node.value[1].value[0][0].value == 'x'
    assert node.value[1].value[0][1].value == '5'


def test_represent_pydantic_model_defaults(representer_default, representer_include_defaults):
    model = SimpleModel(name="test")  # value=10 is default

    # exclude_defaults=True (default)
    node_excluded = representer_default.represent_data(model)
    assert isinstance(node_excluded, DraconMappingNode)
    assert node_excluded.tag == '!SimpleModel'
    represented_items = {k.value: v.value for k, v in node_excluded.value}
    assert 'name' in represented_items
    assert 'value' not in represented_items  # default excluded

    # exclude_defaults=False
    node_included = representer_include_defaults.represent_data(model)
    assert isinstance(node_included, DraconMappingNode)
    assert node_included.tag == '!SimpleModel'
    represented_items = {k.value: v.value for k, v in node_included.value}
    assert 'name' in represented_items
    assert 'value' in represented_items  # default included
    assert represented_items['value'] == '10'


def test_represent_pydantic_model_nested(representer_default):
    nested_model = NestedModel(id=1, simple=SimpleModel(name="inner", value=20))
    node = representer_default.represent_data(nested_model)

    assert isinstance(node, DraconMappingNode)
    assert node.tag == '!NestedModel'
    items = {k.value: v for k, v in node.value}
    assert items['id'].value == '1'
    assert isinstance(items['simple'], DraconMappingNode)
    assert items['simple'].tag == '!SimpleModel'
    inner_items = {k.value: v.value for k, v in items['simple'].value}
    assert inner_items['name'] == 'inner'
    assert inner_items['value'] == '20'  # not default, so included
    assert 'optional_simple' not in items  # None/default, excluded
    assert 'items' not in items  # empty list factory default, excluded


def test_represent_pydantic_model_full_path(representer_full_path):
    model = SimpleModel(name="test")
    node = representer_full_path.represent_data(model)
    assert node.tag == f"!{SimpleModel.__module__}.SimpleModel"


def test_represent_lazy_interpolable(representer_default):
    lazy = LazyInterpolable(value="${env:VAR}", context={'some_var': 'value'})
    node = representer_default.represent_data(lazy)
    assert isinstance(node, InterpolableNode)
    assert node.value == "${env:VAR}"
    assert node.context == {'some_var': 'value'}


def test_represent_resolvable(representer_default):
    # resolvable should represent its underlying node
    inner_node = representer_default.represent_scalar('!int', '123')
    resolvable = Resolvable(node=inner_node)
    node = representer_default.represent_data(resolvable)
    # check if it's the *same kind* of node with same value/tag
    assert isinstance(node, DraconScalarNode)
    assert node.value == inner_node.value
    assert node.tag == inner_node.tag

    # test empty resolvable
    empty_resolvable = Resolvable(node=None)
    empty_node = representer_default.represent_data(empty_resolvable)
    assert isinstance(empty_node, DraconScalarNode)
    assert empty_node.tag == 'tag:yaml.org,2002:null'


def test_represent_deferred_node(representer_default):
    inner_map = DraconMappingNode(
        tag=DEFAULT_MAP_TAG,
        value=[
            (
                DraconScalarNode(tag=DEFAULT_SCALAR_TAG, value='a'),
                DraconScalarNode(tag='tag:yaml.org,2002:int', value='1'),
            )
        ],
    )
    deferred = DeferredNode(value=inner_map)
    node = representer_default.represent_data(deferred)
    # check the type of the node object is the inner type, but tag is modified
    assert isinstance(node, DraconMappingNode), (
        f"Expected inner node type DraconMappingNode, got {type(node)}"
    )
    assert node.tag == '!deferred'
    assert node.value[0][0].value == 'a'
    assert node.value[0][1].value == '1'

    # with type tag
    inner_map_tagged = DraconMappingNode(
        tag='!MyType',
        value=[
            (
                DraconScalarNode(tag=DEFAULT_SCALAR_TAG, value='b'),
                DraconScalarNode(tag='tag:yaml.org,2002:int', value='2'),
            )
        ],
    )
    deferred_tagged = DeferredNode(value=inner_map_tagged)
    node_tagged = representer_default.represent_data(deferred_tagged)
    assert isinstance(node_tagged, DraconMappingNode), (
        f"Expected inner node type DraconMappingNode, got {type(node_tagged)}"
    )
    assert node_tagged.tag == '!deferred:MyType'

    # with clear_ctx list
    deferred_clear_list = DeferredNode(value=inner_map, clear_ctx=['VAR1', 'VAR2'])
    node_clear_list = representer_default.represent_data(deferred_clear_list)
    assert isinstance(node_clear_list, DraconMappingNode), (
        f"Expected inner node type DraconMappingNode, got {type(node_clear_list)}"
    )
    assert node_clear_list.tag == '!deferred::clear_ctx=VAR1,VAR2'

    # with clear_ctx bool
    deferred_clear_bool = DeferredNode(value=inner_map, clear_ctx=True)
    node_clear_bool = representer_default.represent_data(deferred_clear_bool)
    assert isinstance(node_clear_bool, DraconMappingNode), (
        f"Expected inner node type DraconMappingNode, got {type(node_clear_bool)}"
    )
    assert node_clear_bool.tag == '!deferred::clear_ctx=True'


def test_represent_interpolable_node(representer_default):
    interpolable = InterpolableNode(value="${path.to.value}", tag='!env_var')
    node = representer_default.represent_data(interpolable)
    # should just represent the scalar value and tag
    assert isinstance(node, DraconScalarNode)
    assert node.value == "${path.to.value}"
    assert node.tag == '!env_var'


def test_represent_custom_dumpable(representer_default):
    custom = CustomDump(data="test_data")
    node = representer_default.represent_data(custom)
    assert isinstance(node, DraconMappingNode)
    assert node.tag == '!CustomDump'  # tag updated
    items = {k.value: v.value for k, v in node.value}
    assert items['custom_data'] == 'test_data'


def test_represent_multiline_string(representer_default):
    multiline = "line1\nline2\n  line3"
    node = representer_default.represent_data(multiline)
    assert isinstance(node, DraconScalarNode)
    assert node.value == multiline
    assert node.style == '|'  # should default to block style


def test_round_trip_basic(representer_default):
    data = {'a': 1, 'b': [2, 3], 'c': {'d': True}}
    # use dump/loads which uses the representer internally
    loader = DraconLoader()
    # Configure the existing representer instead of replacing it
    loader.yaml.representer.full_module_path = representer_default.full_module_path
    loader.yaml.representer.exclude_defaults = representer_default.exclude_defaults

    yaml_string = dump(data, loader=loader)
    print(f"\nDumped Basic YAML:\n{yaml_string}")
    reconstructed_data = loads(yaml_string, loader=loader, raw_dict=True)  # load as raw dict

    assert data == reconstructed_data


def test_round_trip_pydantic(representer_default):
    model = NestedModel(id=1, simple=SimpleModel(name="inner", value=20))

    loader = DraconLoader(context={'NestedModel': NestedModel, 'SimpleModel': SimpleModel})
    # Configure the existing representer instead of replacing it
    loader.yaml.representer.full_module_path = representer_default.full_module_path
    loader.yaml.representer.exclude_defaults = representer_default.exclude_defaults

    yaml_string = dump(model, loader=loader)
    print(f"\nDumped Pydantic YAML:\n{yaml_string}")
    reconstructed_model = loads(yaml_string, loader=loader)

    assert isinstance(reconstructed_model, NestedModel)
    assert reconstructed_model == model


def test_round_trip_deferred(representer_default):
    inner_model = SimpleModel(name="deferred_inner")
    # representer needs context for inner type if dumping directly
    loader = DraconLoader(context={'SimpleModel': SimpleModel})
    loader.yaml.representer.full_module_path = representer_default.full_module_path
    loader.yaml.representer.exclude_defaults = representer_default.exclude_defaults

    deferred = make_deferred(inner_model, loader=loader)  # need loader for context in make_deferred
    yaml_string = dump(deferred, loader=loader)
    print(f"\nDumped Deferred YAML:\n{yaml_string}")

    reconstructed_deferred = loads(yaml_string, loader=loader)

    assert isinstance(reconstructed_deferred, DeferredNode)
    # construct the deferred node
    constructed_inner = reconstructed_deferred.construct()
    assert isinstance(constructed_inner, SimpleModel)
    assert constructed_inner == inner_model


def test_round_trip_dracon_core(representer_default):
    # test round trip with core dracon features: pydantic models and deferred nodes
    loader = DraconLoader(
        enable_interpolation=True,
        context={'SimpleModel': SimpleModel},
    )
    loader.yaml.representer.full_module_path = representer_default.full_module_path
    loader.yaml.representer.exclude_defaults = representer_default.exclude_defaults

    data = {
        'model': SimpleModel(name="test"),
        'nested': {'values': [1, 2, 3]},
        'deferred': make_deferred({'x': 10}, loader=loader),
    }

    yaml_string = dump(data, loader=loader)
    print(f"\nDumped Core YAML:\n{yaml_string}")

    reconstructed_loader = DraconLoader(
        enable_interpolation=True,
        context={'SimpleModel': SimpleModel},
    )
    reconstructed_data = loads(yaml_string, loader=reconstructed_loader)

    assert isinstance(reconstructed_data['model'], SimpleModel)
    assert reconstructed_data['model'].name == "test"
    assert reconstructed_data['nested']['values'] == [1, 2, 3]
    assert isinstance(reconstructed_data['deferred'], DeferredNode)
    reconstructed_data['deferred']._loader = reconstructed_loader
    assert reconstructed_data['deferred'].construct() == {'x': 10}
