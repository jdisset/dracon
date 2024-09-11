from ruamel.yaml import YAML
from enum import Enum
from ruamel.yaml.composer import Composer
from ruamel.yaml.nodes import MappingNode, SequenceNode, ScalarNode
from ruamel.yaml.nodes import ScalarNode, Node
from ruamel.yaml.tag import Tag
from ruamel.yaml.events import (
    AliasEvent,
    ScalarEvent,
    SequenceStartEvent,
    MappingStartEvent,
)
from pydantic import BaseModel
from .keypath import KeyPath, KeyPathToken, ROOTPATH, escape_keypath_part
from typing import Any, Union, Hashable
from dracon.utils import dict_like, list_like, DictLike, ListLike
from typing import Optional
from copy import deepcopy
from dracon.interpolation import LazyInterpolable, outermost_interpolation_exprs


## {{{                           --     utils     --

MERGE_TAG = Tag(suffix='tag:yaml.org,2002:merge')
STR_TAG = Tag(suffix='tag:yaml.org,2002:str')

DRACON_UNSET_VALUE = '__!DRACON_UNSET_VALUE!__'


def is_merge_key(value: str) -> bool:
    return value.startswith('<<')


def make_node(value: Any, tag=None, **kwargs) -> Node:
    if dict_like(value):
        return DraconMappingNode(
            tag, value=[(make_node(k), make_node(v)) for k, v in value.items()], **kwargs
        )
    elif list_like(value):
        return DraconSequenceNode(tag, value=[make_node(v) for v in value], **kwargs)
    else:
        return ScalarNode(tag, value, **kwargs)


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                        --     node types     --


class DraconScalarNode(ScalarNode):
    def __init__(self, value, start_mark=None, end_mark=None, tag=None, anchor=None, comment=None):
        ScalarNode.__init__(self, tag, value, start_mark, end_mark, comment=comment, anchor=anchor)


class IncludeNode(ScalarNode):
    def __init__(self, value, start_mark=None, end_mark=None, tag=None, anchor=None, comment=None):
        ScalarNode.__init__(self, tag, value, start_mark, end_mark, comment=comment, anchor=anchor)
        print(f'IncludeNode: {value}')


class MergeNode(ScalarNode):
    def __init__(self, value, start_mark=None, end_mark=None, tag=None, anchor=None, comment=None):
        self.merge_key_raw = value
        ScalarNode.__init__(
            self, STR_TAG, value, start_mark, end_mark, comment=comment, anchor=anchor
        )


class UnsetNode(ScalarNode):
    def __init__(self, start_mark=None, end_mark=None, tag=None, anchor=None, comment=None):
        ScalarNode.__init__(
            self,
            tag=STR_TAG,
            value=DRACON_UNSET_VALUE,
            start_mark=start_mark,
            end_mark=end_mark,
            comment=comment,
            anchor=anchor,
        )


class LazyInterpolableNode(ScalarNode):
    def __init__(
        self,
        value,
        start_mark=None,
        end_mark=None,
        tag=None,
        anchor=None,
        comment=None,
        init_outermost_interpolations=None,
    ):
        self.init_outermost_interpolations = init_outermost_interpolations
        ScalarNode.__init__(self, tag, value, start_mark, end_mark, comment=comment, anchor=anchor)


class DraconMappingNode(MappingNode):
    # simply keep map the keys to the nodes...
    def __init__(
        self,
        tag: Any,
        value: Any,
        start_mark: Any = None,
        end_mark: Any = None,
        flow_style: Any = None,
        comment: Any = None,
        anchor: Any = None,
    ) -> None:
        MappingNode.__init__(self, tag, value, start_mark, end_mark, flow_style, comment, anchor)
        self._recompute_map()

    def _recompute_map(self):
        self.map: dict[Hashable, int] = {}  # key -> index

        for idx, (key, value) in enumerate(self.value):
            if key.value in self.map:
                raise ValueError(f'Duplicate key: {key.value}')
            self.map[key.value] = idx

    # and implement a get[] (and set) method
    def __getitem__(self, key: Hashable) -> Node:
        if isinstance(key, Node):
            key = key.value
        return self.value[self.map[key]][1]

    def __setitem__(self, key: Hashable, value: Node):
        if isinstance(key, Node):
            keyv = key.value
        else:
            keyv = key
        if keyv in self.map:
            idx = self.map[keyv]
            realkey, _ = self.value[idx]
            self.value[idx] = (realkey, value)
        else:
            # assert isinstance(key, Node)
            self.value.append((key, value))
            self._recompute_map()

    def __delitem__(self, key: Hashable):
        if isinstance(key, Node):
            key = key.value
        idx = self.map[key]
        del self.value[idx]
        self._recompute_map()

    def __contains__(self, key: Hashable) -> bool:
        if isinstance(key, Node):
            key = key.value
        return key in self.map

    # all dict-like methods
    def keys(self):
        return self.map.keys()

    def values(self):
        return (value for key, value in self.value)

    def items(self):
        # return ((key.value, value) for key, value in self.value)
        return self.value

    def get(self, key: Hashable, default=None):
        return self[key] if key in self else default

    def get_key_node(self, key: Hashable):
        idx = self.map[key]
        return self.value[idx][0]

    def __len__(self):
        return len(self.map)

    def copy(self):
        return self.__class__(
            tag=self.tag,
            value=self.value.copy(),
            start_mark=self.start_mark,
            end_mark=self.end_mark,
            flow_style=self.flow_style,
            comment=self.comment,
            anchor=self.anchor,
        )


class DraconSequenceNode(SequenceNode):
    def __getitem__(self, index: int) -> Node:
        return self.value[index]

    def __setitem__(self, index: int, value: Node):
        self.value[index] = value

    def __delitem__(self, index: int):
        del self.value[index]

    def __add__(self, other: 'DraconSequenceNode') -> 'DraconSequenceNode':
        return self.__class__(
            tag=self.tag,
            value=self.value + other.value,
            start_mark=self.start_mark,
            end_mark=self.end_mark,
            flow_style=self.flow_style,
            comment=self.comment,
            anchor=self.anchor,
        )


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                   --     CompositionResult    --


class CompositionResult(BaseModel):
    root: Node
    include_nodes: list[KeyPath] = []  # keypaths to include nodes
    anchor_paths: dict[str, KeyPath] = {}  # anchor name -> keypath to that anchor node
    merge_nodes: list[KeyPath] = []

    def model_post_init(self, *args, **kwargs):
        super().model_post_init(*args, **kwargs)

    class Config:
        arbitrary_types_allowed = True

    def rerooted(self, new_root: KeyPath):
        new_root = new_root.simplified()
        new_root_node = new_root.get_obj(self.root)

        assert new_root_node is not None, f'Invalid new root: {new_root}'

        new_include_nodes = [
            (ROOTPATH + include_node[len(new_root) :]).simplified()
            for include_node in self.include_nodes
            if include_node.startswith(new_root)
        ]

        new_merge_nodes = [
            (ROOTPATH + merge_node[len(new_root) :]).simplified()
            for merge_node in self.merge_nodes
            if merge_node.startswith(new_root)
        ]

        new_anchor_paths = {
            anchor: (ROOTPATH + anchor_path[len(new_root) :]).simplified()
            for anchor, anchor_path in self.anchor_paths.items()
            if anchor_path.startswith(new_root)
        }

        return CompositionResult(
            root=new_root_node,
            include_nodes=new_include_nodes,
            anchor_paths=new_anchor_paths,
            merge_nodes=new_merge_nodes,
        )

    def replace_node_at(self, at_path: KeyPath, new_node: Node):
        if at_path == ROOTPATH:
            self.root = new_node
        else:
            parent_path = at_path.copy().up()
            parent_node = parent_path.get_obj(self.root)

            if isinstance(parent_node, DraconMappingNode):
                key = at_path[-1]
                parent_node[key] = new_node
            elif isinstance(parent_node, DraconSequenceNode):
                idx = int(at_path[-1])
                parent_node[idx] = new_node
            else:
                raise ValueError(f'Invalid parent node type: {type(parent_node)}')

    def replaced_at(self, at_path: KeyPath, new_root: 'CompositionResult'):
        if at_path == ROOTPATH:
            return new_root.model_copy()

        self.replace_node_at(at_path, new_root.root)

        self.include_nodes.extend(
            [
                (at_path + include_node.rootless()).simplified()
                for include_node in new_root.include_nodes
            ]
        )
        # make unique
        self.include_nodes = list(set(self.include_nodes))

        self.merge_nodes.extend(
            [(at_path + merge_node.rootless()).simplified() for merge_node in new_root.merge_nodes]
        )
        # make unique
        self.merge_nodes = list(set(self.merge_nodes))

        for anchor, anchor_path in new_root.anchor_paths.items():
            if anchor not in self.anchor_paths:
                self.anchor_paths[anchor] = (at_path + anchor_path.rootless()).simplified()

        return self

    def sort_merge_nodes(self):
        # we sort them by innermost first but keep the order of the same level
        lens = [len(m) for m in self.merge_nodes]
        self.merge_nodes = [
            m
            for _, m in sorted(
                zip(lens, self.merge_nodes),
                key=lambda x: x[0],
            )
        ]


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                      --     DraconComposer     --


class DraconComposer(Composer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.node_map: dict[KeyPath, Node] = {}  # keypath -> node
        self.include_nodes: list[KeyPath] = []  # keypaths to include nodes
        self.merge_nodes: list[KeyPath] = []  # keypaths to merge nodes
        self.anchor_paths: dict[str, KeyPath] = {}  # anchor name -> keypath to that anchor node
        self.curr_path = ROOTPATH
        self.interpolation_enabled = True
        self.merging_enabled = True

    def get_result(self) -> CompositionResult:
        return CompositionResult(
            root=self.node_map[ROOTPATH],
            include_nodes=deepcopy(self.include_nodes),
            anchor_paths=deepcopy(self.anchor_paths),
            merge_nodes=deepcopy(self.merge_nodes),
        )

    def descend_path(self, parent, index):
        assert index is not None, f'Invalid index: {index}'
        if parent is None:
            self.curr_path = ROOTPATH
        elif isinstance(parent, MappingNode):
            if isinstance(index, ScalarNode):
                self.curr_path.down(index.value)
            else:
                self.curr_path.down(str(index))
        elif isinstance(parent, SequenceNode):
            self.curr_path.down(str(index))

    def ascend_path(self, node):
        if self.curr_path:
            self.node_map[self.curr_path.copy()] = node
            self.curr_path.up()

    def compose_node(self, parent, index):
        if index is not None:
            self.descend_path(parent, index)

        if self.parser.check_event(AliasEvent):
            event = self.parser.get_event()
            node = IncludeNode(
                value=event.anchor,
                start_mark=event.start_mark,
                end_mark=event.end_mark,
            )
            self.include_nodes.append(self.curr_path.copy())
        else:
            event = self.parser.peek_event()
            anchor = event.anchor
            if anchor is not None:
                assert anchor not in self.anchor_paths, f'Anchor {anchor} already exists'
                self.anchor_paths[anchor] = self.curr_path.copy()

            self.resolver.descend_resolver(parent, index)
            if self.parser.check_event(ScalarEvent):
                if event.ctag == "!include":
                    normal_node = self.compose_scalar_node(anchor)
                    node = IncludeNode(
                        value=normal_node.value,
                        start_mark=event.start_mark,
                        end_mark=event.end_mark,
                        comment=event.comment,
                        anchor=anchor,
                    )
                    self.include_nodes.append(self.curr_path.copy())
                else:
                    # would probably be more idiomatic to write
                    # my own MergeEvent but this works the same...
                    if event.style is None and is_merge_key(event.value) and self.merging_enabled:
                        node = self.compose_merge_node(anchor)
                    else:
                        node = self.compose_scalar_node(anchor)
            elif self.parser.check_event(SequenceStartEvent):
                node = self.compose_sequence_node(anchor)
            elif self.parser.check_event(MappingStartEvent):
                node = self.compose_mapping_node(anchor)
            else:
                raise RuntimeError(f'Not a valid node event: {event}')
            self.resolver.ascend_resolver()

        node = self.wrapped_node(node)
        if index is not None:
            self.ascend_path(node)

        if parent is None:
            assert self.curr_path == ROOTPATH
            self.node_map[self.curr_path.copy()] = node

        return node

    def compose_merge_node(self, anchor: Any) -> Any:
        event = self.parser.get_event()
        tag = event.ctag
        if tag is None or str(tag) == '!':
            tag = self.resolver.resolve(ScalarNode, event.value, event.implicit)
            assert not isinstance(tag, str)
        assert is_merge_key(event.value), f'Invalidly routed to merge node: {event.value}'
        node = MergeNode(
            value=event.value,
            tag=tag,
            start_mark=event.start_mark,
            end_mark=event.end_mark,
            comment=event.comment,
            anchor=anchor,
        )
        if anchor is not None:
            self.anchors[anchor] = node
        mpath = self.curr_path.copy() + KeyPath(escape_keypath_part(event.value))
        self.merge_nodes.append(mpath)
        return node

    def wrapped_node(self, node: Node) -> Node:
        if isinstance(node, MappingNode):
            return DraconMappingNode(
                tag=node.tag,
                value=node.value,
                start_mark=node.start_mark,
                end_mark=node.end_mark,
                flow_style=node.flow_style,
                comment=node.comment,
                anchor=node.anchor,
            )
        elif isinstance(node, SequenceNode):
            return DraconSequenceNode(
                tag=node.tag,
                value=node.value,
                start_mark=node.start_mark,
                end_mark=node.end_mark,
                flow_style=node.flow_style,
                comment=node.comment,
                anchor=node.anchor,
            )
        if isinstance(node, ScalarNode):
            if node.value == DRACON_UNSET_VALUE:
                print(f'Unset node at {node.start_mark}: {node.value}')
                return UnsetNode()
            if self.interpolation_enabled:
                # check if tag can be interpolated
                tag_iexpr = outermost_interpolation_exprs(node.tag)
                value_iexpr = (
                    outermost_interpolation_exprs(node.value)
                    if isinstance(node.value, str)
                    else None
                )
                if tag_iexpr or value_iexpr:
                    return LazyInterpolableNode(
                        value=node.value,
                        start_mark=node.start_mark,
                        end_mark=node.end_mark,
                        tag=node.tag,
                        anchor=node.anchor,
                        comment=node.comment,
                        init_outermost_interpolations=value_iexpr,
                    )
            return node

        elif isinstance(node, (IncludeNode, MergeNode)):
            return node
        else:
            raise NotImplementedError(f'Node type {type(node)} not supported')


##────────────────────────────────────────────────────────────────────────────}}}


def delete_unset_nodes(comp_res: CompositionResult):
    # when we delete an unset node, we have to check if the parent is a mapping node
    # and if we just made it empty. If so, we have to replace it with an UnsetNode
    # and so on, until we reach the root

    def _delete_unset_nodes(node: Node, parent: Optional[Node], key: Optional[Hashable]) -> Node:
        if isinstance(node, DraconMappingNode):
            new_value = []
            for k, v in node.value:
                if isinstance(v, UnsetNode):
                    continue
                new_value.append((k, _delete_unset_nodes(v, node, k)))
            if not new_value and not node.tag.startswith('!'):
                return UnsetNode()
            return DraconMappingNode(
                tag=node.tag,
                value=new_value,
                start_mark=node.start_mark,
                end_mark=node.end_mark,
                flow_style=node.flow_style,
                comment=node.comment,
                anchor=node.anchor,
            )
        elif isinstance(node, DraconSequenceNode):
            new_value = []
            for v in node.value:
                if isinstance(v, UnsetNode):
                    continue
                new_value.append(_delete_unset_nodes(v, node, None))
            return DraconSequenceNode(
                tag=node.tag,
                value=new_value,
                start_mark=node.start_mark,
                end_mark=node.end_mark,
                flow_style=node.flow_style,
                comment=node.comment,
                anchor=node.anchor,
            )
        else:
            return node

    comp_res.root = _delete_unset_nodes(comp_res.root, None, None)

    return comp_res
