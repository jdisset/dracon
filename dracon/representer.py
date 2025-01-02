from ruamel.yaml.representer import RoundTripRepresenter
from ruamel.yaml.nodes import MappingNode, ScalarNode
from typing import Protocol
from ruamel.yaml.scalarstring import PlainScalarString
from pydantic import BaseModel
from dracon.utils import list_like, dict_like
from dracon.resolvable import Resolvable
from dracon.deferred import DeferredNode
from dracon.interpolation import InterpolableNode
from typing import Any, Hashable, Mapping, Sequence, Union
from typing_extensions import runtime_checkable

import numpy as np


# protocol to identify classes that have a dracon_dump method
@runtime_checkable
class DraconDumpable(Protocol):
    def dracon_dump_to_node(self, representer): ...


#
# class DraconRepresenter(RoundTripRepresenter):
#     def __init__(self, *args, full_module_path=True, exclude_defaults=True, **kwargs):
#         super().__init__(*args, **kwargs)
#         self.full_module_path = full_module_path
#         self.exclude_defaults = exclude_defaults
#         self.represented_objects = {}
#
#     def represent_data(self, data: Any) -> Any:
#         if id(data) in self.represented_objects:
#             return self.represented_objects[id(data)]
#
#         if hasattr(data, 'tag') and isinstance(data.tag, str) and data.tag.startswith('!'):
#             # For nodes with tags, we want to preserve their original tag
#             node = self.represent_mapping(data.tag, data)
#             self.represented_objects[id(data)] = node
#             return node
#
#         if isinstance(data, DeferredNode):
#             return data.dracon_dump_to_node(self)
#
#         # if isinstance(data, InterpolableNode):
#         #     # Create a scalar node with the interpolation expression
#         #     node = self.represent_scalar('tag:yaml.org,2002:str', data.value)
#         #     if data.init_outermost_interpolations:
#         #         # Mark that this is an interpolation node
#         #         node.tag = '!interpolation'
#         #     self.represented_objects[id(data)] = node
#         #     return node
#
#         if isinstance(data, DraconDumpable):
#             node = data.dracon_dump_to_node(self)
#             self.represented_objects[id(data)] = node
#             return node
#
#         if isinstance(data, BaseModel):
#             node = self.represent_pydantic_model(data)
#             self.represented_objects[id(data)] = node
#             return node
#
#         if isinstance(data, Sequence) and not isinstance(data, str):
#             node = self.represent_list(data)
#             self.represented_objects[id(data)] = node
#             return node
#
#         try:
#             node = super().represent_data(data)
#             self.represented_objects[id(data)] = node
#             return node
#         except:
#             # If all else fails, convert to string
#             return self.represent_scalar('tag:yaml.org,2002:str', str(data))
#
#     def represent_pydantic_model(self, data):
#         assert isinstance(data, BaseModel)
#
#         tag = f"!{data.__class__.__name__}"
#         if self.full_module_path:
#             tag = f"!{data.__class__.__module__}.{data.__class__.__name__}"
#
#         model_dump = data.model_dump(exclude_defaults=self.exclude_defaults)
#
#         # we dump the object using the model_dump method
#         # (which uses the preferred aliases and serializations)
#         # EXCEPT for the fields that are BaseModel instances
#         # where we recursively call this method instead
#         for name, attr in dict(data).items():
#             if isinstance(attr, BaseModel):
#                 model_dump[name] = attr
#             elif list_like(attr):
#                 for i, x in enumerate(attr):
#                     if isinstance(x, BaseModel):
#                         model_dump[name][i] = x
#             elif dict_like(attr):
#                 for k, v in attr.items():
#                     if isinstance(v, BaseModel):
#                         model_dump[name][k] = v
#
#         node = self.represent_mapping(tag, model_dump)
#         return node


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
        if isinstance(data, BaseModel):
            return self.represent_pydantic_model(data)
        if isinstance(data, Sequence) and not isinstance(data, str):
            return self.represent_list(data)

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


# TODO:
# - [ ] make keypaths regex to specify which keys are deferred
# -
