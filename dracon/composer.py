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
from .utils import dict_like

class IncludeNode(ScalarNode):

    def __init__(self, value, start_mark=None, end_mark=None, tag=None, anchor=None, comment=None):
        if tag is None:
            tag = 'dracon_include'
        ScalarNode.__init__(self, tag, value, start_mark, end_mark, comment=comment, anchor=anchor)
        # TODO: check that its a valid include, and if not print a pretty error using start_mark
        

def keypath_str(keypath):
    out_str = ''
    for i, p in enumerate(keypath):
        if i <= 1:
            out_str += p
        else:
            out_str += '.' + p
    return out_str

class DraconComposer(Composer):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.path_stack = []
        self.anchor_paths = {}

    def descend_path(self, parent, index):
        if parent is None:
            self.path_stack.append('/')
        elif isinstance(parent, MappingNode):
            if index is None:
                self.path_stack.append(None)
            elif isinstance(index, ScalarNode):
                self.path_stack.append(index.value)
            else:
                self.path_stack.append(str(index))
        elif isinstance(parent, SequenceNode):
            self.path_stack.append(str(index))

    def ascend_path(self):
        if self.path_stack:
            self.path_stack.pop()

    def get_path(self):
        return [p for p in self.path_stack if p is not None]

    def compose_node(self, parent, index):
        self.descend_path(parent, index)
        current_path = self.get_path()

        if self.parser.check_event(AliasEvent):
            event = self.parser.get_event()
            node = IncludeNode(
                value=current_path,
                start_mark=event.start_mark,
                end_mark=event.end_mark,
                anchor=event.anchor,
            )
        else:
            event = self.parser.peek_event()
            anchor = event.anchor
            if anchor is not None:
                assert anchor not in self.anchor_paths, f'Anchor {anchor} already exists'
                self.anchor_paths[anchor] = keypath_str(current_path)

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

            if anchor:
                self.anchor_paths[anchor] = keypath_str(current_path)

        self.ascend_path()
        return node

