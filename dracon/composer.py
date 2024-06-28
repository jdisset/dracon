from ruamel.yaml import YAML
from ruamel.yaml.composer import Composer
from ruamel.yaml.nodes import MappingNode, SequenceNode, ScalarNode
from ruamel.yaml.nodes import ScalarNode, Node
from ruamel.yaml.events import (
    AliasEvent,
    ScalarEvent,
    SequenceStartEvent,
    MappingStartEvent,
)
from .merge import MergeKey, merged
from .utils import dict_like, simplify_path, combine_paths
from pydantic import BaseModel
from .keypath import KeyPath, KeyPathToken, ROOTPATH


class WrappedInWeakRef:
    def __init__(self, obj):
        self.obj = obj

    def __hash__(self):
        return hash(self.obj)

    def __eq__(self, other):
        return self.obj == other.obj

class IncludeNode(ScalarNode):

    def __init__(
        self, value, at_path, start_mark=None, end_mark=None, tag=None, anchor=None, comment=None
    ):
        if tag is None:
            tag = 'dracon_include'
        self.at_path = at_path
        ScalarNode.__init__(self, tag, value, start_mark, end_mark, comment=comment, anchor=anchor)


class CompositionResult(BaseModel):

    node_map: dict[KeyPath, Node] = {}  # keypath -> node
    include_nodes: list[KeyPath] = []  # keypaths to include nodes
    anchor_paths: dict[str, KeyPath] = {}  # anchor name -> keypath to that anchor node
    reverse_map: dict[Node, set[KeyPath]] = {} # nodes are hashable!

    def model_post_init(self, *args, **kwargs):
        super().model_post_init(*args, **kwargs)
        self.build_reverse_map()

    def build_reverse_map(self):
        self.reverse_map = {}
        for keypath, node in self.node_map.items():
            if node not in self.reverse_map:
                self.reverse_map[node] = set()
            self.reverse_map[node].add(keypath)

    def root(self):
        return self.node_map[ROOTPATH]

    def rerooted(self, new_root: KeyPath):

        new_root.simplify()

        assert new_root in set(
            self.node_map.keys()
        ), f'Invalid {new_root=}, not in {self.node_map.keys()=}'

        new_node_map = {}
        for old_keypath, node in self.node_map.items():
            if old_keypath.startswith(new_root):
                new_keypath = (ROOTPATH + old_keypath[len(new_root) :]).simplified()
                new_node_map[new_keypath] = node

        new_include_nodes = [
            (ROOTPATH + include_node[len(new_root) :]).simplified()
            for include_node in self.include_nodes
            if include_node.startswith(new_root)
        ]

        new_anchor_paths = {
            anchor: (ROOTPATH + anchor_path[len(new_root) :]).simplified()
            for anchor, anchor_path in self.anchor_paths.items()
            if anchor_path.startswith(new_root)
        }

        return CompositionResult(
            node_map=new_node_map,
            include_nodes=new_include_nodes,
            anchor_paths=new_anchor_paths,
        )


    def replace_at(self, at_path, new_root: 'CompositionResult'):
        # node at at_path will be replaced with the new_root.root()

        assert at_path in self.node_map, f'Invalid {at_path=}, not in {self.node_map.keys()=}'

        previous_node = self.node_map[at_path]
        other_node_map_with_prefix = {
            (at_path + k.rootless()).simplified(): v for k, v in new_root.node_map.items()
        }

        self.node_map.update(other_node_map_with_prefix)
        new_node = new_root.root()
        # replace all references to the previous node with the new node
        all_keypaths = self.reverse_map[previous_node]
        for keypath in all_keypaths:
            self.node_map[keypath] = new_node


        if at_path in self.include_nodes:
            self.include_nodes.remove(at_path)
            self.include_nodes.extend(
                [
                    (at_path + include_node.rootless()).simplified()
                    for include_node in new_root.include_nodes
                ]
            )

        for anchor, anchor_path in new_root.anchor_paths.items():
            if anchor not in self.anchor_paths:
                self.anchor_paths[anchor] = (at_path + anchor_path.rootless()).simplified()

        self.build_reverse_map()
        return self

    class Config:
        arbitrary_types_allowed = True


class DraconComposer(Composer):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.node_map: dict[KeyPath, Node] = {}  # keypath -> node
        self.include_nodes: list[KeyPath] = []  # keypaths to include nodes
        self.anchor_paths: dict[str, KeyPath] = {}  # anchor name -> keypath to that anchor node

        self.curr_path = ROOTPATH

    def get_result(self) -> CompositionResult:
        return CompositionResult(
            node_map=self.node_map,
            include_nodes=self.include_nodes,
            anchor_paths=self.anchor_paths,
        )

    def descend_path(self, parent, index):
        assert index is not None, f'Invalid index: {index}'
        previous_path = str(self.curr_path)
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
            previous_path = str(self.curr_path)
            self.node_map[self.curr_path.copy()] = node
            self.curr_path.up()

    def compose_node(self, parent, index):
        if index is not None:
            self.descend_path(parent, index)

        if self.parser.check_event(AliasEvent):
            event = self.parser.get_event()
            node = IncludeNode(
                value=event.anchor,
                at_path=self.curr_path.copy(),
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
                if event.style is None and MergeKey.is_merge_key(event.value):
                    event.tag = 'dracon_merge'
                node = self.compose_scalar_node(anchor)
            elif self.parser.check_event(SequenceStartEvent):
                node = self.compose_sequence_node(anchor)
            elif self.parser.check_event(MappingStartEvent):
                node = self.compose_mapping_node(anchor)
            else:
                raise RuntimeError(f'Not a valid node event: {event}')
            self.resolver.ascend_resolver()

        if index is not None:
            self.ascend_path(node)
            # assert self.node_map[self.curr_path] == node
        if parent is None:
            assert self.curr_path == ROOTPATH
            self.node_map[self.curr_path.copy()] = node
        return node
