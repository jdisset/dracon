from dracon import dump, loads
from dracon.loader import DraconLoader
from pydantic import BaseModel, PlainSerializer
from typing import Annotated, List, get_type_hints


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
    assert (
        conf
        == "!ClassC\nattr1:\n- custom_hello\n- custom_world\nattrB: !ClassB\n  attr1: hello\n  attr2: 42\n  attrA: !ClassA\n    attr3: 3.14\n"
    )


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
