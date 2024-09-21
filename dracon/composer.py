## {{{                          --     imports     --
from ruamel.yaml.composer import Composer
from ruamel.yaml.nodes import Node, MappingNode, SequenceNode, ScalarNode

from dracon.nodes import (
    DraconMappingNode,
    DraconSequenceNode,
    InterpolableNode,
    IncludeNode,
    MergeNode,
    UnsetNode,
    DRACON_UNSET_VALUE,
)

from ruamel.yaml.events import (
    AliasEvent,
    ScalarEvent,
    SequenceStartEvent,
    MappingStartEvent,
)

from pydantic import BaseModel
from .keypath import KeyPath, ROOTPATH, escape_keypath_part
from typing import Any, Hashable, Callable
from typing import Optional, List, Literal, Final
from copy import deepcopy
from dracon.utils import outermost_interpolation_exprs
##────────────────────────────────────────────────────────────────────────────}}}

## {{{                   --     CompositionResult    --

SpecialNodeCategory = Literal['include', 'merge']
INCLUDENODE: Final = 'include'
MERGENODE: Final = 'merge'


class CompositionResult(BaseModel):
    root: Node
    special_nodes: dict[Literal['include', 'merge'], list[KeyPath]] = {}
    anchor_paths: dict[str, KeyPath] = {}

    def model_post_init(self, *args, **kwargs):
        super().model_post_init(*args, **kwargs)
        # Ensure special_nodes has default lists for known categories
        self.special_nodes.setdefault(INCLUDENODE, [])
        self.special_nodes.setdefault(MERGENODE, [])

    def rerooted(self, new_root: KeyPath):
        new_root = new_root.simplified()
        new_root_node = new_root.get_obj(self.root)
        assert new_root_node is not None, f'Invalid new root: {new_root}'

        new_special_nodes = {}
        for category, paths in self.special_nodes.items():
            new_paths = [
                (ROOTPATH + path[len(new_root) :]).simplified()
                for path in paths
                if path.startswith(new_root)
            ]
            if new_paths:
                new_special_nodes[category] = new_paths

        new_anchor_paths = {
            anchor: (ROOTPATH + path[len(new_root) :]).simplified()
            for anchor, path in self.anchor_paths.items()
            if path.startswith(new_root)
        }

        return CompositionResult(
            root=new_root_node,
            special_nodes=new_special_nodes,
            anchor_paths=new_anchor_paths,
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

        for category, paths in new_root.special_nodes.items():
            existing_paths = self.special_nodes.setdefault(category, [])
            existing_paths.extend([(at_path + path.rootless()).simplified() for path in paths])
            # Remove duplicates
            self.special_nodes[category] = list(set(existing_paths))

        for anchor, anchor_path in new_root.anchor_paths.items():
            if anchor not in self.anchor_paths:
                self.anchor_paths[anchor] = (at_path + anchor_path.rootless()).simplified()

        return self

    def pop_all_special(self, category: SpecialNodeCategory):
        while self.special_nodes.get(category):
            yield self.special_nodes[category].pop()

    def sort_special_nodes(self, category: SpecialNodeCategory):
        nodes = self.special_nodes.get(category, [])
        self.special_nodes[category] = sorted(nodes, key=len)

    def walk(
        self,
        callback: Callable[[Node, KeyPath], None],
        start_path: KeyPath = ROOTPATH,
    ):
        def walk_node(node, path):
            callback(node, path)
            if isinstance(node, DraconMappingNode):
                for k_node, v_node in node.value:
                    walk_node(k_node, path)
                    walk_node(v_node, path + k_node.value)
            elif isinstance(node, DraconSequenceNode):
                for i, v in enumerate(node.value):
                    walk_node(v, path + str(i))

        walk_node(self.root, start_path)

    class Config:
        arbitrary_types_allowed = True

##────────────────────────────────────────────────────────────────────────────}}}

## {{{                      --     DraconComposer     --


class DraconComposer(Composer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.node_map: dict[KeyPath, Node] = {}  # keypath -> node
        self.special_nodes: dict[str, list[KeyPath]] = {}
        self.anchor_paths: dict[str, KeyPath] = {}
        self.curr_path = ROOTPATH
        self.interpolation_enabled = True
        self.merging_enabled = True

    def get_result(self) -> CompositionResult:
        if self.node_map:
            root_node = self.node_map[ROOTPATH]
        else:
            # create an empty root node
            root_node = DraconMappingNode(value=[], tag='')

        return CompositionResult(
            root=root_node,
            special_nodes=self.special_nodes,
            anchor_paths=self.anchor_paths,
        )

    def add_special_node(self, category: str, path: KeyPath):
        if category not in self.special_nodes:
            self.special_nodes[category] = []
        self.special_nodes[category].append(path.copy())

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
            self.add_special_node(INCLUDENODE, self.curr_path.copy())
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
                    self.add_special_node(INCLUDENODE, self.curr_path.copy())
                else:
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

    # Rest of the class remains the same
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
        self.add_special_node(MERGENODE, mpath)
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
                    return InterpolableNode(
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

## {{{                           --     utils     --


def is_merge_key(value: str) -> bool:
    return value.startswith('<<')


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


##────────────────────────────────────────────────────────────────────────────}}}
