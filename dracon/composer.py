## {{{                          --     imports     --{{{}}}
from ruamel.yaml.composer import Composer
from ruamel.yaml.nodes import Node, MappingNode, SequenceNode, ScalarNode

from dracon.utils import ftrace, deepcopy
from dracon.nodes import (
    DraconScalarNode,
    DraconMappingNode,
    DraconSequenceNode,
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

from dracon.keypath import KeyPath, ROOTPATH, MAPPING_KEY
from pydantic import BaseModel, ConfigDict
from typing import Any, Hashable, Callable
from typing import Optional, List, Literal, Final

from dracon.interpolation import InterpolableNode
from dracon.interpolation_utils import outermost_interpolation_exprs
##────────────────────────────────────────────────────────────────────────────}}}

## {{{                   --     CompositionResult    --

SpecialNodeCategory = Literal['include', 'merge', 'instruction', 'interpolable']
INCLUDENODE: Final = 'include'
MERGENODE: Final = 'merge'
INTERPOLABLE: Final = 'interpolable'
INSTRUCTION: Final = 'instruction'

INCLUDE_TAG = '!include'


class CompositionResult(BaseModel):
    root: Node
    special_nodes: dict[SpecialNodeCategory, list[KeyPath]] = {}
    anchor_paths: Optional[dict[str, KeyPath]] = None
    node_map: Optional[dict[KeyPath, Node]] = None
    # parent_path: KeyPath = ROOTPATH

    def __deepcopy__(self, memo=None):
        cr = CompositionResult(
            root=deepcopy(self.root, memo),
            special_nodes={},
            anchor_paths=deepcopy(self.anchor_paths, memo),
        )
        cr.make_map()
        return cr

    def __hash__(self):
        return hash(self.root)

    def model_post_init(self, *args, **kwargs):
        super().model_post_init(*args, **kwargs)
        for category in SpecialNodeCategory.__args__:
            self.special_nodes.setdefault(category, [])
        if self.node_map is None:
            self.make_map()
        if self.anchor_paths is None:
            self.find_anchors()

    def make_map(self):
        self.node_map = {}

        def _callback(node, path):
            self.node_map[path] = node  # type: ignore

        walk_node(self.root, _callback, start_path=ROOTPATH)

    def update_paths(self):
        assert self.node_map is not None
        for path, node in self.node_map.items():
            if hasattr(node, 'path'):
                node.path = path  # type: ignore

    def rerooted(self, new_root_path: KeyPath):
        return CompositionResult(root=new_root_path.get_obj(self.root))

    def set_at(self, at_path: KeyPath, new_node: Node):
        if at_path == ROOTPATH:
            self.root = new_node
        else:
            parent_node = at_path.parent.get_obj(self.root)

            if isinstance(parent_node, DraconMappingNode):
                key = at_path[-1]
                parent_node[key] = new_node
            elif isinstance(parent_node, DraconSequenceNode):
                idx = int(at_path[-1])  # type: ignore
                parent_node[idx] = new_node
            else:
                raise ValueError(f'Invalid parent node type: {type(parent_node)}')
        self.update_map_at(at_path)

    def update_map_at(self, at_path: KeyPath):
        if self.node_map is None:
            self.node_map = {}
        node = at_path.get_obj(self.root)
        self.node_map[at_path] = node

        def _callback(node, path):
            assert self.node_map is not None
            self.node_map[path] = node

        walk_node(node, _callback, start_path=at_path)

    def merge_composition_at(self, at_path: KeyPath, new_comp: 'CompositionResult', reuse_map=True):
        # new_comp.parent_path = self.parent_path + at_path[1:]
        new_node = new_comp.root
        self.set_at(at_path, new_node)
        # if reuse_map:
        # for path, node in new_comp.node_map.items():
        # self.node_map[at_path + path] = node

    def pop_all_special(self, category: SpecialNodeCategory):
        while self.special_nodes.get(category):
            yield self.special_nodes[category].pop()

    def sort_special_nodes(self, category: SpecialNodeCategory, reverse=False):
        nodes = self.special_nodes.get(category, [])
        self.special_nodes[category] = sorted(nodes, key=len, reverse=reverse)

    def walk_no_path(
        self,
        callback: Callable[[Node], None],
    ):
        assert self.node_map is not None
        for _, node in self.node_map.items():
            callback(node)

    def walk(
        self,
        callback: Callable[[Node, KeyPath], None],
    ):
        assert self.node_map is not None
        for path, node in self.node_map.items():
            callback(node, path)

    def find_special_nodes(
        self,
        category: SpecialNodeCategory,
        is_special: Callable[[Node], bool],
    ):
        special_nodes = []
        assert self.node_map is not None

        for path, node in self.node_map.items():
            if is_special(node):
                special_nodes.append(path)

        self.special_nodes[category] = special_nodes

    def find_anchors(self):
        assert self.node_map is not None

        def is_anchor(node):
            return hasattr(node, 'anchor') and (node.anchor is not None)

        self.anchor_paths = {}
        for path, node in self.node_map.items():
            if is_anchor(node):
                self.anchor_paths[node.anchor] = path

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __repr__(self):
        return f'CompositionResult:{self.root}'

    def __str__(self):
        return f'CompositionResult:{self.root}'


def walk_node(node, callback, start_path=None):
    def __walk_node_no_path(node):
        callback(node)
        if isinstance(node, DraconMappingNode):
            for k_node, v_node in node.value:
                __walk_node_no_path(k_node)
                __walk_node_no_path(v_node)
        elif isinstance(node, DraconSequenceNode):
            for v in node.value:
                __walk_node_no_path(v)

    def __walk_node(node, path):
        callback(node, path)
        path = path.removed_mapping_key()
        if isinstance(node, DraconMappingNode):
            for k_node, v_node in node.value:
                __walk_node(k_node, path.with_added_parts(MAPPING_KEY, k_node.value))
                __walk_node(v_node, path.with_added_parts(k_node.value))
        elif isinstance(node, DraconSequenceNode):
            for i, v in enumerate(node.value):
                __walk_node(v, path.with_added_parts(str(i)))

    if start_path is not None:
        __walk_node(node, start_path)
    else:
        __walk_node_no_path(node)


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                      --     DraconComposer     --


class DraconComposer(Composer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.special_nodes: dict[SpecialNodeCategory, list[KeyPath]] = {}
        self.anchor_paths: dict[str, KeyPath] = {}
        self.interpolation_enabled = True
        self.merging_enabled = True
        self.root_node = None

    def get_result(self) -> CompositionResult:
        if self.root_node is not None:
            root_node = self.root_node
        else:
            # create an empty root node
            root_node = DraconMappingNode(value=[], tag='')

        return CompositionResult(
            root=root_node,
            special_nodes=self.special_nodes,
        )

    def add_special_node(self, category: SpecialNodeCategory, path: KeyPath):
        if category not in self.special_nodes:
            self.special_nodes[category] = []
        self.special_nodes[category].append(path.copy())

    def compose_node(self, parent, index):
        if self.parser.check_event(AliasEvent):  # *anchor
            node = self.compose_alias_event()
        else:
            event = self.parser.peek_event()

            self.resolver.descend_resolver(parent, index)
            if self.parser.check_event(ScalarEvent):
                if event.ctag == INCLUDE_TAG:
                    node = self.compose_include_node()
                elif event.style is None and is_merge_key(event.value) and self.merging_enabled:
                    node = self.compose_merge_node()
                else:
                    node = self.compose_scalar_node()
            elif self.parser.check_event(SequenceStartEvent):
                node = self.compose_sequence_node(event.anchor)
            elif self.parser.check_event(MappingStartEvent):
                node = self.compose_mapping_node(event.anchor)
            else:
                raise RuntimeError(f'Not a valid node event: {event}')
            self.resolver.ascend_resolver()

        node = self.wrapped_node(node)

        if parent is None:
            self.root_node = node

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
        elif isinstance(node, (IncludeNode, MergeNode, InterpolableNode)):
            return node
        elif isinstance(node, ScalarNode):
            if node.value == DRACON_UNSET_VALUE:
                return UnsetNode()
            return DraconScalarNode(
                tag=node.tag,
                value=node.value,
                start_mark=node.start_mark,
                end_mark=node.end_mark,
                comment=node.comment,
                anchor=node.anchor,
            )
        else:
            raise NotImplementedError(f'Node type {type(node)} not supported')

    def compose_alias_event(self):
        event = self.parser.get_event()
        return IncludeNode(
            value=event.anchor,
            start_mark=event.start_mark,
            end_mark=event.end_mark,
            comment=event.comment,
        )

    def compose_scalar_node(self, anchor=None) -> Node:
        event = self.parser.get_event()
        tag = event.ctag

        if tag is None or str(tag) == '!':
            tag = self.resolver.resolve(ScalarNode, event.value, event.implicit)
            assert not isinstance(tag, str)

        node = ScalarNode(
            tag,
            event.value,
            event.start_mark,
            event.end_mark,
            style=event.style,
            comment=event.comment,
            anchor=event.anchor,
        )

        node = self.handle_interpolation(node)

        if node.anchor is not None:
            self.anchors[node.anchor] = node

        return node

    def handle_interpolation(self, node) -> Node:
        if self.interpolation_enabled:
            tag_iexpr = outermost_interpolation_exprs(node.tag)
            value_iexpr = (
                outermost_interpolation_exprs(node.value) if isinstance(node.value, str) else None
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

    def compose_include_node(self) -> Node:
        normal_node = self.compose_scalar_node()
        node = IncludeNode(
            value=normal_node.value,
            start_mark=normal_node.start_mark,
            end_mark=normal_node.end_mark,
            comment=normal_node.comment,
            anchor=normal_node.anchor,
        )
        return node

    def compose_merge_node(self) -> Any:
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
            anchor=event.anchor,
        )
        return node


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                           --     utils     --


def is_merge_key(value: str) -> bool:
    return value.startswith('<<')


def delete_unset_nodes(comp_res: CompositionResult):
    # when we delete an unset node, we have to check if the parent is a mapping node
    # and if we just made it empty. If so, we have to replace it with an UnsetNode
    # and so on, until we reach the root
    has_changed = False

    def _delete_unset_nodes(node: Node, parent: Optional[Node], key: Optional[Hashable]) -> Node:
        nonlocal has_changed
        if isinstance(node, DraconMappingNode):
            new_value = []
            for k, v in node.value:
                if isinstance(v, UnsetNode):
                    has_changed = True
                    continue
                new_value.append((k, _delete_unset_nodes(v, node, k)))
            if not new_value and not node.tag.startswith('!'):
                has_changed = True
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
                    has_changed = True
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

    return comp_res, has_changed


##────────────────────────────────────────────────────────────────────────────}}}
