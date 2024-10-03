from ruamel.yaml.representer import RoundTripRepresenter
from ruamel.yaml.nodes import MappingNode, ScalarNode
from typing import Protocol
from ruamel.yaml.scalarstring import PlainScalarString
from pydantic import BaseModel
from dracon.utils import list_like, dict_like
from dracon.resolvable import Resolvable
from typing import Any, Hashable, Mapping
from typing_extensions import runtime_checkable

import numpy as np


# protocol to identify classes that have a dracon_dump method
@runtime_checkable
class DraconDumpable(Protocol):
    def dracon_dump_to_node(self, representer): ...


class DraconRepresenter(RoundTripRepresenter):
    def __init__(self, *args, full_module_path=True, exclude_defaults=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.full_module_path = (
            full_module_path  # if True, the full module path will be used as the tag
        )
        self.exclude_defaults = exclude_defaults

    def represent_data(self, data: Any) -> Any:
        if isinstance(data, DraconDumpable):
            return data.dracon_dump_to_node(self)
        return super().represent_data(data)


def represent_pydantic_model(self, data):
    assert isinstance(data, BaseModel)

    tag = f"!{data.__class__.__name__}"
    if self.full_module_path:
        tag = f"!{data.__class__.__module__}.{data.__class__.__name__}"

    model_dump = data.model_dump(exclude_defaults=self.exclude_defaults)

    # we dump the object using the model_dump method
    # (which uses the preffered aliases and serializations)
    # EXCEPT for the fields that are BaseModel instances
    # where we recursively call this method instead

    for name, attr in dict(data).items():
        if isinstance(attr, BaseModel):
            model_dump[name] = attr
        elif list_like(attr):
            for i, x in enumerate(attr):
                if isinstance(x, BaseModel):
                    model_dump[name][i] = x
        elif dict_like(attr):
            for k, v in attr.items():
                if isinstance(v, BaseModel):
                    model_dump[name][k] = v

    node = self.represent_mapping(tag, model_dump)
    return node


DraconRepresenter.add_multi_representer(BaseModel, represent_pydantic_model)

# TODO:
# - [ ] make keypaths regex to specify which keys are deferred
# - 
