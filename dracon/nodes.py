## {{{                          --     imports     --
from ruamel.yaml.nodes import Node, MappingNode, SequenceNode, ScalarNode
from ruamel.yaml.tag import Tag
from dracon.utils import dict_like, list_like, generate_unique_id, node_repr, deepcopy
from typing import Any, Hashable, Optional
from dracon.keypath import KeyPath, escape_keypath_part
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


def base_node_hash(node):
    return hash(
        (node.tag, node.value, node.start_mark.line, node.start_mark.column, node.start_mark.name)
    )


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

    def __getstate__(self):
        state = {
            'tag': self.tag,
            'value': self.value,
            'start_mark': self.start_mark,
            'end_mark': self.end_mark,
            'style': self.style,
            'comment': self.comment,
            'anchor': self.anchor,
        }
        return state

    def __setstate__(self, state):
        self.tag = state['tag']
        self.value = state['value']
        self.start_mark = state['start_mark']
        self.end_mark = state['end_mark']
        self.style = state['style']
        self.comment = state['comment']
        self.anchor = state['anchor']


class ContextNode(DraconScalarNode):
    def __init__(
        self,
        value,
        start_mark=None,
        end_mark=None,
        tag=None,
        anchor=None,
        comment=None,
        context: Optional[dict[str, Any]] = None,
    ):
        DraconScalarNode.__init__(
            self,
            value=value,
            start_mark=start_mark,
            end_mark=end_mark,
            tag=tag,
            comment=comment,
            anchor=anchor,
        )
        self.context = context or {}

        # deepcopy still shallows copy the context:
        def __deepcopy__(self, memo):
            return self.__class__(
                value=deepcopy(self.value, memo),
                start_mark=self.start_mark,
                end_mark=self.end_mark,
                tag=self.tag,
                anchor=self.anchor,
                comment=self.comment,
                context=self.context.copy(),
            )

    def __getstate__(self):
        state = DraconScalarNode.__getstate__(self)
        state['context'] = self.context
        return state

    def __setstate__(self, state):
        DraconScalarNode.__setstate__(self, state)
        self.context = state['context']


class IncludeNode(ContextNode):
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
        ContextNode.__init__(
            self,
            value=value,
            start_mark=start_mark,
            end_mark=end_mark,
            tag=tag,
            comment=comment,
            anchor=anchor,
            context=context,
        )

        def __deepcopy__(self, memo):
            return IncludeNode(
                value=deepcopy(self.value, memo),
                start_mark=self.start_mark,
                end_mark=self.end_mark,
                tag=self.tag,
                anchor=self.anchor,
                comment=self.comment,
                context=self.context.copy(),
            )


class MergeNode(DraconScalarNode):
    def __init__(self, value, start_mark=None, end_mark=None, tag=None, anchor=None, comment=None):
        self.merge_key_raw = value
        DraconScalarNode.__init__(
            self, STR_TAG, value, start_mark, end_mark, comment=comment, anchor=anchor
        )

    def __getstate__(self):
        state = DraconScalarNode.__getstate__(self)
        state['merge_key_raw'] = self.merge_key_raw
        return state

    def __setstate__(self, state):
        DraconScalarNode.__setstate__(self, state)
        self.merge_key_raw = state['merge_key_raw']


class UnsetNode(DraconScalarNode):
    def __init__(self, start_mark=None, end_mark=None, tag=None, anchor=None, comment=None):
        DraconScalarNode.__init__(
            self,
            tag=STR_TAG,
            value='',
            start_mark=start_mark,
            end_mark=end_mark,
            comment=comment,
            anchor=anchor,
        )


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
        self.map = {}  # key value -> index
        for idx, (key, _) in enumerate(self.value):
            if not hasattr(key, 'value'):
                raise ValueError(f'Key {key!r} has no value attribute')
            if key.value in self.map:
                raise ValueError(f'Duplicate key: {key.value!r}')
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

    def __deepcopy__(self, memo):
        copied_value = deepcopy(self.value, memo)
        return self.__class__(
            tag=self.tag,
            value=copied_value,
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

    def __getstate__(self):
        state = {
            'tag': self.tag,
            'value': self.value,
            'start_mark': self.start_mark,
            'end_mark': self.end_mark,
            'flow_style': self.flow_style,
            'comment': self.comment,
            'anchor': self.anchor,
            'map': self.map,
        }
        return state

    def __setstate__(self, state):
        self.tag = state['tag']
        self.value = state['value']
        self.start_mark = state['start_mark']
        self.end_mark = state['end_mark']
        self.flow_style = state['flow_style']
        self.comment = state['comment']
        self.anchor = state['anchor']
        self.map = state['map']


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

    def __len__(self) -> int:
        return len(self.value)

    def __contains__(self, value: Node) -> bool:
        return value in self.value

    def __iter__(self):
        return iter(self.value)

    def __append__(self, value: Node):
        self.value.append(value)

    def __extend__(self, values: list[Node]):
        self.value.extend(values)

    def extend(self, values: list[Node]):
        self.value.extend(values)

    def append(self, value: Node):
        self.value.append(value)

    def __getstate__(self):
        state = {
            'tag': self.tag,
            'value': self.value,
            'start_mark': self.start_mark,
            'end_mark': self.end_mark,
            'flow_style': self.flow_style,
            'comment': self.comment,
            'anchor': self.anchor,
        }
        return state

    def __setstate__(self, state):
        self.tag = state['tag']
        self.value = state['value']
        self.start_mark = state['start_mark']
        self.end_mark = state['end_mark']
        self.flow_style = state['flow_style']
        self.comment = state['comment']
        self.anchor = state['anchor']

    @classmethod
    def from_mapping(cls, mapping: DraconMappingNode, empty=False, elt_tag=None):
        tag = mapping.tag
        if tag == DEFAULT_MAP_TAG:
            tag = DEFAULT_SEQ_TAG
        newseq = cls(
            tag=tag,
            value=[],
            start_mark=mapping.start_mark,
            end_mark=mapping.end_mark,
            flow_style=mapping.flow_style,
            comment=mapping.comment,
            anchor=mapping.anchor,
        )

        if not empty:
            elt_tag = elt_tag or DEFAULT_MAP_TAG
            for key, value in mapping.items():
                mapval = DraconMappingNode(
                    tag=elt_tag,
                    value=[(key, value)],
                )
                newseq.append(mapval)

        return newseq

    def __str__(self):
        return node_repr(self)

    def __repr__(self):
        return node_repr(self)

    def __deepcopy__(self, memo):
        return self.__class__(
            tag=self.tag,
            value=deepcopy(self.value, memo),
            start_mark=self.start_mark,
            end_mark=self.end_mark,
            flow_style=self.flow_style,
            comment=self.comment,
            anchor=self.anchor,
        )

    # def __hash__(self):
    # return hash((tuple(self.value), base_node_hash(self)))


##────────────────────────────────────────────────────────────────────────────}}}


## {{{                          --     hashes     --
def dracon_scalar_node_hash(self):
    startmark_hash = (
        hash((self.start_mark.line, self.start_mark.column, self.start_mark.name))
        if self.start_mark
        else 0
    )

    return hash(
        (self.__class__.__name__, self.tag, self.value, self.anchor, startmark_hash, self.ctag)
    )


def context_node_hash(self):
    base_hash = dracon_scalar_node_hash(self)

    # Only include hashable context items
    hashable_context = {}
    for k, v in self.context.items():
        try:
            # Test if the value is hashable
            hash(v)
            hashable_context[k] = v
        except TypeError:
            # Skip unhashable items but include their keys
            hashable_context[k] = f"<unhashable-{type(v).__name__}>"

    context_items = frozenset(hashable_context.items())
    return hash((base_hash, context_items))


def include_node_hash(self):
    """Hash function for IncludeNode."""
    return context_node_hash(self)


def merge_node_hash(self):
    base_hash = dracon_scalar_node_hash(self)
    return hash((base_hash, self.merge_key_raw))


def unset_node_hash(self):
    # UnsetNode hash is simpler since it has fixed value
    return hash((self.__class__.__name__, self.tag, self.anchor))


def dracon_mapping_node_hash(self):
    items_hash = hash(
        tuple((k.value, hash(v)) for k, v in sorted(self.value, key=lambda x: x[0].value))
    )
    return hash((self.__class__.__name__, self.tag, items_hash, self.anchor))


def dracon_sequence_node_hash(self):
    elements_hash = hash(tuple(hash(v) for v in self.value))
    return hash((self.__class__.__name__, self.tag, elements_hash, self.anchor))


# PLAN:
# simplify by removing resolvable. It's redundant with deferred
# that sould make the constructor not touch the nodes at all
# which means their hash will be consistent


# DraconScalarNode.__hash__ = dracon_scalar_node_hash
# ContextNode.__hash__ = context_node_hash
# IncludeNode.__hash__ = include_node_hash
# MergeNode.__hash__ = merge_node_hash
# UnsetNode.__hash__ = unset_node_hash
# DraconMappingNode.__hash__ = dracon_mapping_node_hash
# DraconSequenceNode.__hash__ = dracon_sequence_node_hash

##────────────────────────────────────────────────────────────────────────────}}}
