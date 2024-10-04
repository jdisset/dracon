## {{{                          --     imports     --
import re
import pytest
from dracon import dump, loads
from dracon.loader import DraconLoader
from dracon.deferred import DeferredNode
from dracon.dracontainer import Dracontainer, Mapping, Sequence
from dracon.interpolation import InterpolationError, InterpolationMatch
from typing import Generic, TypeVar, Any, Optional, Annotated, cast, List
from pydantic import (
    BaseModel,
    field_validator,
    BeforeValidator,
    WrapValidator,
    AfterValidator,
    ConfigDict,
    Field,
)

from dracon.interpolation import outermost_interpolation_exprs
from dracon.lazy import LazyInterpolable

from pydantic.dataclasses import dataclass
from dracon.keypath import KeyPath
from typing import Any, Dict, Callable, Optional, Tuple, List
import copy
from dracon.interpolation_utils import find_field_references
from asteval import Interpreter
##────────────────────────────────────────────────────────────────────────────}}}


class ClassA(BaseModel):
    index: int
    name: str = ''

    @property
    def name_index(self):
        return f"{self.index}: {self.name}"


def test_deferred():
    yaml_content = """
    !define i42 : !int 42

    a_obj: !ClassA
        index: &aid ${i42}
        name: oldname
        <<{<+}: 
            name: "new_name ${&aid}"

    nested: !deferred
        !define aid: ${get_index(construct(&/a_obj))}
        a_index: ${aid}
        aname: ${&/a_obj.name}
        constructed_nameindex: ${construct(&/a_obj).name_index}

    """

    loader = DraconLoader(enable_interpolation=True, context={'ClassA': ClassA})
    loader.yaml.representer.full_module_path = False
    loader.context['get_index'] = lambda obj: obj.index
    config = loader.loads(yaml_content)
    config.resolve_all_lazy()

    assert isinstance(config.a_obj, ClassA)
    assert config['a_obj'].index == 42
    assert config['a_obj'].name == "new_name 42"

    assert type(config['nested']) is DeferredNode

    nested_comp = config.nested.compose()
    nested = config.nested.construct()

    assert nested.a_index == 42
    assert nested.aname == "new_name 42"
    assert nested.constructed_nameindex == "42: new_name 42"


def test_deferred_explicit():
    yaml_content = """
    !define i42 : !int 42

    a_obj: !ClassA &ao
        index: &aid ${i42}
        name: oldname
        <<{<+}: 
            name: "new_name ${&aid}"


    b_obj: !deferred:ClassA &bo
        index: &bid ${int(i42) - 10}
        name: oldname
        <<{<+}: 
            name: "new_name ${&bid}"

    nested:
        !define aid: ${get_index(construct(&/a_obj)) + $CONSTANT}
        a_index: ${aid}
        aname: ${&/a_obj.name}
        constructed_nameindex: ${construct(&/a_obj).name_index}
        !define ao: ${&/a_obj}
        !define bo: ${&/b_obj} # required to go through a reference when pointing to a deferred node
        obj2:
            <<: !include ao
        obj3: !include $ao
        obj4: !include $bo
            

    """

    loader = DraconLoader(
        enable_interpolation=True, context={'ClassA': ClassA}, deferred_paths=['/nested']
    )
    loader.yaml.representer.full_module_path = False
    config = loader.loads(yaml_content)
    config.resolve_all_lazy()

    assert isinstance(config.a_obj, ClassA)
    assert config['a_obj'].index == 42
    assert config['a_obj'].name == "new_name 42"

    assert type(config['nested']) is DeferredNode

    config.nested.update_context({'get_index': lambda obj: obj.index, '$CONSTANT': 10})
    nested = config.nested.construct()

    assert nested.a_index == 52
    assert nested.aname == "new_name 42"
    assert nested.constructed_nameindex == "42: new_name 42"

    assert isinstance(config.b_obj, DeferredNode)
    b_obj = config.b_obj.construct()
    assert isinstance(b_obj, ClassA)
    assert b_obj.index == 32
    assert b_obj.name == "new_name 32"

    assert nested.obj2 == config.a_obj
    assert nested.obj3 == config.a_obj
    assert isinstance(nested.obj4, DeferredNode)
    assert nested.obj4.construct() == b_obj

def test_deferred_multiple():
    from pydantic import BaseModel

