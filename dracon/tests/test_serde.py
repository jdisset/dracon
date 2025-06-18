from dracon import dump, loads
from dracon.loader import DraconLoader
from pydantic import BaseModel, PlainSerializer, GetCoreSchemaHandler
from typing import Annotated, List, get_type_hints, Any
import pytest
from dracon.nodes import ContextNode
from pydantic_core import core_schema
import gc
import sys


class ClassA(BaseModel):
    attr3: float = 0


class ClassB(BaseModel):
    attr1: str
    attr2: int
    attrA: ClassA


TypeWithSer = Annotated[
    str,
    PlainSerializer(lambda x: f'custom_{x}'),
]


def test_context_shallow_copy():
    # Create a large object that would be expensive to deepcopy
    large_data = [i for i in range(1000000)]
    initial_ref_count = sys.getrefcount(large_data)

    # Create a context with this large object
    context = {"large_data": large_data}

    # Create nodes with this context
    nodes = [ContextNode(value=f"test{i}", context=context) for i in range(10)]

    # Verify all nodes reference the same large_data object
    for node in nodes:
        assert node.context["large_data"] is large_data

    # Verify reference count increased by expected amount
    # (one for each node's context dict plus other references from the test)
    expected_increase = len(nodes)
    assert sys.getrefcount(large_data) <= initial_ref_count + expected_increase + 3

    # Copy a node and verify the large data is not duplicated
    copied_node = nodes[0].copy()
    assert copied_node.context["large_data"] is large_data


class ClassC(BaseModel):
    attr1: List[TypeWithSer]
    attrB: ClassB


def test_simple():
    conf = """
        !ClassB
        attr1: hello
        attr2: 42
        attrA: !ClassA
            attr3: 3.14
    """

    loader = DraconLoader(context={"ClassA": ClassA, "ClassB": ClassB})
    loader.yaml.representer.full_module_path = False

    obj = loader.loads(conf)
    assert isinstance(obj, ClassB)
    assert obj.attr1 == "hello"
    assert obj.attr2 == 42
    assert isinstance(obj.attrA, ClassA)
    assert obj.attrA.attr3 == 3.14


def test_dump():
    loader = DraconLoader()
    loader.yaml.representer.full_module_path = False
    obj = ClassB(attr1="hello", attr2=42, attrA=ClassA(attr3=3.14))
    conf = loader.dump(obj)
    assert conf == "!ClassB\nattr1: hello\nattr2: 42\nattrA: !ClassA\n  attr3: 3.14\n"


def test_complex():
    a = ClassA(attr3=3.14)
    b = ClassB(attr1="hello", attr2=42, attrA=a)
    c = ClassC(attr1=["hello", "world"], attrB=b)

    loader = DraconLoader(context={"ClassA": ClassA, "ClassB": ClassB, "ClassC": ClassC})
    loader.yaml.representer.full_module_path = False
    conf = loader.dump(c)
    print(f"actual conf:\n{conf}")

    expected = "!ClassC\nattr1:\n- custom_hello\n- custom_world\nattrB: !ClassB\n  attr1: hello\n  attr2: 42\n  attrA: !ClassA\n    attr3: 3.14\n"

    print(f"expected:\n{expected}")

    assert conf == expected


class ClassEx(BaseModel):
    attr: float = 0


def test_empty():
    conf = """
        emptyd: !ClassEx {}
        """
    loader = DraconLoader(context={"ClassEx": ClassEx})
    loader.yaml.representer.full_module_path = False
    obj = loader.loads(conf)
    assert isinstance(obj.emptyd, ClassEx)
    assert obj.emptyd.attr == 0


class Regex(str):
    """A string that should be treated as a regex pattern."""

    @classmethod
    def __get_pydantic_core_schema__(
        cls, _source_type: Any, _handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.union_schema(
            [
                core_schema.is_instance_schema(cls),
                core_schema.chain_schema(
                    [
                        core_schema.str_schema(),
                        core_schema.no_info_plain_validator_function(cls),
                    ]
                ),
            ]
        )

    def __new__(cls, string):
        return super().__new__(cls, string)


class RegexModel(BaseModel):
    pattern: Regex


def test_regex_dracon_representation():
    """Test that Regex class can be represented by dracon and dumped as strings."""
    model = RegexModel(pattern=Regex(r"\d+"))
    
    assert isinstance(model.pattern, Regex)
    assert str(model.pattern) == r"\d+"
    
    loader = DraconLoader()
    loader.yaml.representer.full_module_path = False
    
    yaml_output = loader.dump(model)
    assert r"\d+" in yaml_output
    assert "!RegexModel" in yaml_output
    
    loader.context.update({"RegexModel": RegexModel, "Regex": Regex})
    loaded_model = loader.loads(yaml_output)
    
    assert isinstance(loaded_model, RegexModel)
    assert isinstance(loaded_model.pattern, Regex)
    assert str(loaded_model.pattern) == r"\d+"


def test_regex_yaml_roundtrip():
    """Test that Regex instances can be dumped as strings and loaded back."""
    loader = DraconLoader()
    loader.yaml.representer.full_module_path = False
    loader.context.update({"RegexModel": RegexModel, "Regex": Regex})
    
    original_model = RegexModel(pattern=Regex(r"[a-zA-Z]+"))
    yaml_str = loader.dump(original_model)
    
    assert "[a-zA-Z]+" in yaml_str
    assert "pattern: !Regex" not in yaml_str  # pattern should not have Regex constructor tag
    
    loaded_model = loader.loads(yaml_str)
    assert isinstance(loaded_model.pattern, Regex)
    assert str(loaded_model.pattern) == r"[a-zA-Z]+"
