## {{{                          --     imports     --
from ruamel.yaml.nodes import Node, MappingNode, SequenceNode, ScalarNode
from ruamel.yaml.tag import Tag
from dracon.utils import dict_like, list_like, generate_unique_id, node_repr
from typing import Any, Hashable
from dracon.keypath import KeyPath, escape_keypath_part
from functools import partial
##────────────────────────────────────────────────────────────────────────────}}}

## {{{                           --     utils     --

MERGE_TAG = Tag(suffix='tag:yaml.org,2002:merge')
STR_TAG = Tag(suffix='tag:yaml.org,2002:str')

DRACON_UNSET_VALUE = '__!DRACON_UNSET_VALUE!__'
DEFAULT_MAP_TAG = 'tag:yaml.org,2002:map'
DEFAULT_SEQ_TAG = 'tag:yaml.org,2002:seq'
DEFAULT_SCALAR_TAG = 'tag:yaml.org,2002:str'


def reset_tag(node):
    if isinstance(node, SequenceNode):
        node.tag = DEFAULT_SEQ_TAG
    elif isinstance(node, MappingNode):
        node.tag = DEFAULT_MAP_TAG
    else:
        node.tag = DEFAULT_SCALAR_TAG


def make_node(value: Any, tag=None, **kwargs):
    if isinstance(value, Node):
        if tag is not None:
            value.tag = tag
        return value

    if dict_like(value):
        return DraconMappingNode(
            tag or DEFAULT_MAP_TAG,
            value=[(make_node(k), make_node(v)) for k, v in value.items()],
            **kwargs,
        )
    elif list_like(value):
        return DraconSequenceNode(
            tag or DEFAULT_SEQ_TAG, value=[make_node(v) for v in value], **kwargs
        )
    else:
        return ScalarNode(tag or DEFAULT_SCALAR_TAG, value, **kwargs)


##────────────────────────────────────────────────────────────────────────────}}}


class DraconScalarNode(ScalarNode):
    def __init__(
        self,
        tag,
        value,
        start_mark=None,
        end_mark=None,
        style=None,
        comment=None,
        anchor=None,
    ):
        ScalarNode.__init__(self, tag, value, start_mark, end_mark, comment=comment, anchor=anchor)

    def __str__(self):
        return node_repr(self)

    def __repr__(self):
        return node_repr(self)


class DeferredNode(ScalarNode):
    # A node that is not yet resolved, just a wrapper to another node
    def __init__(
        self,
        tag,
        value,
        start_mark=None,
        end_mark=None,
        style=None,
        comment=None,
        anchor=None,
        context=None,
    ):
        ScalarNode.__init__(self, tag, value, start_mark, end_mark, comment=comment, anchor=anchor)
        self.context = context or {}
        self.loader = None

    def compose(self, **kwargs):
        from dracon.loader import DraconLoader
        from dracon.composer import CompositionResult, walk_node
        from dracon.merge import add_to_context

        if not self.loader:
            raise ValueError('DeferredNode must have a loader to be composed')

        if not isinstance(self.value, Node):
            raise ValueError('DeferredNode must have a Node as value')

        walk_node(
            node=self.value,
            callback=partial(add_to_context, self.context),
        )

        compres = CompositionResult(root=self.value)
        compres = self.loader.post_process_composed(compres)
        return compres

    def construct(self, **kwargs):
        compres = self.compose(**kwargs)
        return self.loader.load_from_composition_result(compres)


class IncludeNode(DraconScalarNode):
    def __init__(
        self,
        value,
        start_mark=None,
        end_mark=None,
        tag=None,
        anchor=None,
        comment=None,
        context=None,
    ):
        DraconScalarNode.__init__(
            self, tag, value, start_mark, end_mark, comment=comment, anchor=anchor
        )
        self.context = context or {}

    def __str__(self):
        return node_repr(self)

    def __repr__(self):
        return node_repr(self)


class MergeNode(DraconScalarNode):
    def __init__(self, value, start_mark=None, end_mark=None, tag=None, anchor=None, comment=None):
        self.merge_key_raw = value
        DraconScalarNode.__init__(
            self, STR_TAG, value, start_mark, end_mark, comment=comment, anchor=anchor
        )

    def __str__(self):
        return node_repr(self)

    def __repr__(self):
        return node_repr(self)


class UnsetNode(DraconScalarNode):
    def __init__(self, start_mark=None, end_mark=None, tag=None, anchor=None, comment=None):
        DraconScalarNode.__init__(
            self,
            tag=STR_TAG,
            value=DRACON_UNSET_VALUE,
            start_mark=start_mark,
            end_mark=end_mark,
            comment=comment,
            anchor=anchor,
        )

    def __str__(self):
        return node_repr(self)

    def __repr__(self):
        return node_repr(self)


## {{{                        --     MappingNode     --


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
        self.map: dict[Hashable, int] = {}  # key value -> index

        for idx, (key, _) in enumerate(self.value):
            assert hasattr(key, 'value'), f'Key {key} has no value attribute'
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
        return (value for _, value in self.value)

    def items(self):
        return self.value

    def get(self, key: Hashable, default=None):
        return self[key] if key in self else default

    def get_key(self, key: Hashable):
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

    def get_include_nodes(self) -> list[KeyPath]:
        res = []

        for key, value in self.value:
            curpath = KeyPath(escape_keypath_part(key.value))
            if isinstance(value, IncludeNode):
                res.append(curpath)
            elif isinstance(value, DraconMappingNode):
                res.extend([curpath + p for p in value.get_include_nodes()])

        return res

    def get_merge_nodes(self) -> list[KeyPath]:
        res = []

        for key, value in self.value:
            curpath = KeyPath(escape_keypath_part(key.value))
            if isinstance(key, MergeNode):
                res.append(curpath)
            if isinstance(value, DraconMappingNode):
                res.extend([curpath + p for p in value.get_merge_nodes()])

        return res

    def append(self, newvalue: tuple[Node, Node]):
        key, _ = newvalue
        self.value.append(newvalue)
        if key.value in self.map:
            raise ValueError(f'Duplicate key: {key.value}')
        self.map[key.value] = len(self.value) - 1

    def clear(self):
        self.value = []
        self.map = {}

    def __str__(self):
        return node_repr(self)

    def __repr__(self):
        return node_repr(self)


##────────────────────────────────────────────────────────────────────────────}}}


## {{{                       --     SequenceNode     --
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

    def append(self, value: Node):
        self.value.append(value)

    @classmethod
    def from_mapping(cls, mapping: DraconMappingNode, empty=False):
        tag = mapping.tag
        if tag == DEFAULT_MAP_TAG:
            tag = DEFAULT_SEQ_TAG
        return cls(
            tag=tag,
            value=[v for _, v in mapping.value] if not empty else [],
            start_mark=mapping.start_mark,
            end_mark=mapping.end_mark,
            flow_style=mapping.flow_style,
            comment=mapping.comment,
            anchor=mapping.anchor,
        )


##────────────────────────────────────────────────────────────────────────────}}}
