# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

from ruamel.yaml.representer import RoundTripRepresenter, RepresenterError
from ruamel.yaml.nodes import MappingNode, ScalarNode, SequenceNode, Node
from ruamel.yaml.tag import Tag
from pydantic import BaseModel
from dracon.utils import make_hashable
from dracon.resolvable import Resolvable
from dracon.deferred import DeferredNode
from dracon.interpolation import InterpolableNode
from dracon.trace import ftrace
from dracon.lazy import LazyInterpolable
from dracon.dracontainer import Mapping as DraconMapping, Sequence as DraconSequence
from dracon.nodes import (
    DEFAULT_MAP_TAG,
    DEFAULT_SEQ_TAG,
    DEFAULT_SCALAR_TAG,
    DraconMappingNode,
    DraconSequenceNode,
    DraconScalarNode,
)
from typing import Any
from typing_extensions import runtime_checkable, Protocol
import logging

logger = logging.getLogger(__name__)


@runtime_checkable
class DraconDumpable(Protocol):
    def dracon_dump_to_node(self, representer): ...


class DraconRepresenter(RoundTripRepresenter):
    def __init__(self, *args, full_module_path=True, exclude_defaults=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.full_module_path = full_module_path
        self.exclude_defaults = exclude_defaults

    def _get_pydantic_tag(self, data: BaseModel) -> str:
        """Generates the YAML tag for a Pydantic model."""
        cls = data.__class__
        if self.full_module_path:
            return f"!{cls.__module__}.{cls.__name__}"
        else:
            return f"!{cls.__name__}"

    def _get_deferred_tag(self, data: DeferredNode, inner_node_tag: str) -> str:
        """Generates the YAML tag for a DeferredNode."""
        deferred_tag_base = '!deferred'
        original_tag_suffix = ''

        # get original tag (could be from inner node or explicitly set on deferred)
        original_tag = getattr(data.value, 'tag', None) or inner_node_tag
        if (
            original_tag
            and original_tag not in (DEFAULT_MAP_TAG, DEFAULT_SEQ_TAG, DEFAULT_SCALAR_TAG, '!')
            and not original_tag.startswith('!deferred')
        ):
            original_tag_suffix = original_tag[1:] if original_tag.startswith('!') else original_tag

        clear_ctx_suffix = ''
        clear_ctx_val = getattr(data, '_original_clear_ctx', None)
        if clear_ctx_val is True:
            clear_ctx_suffix = '::clear_ctx=True'
        elif isinstance(clear_ctx_val, list) and clear_ctx_val:
            clear_ctx_suffix = f'::clear_ctx={",".join(clear_ctx_val)}'

        final_tag = deferred_tag_base
        if original_tag_suffix:
            final_tag += f':{original_tag_suffix}'
        final_tag += clear_ctx_suffix
        return final_tag

    # --- representers for specific types ---

    def represent_str(self, data: str) -> Node:
        # explicitly handle strings to control style
        style = '|' if '\n' in data else None
        return self.represent_scalar('tag:yaml.org,2002:str', data, style=style)

    def represent_dracon_mapping(self, data: DraconMapping) -> Node:
        return self.represent_mapping(DEFAULT_MAP_TAG, data._data)

    def represent_dracon_sequence(self, data: DraconSequence) -> Node:
        return self.represent_sequence(DEFAULT_SEQ_TAG, data._data)

    def represent_lazy_interpolable(self, data: LazyInterpolable) -> Node:
        # return an InterpolableNode instance
        return InterpolableNode(
            value=str(data.value),
            context=data.context,
            tag=DEFAULT_SCALAR_TAG,
            init_outermost_interpolations=data.init_outermost_interpolations,
        )

    def represent_interpolable_node(self, data: InterpolableNode) -> Node:
        # represent as a simple scalar with its tag and value
        return self.represent_scalar(data.tag, data.value, anchor=data.anchor)

    def represent_resolvable(self, data: Resolvable) -> Node:
        # represent the inner node directly, or null if empty
        if data.node is None:
            return self.represent_scalar('tag:yaml.org,2002:null', '')
        return self.represent_data(data.node)

    def represent_deferred_node(self, data: DeferredNode) -> Node:
        # represent the inner value node first
        node = self.represent_data(data.value)
        # calculate and set the specific deferred tag
        node.tag = self._get_deferred_tag(data, node.tag)
        return node

    # --- representers for multi types (protocols/subclasses) ---

    def represent_dracon_dumpable(self, data: DraconDumpable) -> Node:
        return data.dracon_dump_to_node(self)

    def represent_pydantic_model(self, data: BaseModel) -> Node:
        tag = self._get_pydantic_tag(data)

        # get serialized values to respect serializers and exclusion rules
        dump_dict = data.model_dump(mode='python', exclude_unset=self.exclude_defaults)

        mapping_value_pairs = []
        for field_name, serialized_value in dump_dict.items():
            # represent the key
            node_key = self.represent_data(field_name)

            # decide whether to represent the original or serialized value
            original_value = getattr(data, field_name)
            value_to_represent = (
                original_value if isinstance(original_value, BaseModel) else serialized_value
            )
            node_value = self.represent_data(value_to_represent)
            mapping_value_pairs.append((node_key, node_value))

        flow_style = self.default_flow_style  # can be None
        node = self.represent_mapping(tag, mapping_value_pairs, flow_style=flow_style)
        return node

    # --- override base representers to return dracon nodes ---

    def represent_scalar(
        self, tag: Any, value: Any, style: Any = None, anchor: Any = None
    ) -> DraconScalarNode:
        final_style = style if style is not None else self.default_style
        tag_str = str(tag) if isinstance(tag, Tag) else tag
        node = DraconScalarNode(tag_str, value, style=final_style, anchor=anchor)
        if self.alias_key is not None:
            self.represented_objects[make_hashable(self.alias_key)] = node
        return node

    def represent_sequence(
        self, tag: Any, sequence: Any, flow_style: Any = None, anchor: Any = None
    ) -> DraconSequenceNode:
        value = []
        tag_str = str(tag) if isinstance(tag, Tag) else tag
        node = DraconSequenceNode(tag_str, value, flow_style=flow_style, anchor=anchor)
        if self.alias_key is not None:
            self.represented_objects[make_hashable(self.alias_key)] = node
        best_style = True
        for item in sequence:
            node_item = self.represent_data(item)
            if not (isinstance(node_item, ScalarNode) and not node_item.style):
                best_style = False
            value.append(node_item)
        if flow_style is None:
            node.flow_style = (
                self.default_flow_style if self.default_flow_style is not None else best_style
            )
        return node

    def represent_mapping(
        self, tag: Any, mapping: Any, flow_style: Any = None, anchor: Any = None
    ) -> DraconMappingNode:
        value = []
        tag_str = str(tag) if isinstance(tag, Tag) else tag
        node = DraconMappingNode(tag_str, value, flow_style=flow_style, anchor=anchor)
        if self.alias_key is not None:
            self.represented_objects[make_hashable(self.alias_key)] = node
        best_style = True

        items_to_represent = []
        if hasattr(mapping, 'items'):
            items_to_represent = list(mapping.items())
        elif isinstance(mapping, list) and all(
            isinstance(item, tuple) and len(item) == 2 for item in mapping
        ):
            items_to_represent = mapping
        else:
            raise RepresenterError(f"cannot represent mapping-like object of type {type(mapping)}")

        for item_key, item_value in items_to_represent:
            node_key = self.represent_data(item_key)
            node_value = self.represent_data(item_value)
            if not (isinstance(node_key, ScalarNode) and not node_key.style):
                best_style = False
            if not (isinstance(node_value, ScalarNode) and not node_value.style):
                best_style = False
            value.append((node_key, node_value))

        if flow_style is None:
            node.flow_style = (
                self.default_flow_style if self.default_flow_style is not None else best_style
            )
        return node

    # --- main dispatch method ---

    @ftrace(watch=[])
    def represent_data(self, data: Any) -> Node:
        # handle aliasing first
        alias_key = None
        hashable_data_key = make_hashable(data)
        is_aliasable = hashable_data_key is not None
        if is_aliasable and not self.ignore_aliases(data):
            alias_key = id(data)
            if alias_key in self.represented_objects:
                return self.represented_objects[alias_key]
            self.object_keeper.append(data)
            self.alias_key = alias_key

        node = None
        try:
            # check if data is already a suitable node (excluding types handled by specific representers)
            if isinstance(
                data, (DraconScalarNode, DraconMappingNode, DraconSequenceNode)
            ) and not isinstance(data, (DeferredNode, InterpolableNode)):
                node = data
            else:
                # find the appropriate representer function
                data_type = type(data)
                representer_func = self.yaml_representers.get(data_type)
                if not representer_func:
                    # check representers in MRO (both regular and multi representers)
                    for cls in data_type.__mro__:
                        if cls in self.yaml_representers:
                            representer_func = self.yaml_representers[cls]
                            break
                        elif cls in self.yaml_multi_representers:
                            representer_func = self.yaml_multi_representers[cls]
                            break
                    if not representer_func:
                        for reg_type, func in self.yaml_multi_representers.items():
                            if (
                                isinstance(reg_type, type)
                                and hasattr(reg_type, '_is_protocol')
                                and isinstance(data, reg_type)
                            ):
                                representer_func = func
                                break

                if representer_func:
                    node = representer_func(self, data)
                else:
                    # fallback to ruamel's default dispatch
                    logger.debug(
                        f"no specific representer found, using super().represent_data for {data_type}"
                    )
                    node = super().represent_data(data)

                    # wrap the result from super() if needed
                    if isinstance(node, ScalarNode) and not isinstance(node, DraconScalarNode):
                        node = DraconScalarNode(
                            node.tag,
                            node.value,
                            style=node.style,
                            anchor=node.anchor,
                            comment=node.comment,
                        )
                    elif isinstance(node, SequenceNode) and not isinstance(
                        node, DraconSequenceNode
                    ):
                        node = DraconSequenceNode(
                            node.tag,
                            node.value,
                            flow_style=node.flow_style,
                            anchor=node.anchor,
                            comment=node.comment,
                        )
                    elif isinstance(node, MappingNode) and not isinstance(node, DraconMappingNode):
                        node = DraconMappingNode(
                            node.tag,
                            node.value,
                            flow_style=node.flow_style,
                            anchor=node.anchor,
                            comment=node.comment,
                        )

        except Exception as e:  # catch representation errors
            logger.error(
                f"error representing {type(data)}: {str(data)[:100]}... error: {e}", exc_info=True
            )
            node = self.represent_scalar(
                DEFAULT_SCALAR_TAG, f"<error representing {type(data).__name__}>"
            )
        finally:
            # store represented node for aliasing
            if alias_key is not None:
                if node is not None:
                    self.represented_objects[alias_key] = node
                self.alias_key = None

        if node is None:
            raise RepresenterError(f"representer failed to produce a node for data: {data!r}")

        if not isinstance(node, (DraconScalarNode, DraconMappingNode, DraconSequenceNode)):
            raise RepresenterError(f"Final node is not a DraconNode subtype: {type(node)}")

        return node


# register representers at the class level
DraconRepresenter.add_representer(str, DraconRepresenter.represent_str)
DraconRepresenter.add_representer(DraconMapping, DraconRepresenter.represent_dracon_mapping)
DraconRepresenter.add_representer(DraconSequence, DraconRepresenter.represent_dracon_sequence)
DraconRepresenter.add_representer(LazyInterpolable, DraconRepresenter.represent_lazy_interpolable)
DraconRepresenter.add_representer(Resolvable, DraconRepresenter.represent_resolvable)
DraconRepresenter.add_representer(DeferredNode, DraconRepresenter.represent_deferred_node)
DraconRepresenter.add_representer(InterpolableNode, DraconRepresenter.represent_interpolable_node)

DraconRepresenter.add_multi_representer(DraconDumpable, DraconRepresenter.represent_dracon_dumpable)
DraconRepresenter.add_multi_representer(BaseModel, DraconRepresenter.represent_pydantic_model)
