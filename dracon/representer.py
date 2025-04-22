# dracon/representer.py

from ruamel.yaml.representer import RoundTripRepresenter
from ruamel.yaml.nodes import MappingNode, ScalarNode, SequenceNode
from typing import Protocol
from ruamel.yaml.scalarstring import PlainScalarString
from pydantic import BaseModel
from dracon.utils import list_like, dict_like
from dracon.resolvable import Resolvable
from dracon.deferred import DeferredNode
from dracon.interpolation import InterpolableNode
from dracon.lazy import LazyInterpolable  # <<< Import LazyInterpolable
from dracon.dracontainer import Mapping as DraconMapping, Sequence as DraconSequence
from dracon.nodes import DEFAULT_MAP_TAG, DEFAULT_SEQ_TAG, DEFAULT_SCALAR_TAG
from typing import Any, Hashable, Mapping, Sequence, Union
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
        self.add_representer(DraconMapping, self.represent_dracon_mapping)
        self.add_representer(DraconSequence, self.represent_dracon_sequence)
        self.add_representer(LazyInterpolable, self.represent_lazy_interpolable)

    def represent_dracon_mapping(self, data: DraconMapping) -> MappingNode:
        return self.represent_mapping(DEFAULT_MAP_TAG, data._data)

    def represent_dracon_sequence(self, data: DraconSequence) -> SequenceNode:
        return self.represent_sequence(DEFAULT_SEQ_TAG, data._data)

    def represent_lazy_interpolable(self, data: LazyInterpolable) -> ScalarNode:
        return self.represent_scalar(DEFAULT_SCALAR_TAG, data.value)

    def represent_data(self, data: Any) -> Any:
        if isinstance(data, DraconMapping):
            return self.represent_dracon_mapping(data)
        if isinstance(data, DraconSequence):
            return self.represent_dracon_sequence(data)
        if isinstance(data, LazyInterpolable):
            return self.represent_lazy_interpolable(data)
        if isinstance(data, DraconDumpable):
            return data.dracon_dump_to_node(self)
        if isinstance(data, BaseModel):
            return self.represent_pydantic_model(data)

        return super().represent_data(data)

    def represent_pydantic_model(self, data):
        assert isinstance(data, BaseModel)

        tag = f"!{data.__class__.__name__}"
        if self.full_module_path:
            tag = f"!{data.__class__.__module__}.{data.__class__.__name__}"

        model_dump = data.model_dump(exclude_defaults=self.exclude_defaults)

        for name, attr in dict(data).items():
            if isinstance(attr, BaseModel):
                model_dump[name] = attr
            elif list_like(attr):
                for i, x in enumerate(attr):
                    if isinstance(x, BaseModel):
                        if (
                            name in model_dump
                            and isinstance(model_dump[name], list)
                            and i < len(model_dump[name])
                        ):
                            model_dump[name][i] = x
            elif dict_like(attr):
                for k, v in attr.items():
                    if isinstance(v, BaseModel):
                        if (
                            name in model_dump
                            and isinstance(model_dump[name], dict)
                            and k in model_dump[name]
                        ):
                            model_dump[name][k] = v

        node = self.represent_mapping(tag, model_dump)
        return node
