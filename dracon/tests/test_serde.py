from dracon import *
from pydantic import BaseModel


class MyClass(BaseModel):
    attr1: str
    attr2: int


def test_simple():
    conf = """
        !MyClass
        attr1: hello
        attr2: 42
    """

    obj = loads(conf)
    assert isinstance(obj, MyClass)
    assert obj.attr1 == "hello"
    assert obj.attr2 == 42


def test_dump():
    obj = MyClass(attr1="hello", attr2=42)
    conf = dump(obj)
    assert conf == "!MyClass\nattr1: hello\nattr2: 42\n"
