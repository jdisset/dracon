## {{{                          --     imports     --
import re
import pytest
from dracon import dump, loads
from dracon.loader import DraconLoader
from dracon.nodes import DeferredNode
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

    loader = DraconLoader(enable_interpolation=True, custom_types={'ClassA': ClassA})
    loader.yaml.representer.full_module_path = False
    loader.context['func'] = lambda x, y: x + y
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
