# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

## {{{                          --     imports     --
from ruamel.yaml.nodes import Node, MappingNode, SequenceNode, ScalarNode
from ruamel.yaml.tag import Tag
from dracon.utils import dict_like, list_like, node_repr, deepcopy, make_hashable, ShallowDict
from typing import Any, Hashable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from dracon.diagnostics import SourceContext
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


def make_source_context(start_mark, include_trace=None, keypath=None) -> Optional["SourceContext"]:
    from dracon.diagnostics import SourceContext
    if start_mark is None:
        return None
    return SourceContext.from_mark(start_mark, include_trace or (), keypath=keypath)


##────────────────────────────────────────────────────────────────────────────}}}


def base_node_hash(node):
    return hash(
        (node.tag, node.value, node.start_mark.line, node.start_mark.column, node.start_mark.name)
    )


class DraconScalarNode(ScalarNode):
    def __init__(
        self, tag, value, start_mark=None, end_mark=None, style=None, comment=None,
        anchor=None, source_context: Optional["SourceContext"] = None,
    ):
        ScalarNode.__init__(self, tag, value, start_mark, end_mark, style=style, comment=comment, anchor=anchor)
        self._source_context = source_context

    @property
    def source_context(self) -> Optional["SourceContext"]:
        if self._source_context is None and self.start_mark is not None:
            self._source_context = make_source_context(self.start_mark)
        return self._source_context

    @source_context.setter
    def source_context(self, value: Optional["SourceContext"]):
        self._source_context = value

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
            '_source_context': self._source_context,
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
        self._source_context = state.get('_source_context')


class ContextNode(DraconScalarNode):
    def __init__(
        self,
        value,
        start_mark=None,
        end_mark=None,
        tag=None,
        anchor=None,
        comment=None,
        context=None,
        source_context: Optional["SourceContext"] = None,
    ):
        DraconScalarNode.__init__(
            self,
            value=value,
            start_mark=start_mark,
            end_mark=end_mark,
            tag=tag,
            comment=comment,
            anchor=anchor,
            source_context=source_context,
        )
        self.context = (
            ShallowDict(context or {}) if not isinstance(context, ShallowDict) else context
        )

    def __getstate__(self):
        state = DraconScalarNode.__getstate__(self)
        state['context'] = self.context.copy()
        return state

    def __setstate__(self, state):
        DraconScalarNode.__setstate__(self, state)
        self.context = state['context']

    def copy(self):
        """Create a shallow copy with the context also shallow copied."""
        return self.__class__(
            value=self.value,
            start_mark=self.start_mark,
            end_mark=self.end_mark,
            tag=self.tag,
            anchor=self.anchor,
            comment=self.comment,
            context=self.context.copy(),  # Shallow copy the context
            source_context=self._source_context,
        )


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

    def __deepcopy__(self, memo):
        return UnsetNode(
            start_mark=self.start_mark,
            end_mark=self.end_mark,
            tag=self.tag,
            anchor=self.anchor,
            comment=self.comment,
        )


## {{{                        --     MappingNode     --


class DraconMappingNode(MappingNode):
    def __init__(
        self, tag: Any, value: Any, start_mark: Any = None, end_mark: Any = None,
        flow_style: Any = None, comment: Any = None, anchor: Any = None,
        source_context: Optional["SourceContext"] = None,
    ) -> None:
        MappingNode.__init__(self, tag, value, start_mark, end_mark, flow_style, comment, anchor)
        self._source_context = source_context
        self._recompute_map()

    @property
    def source_context(self) -> Optional["SourceContext"]:
        if self._source_context is None and self.start_mark is not None:
            self._source_context = make_source_context(self.start_mark)
        return self._source_context

    @source_context.setter
    def source_context(self, value: Optional["SourceContext"]):
        self._source_context = value

    def _recompute_map(self):
        self.map = {}  # key value -> index
        for idx, (key, _) in enumerate(self.value):
            if not hasattr(key, 'value'):
                raise ValueError(f'Key {key!r} has no value attribute')
            key_val = str(key.value)
            if key_val in self.map:
                raise ValueError(f'Duplicate key: {key_val!r}')
            self.map[key_val] = idx

    # and implement a get[] (and set) method
    def __getitem__(self, key: Hashable) -> Node:
        if isinstance(key, Node):
            key = key.value
        key_str = str(key)
        return self.value[self.map[key_str]][1]

    def __setitem__(self, key: Hashable, value: Node):
        if isinstance(key, Node):
            keyv = key.value
        else:
            keyv = key
        key_str = str(keyv)
        if key_str in self.map:
            idx = self.map[key_str]
            realkey, _ = self.value[idx]
            self.value[idx] = (realkey, value)
        else:
            # assert isinstance(key, Node)
            self.value.append((key, value))
            self._recompute_map()

    def __delitem__(self, key: Hashable):
        if isinstance(key, Node):
            key = key.value
        # Convert key to string for lookup
        key_str = str(key)
        idx = self.map[key_str]
        del self.value[idx]
        self._recompute_map()

    def __contains__(self, key: Hashable) -> bool:
        if isinstance(key, Node):
            key = key.value
        key_str = str(key)
        return key_str in self.map

    def keys(self):
        return self.map.keys()

    def values(self):
        return (value for _, value in self.value)

    def items(self):
        return self.value

    def get(self, key: Hashable, default=None):
        return self[key] if key in self else default

    def get_key(self, key: Hashable):
        key_str = str(key)
        idx = self.map[key_str]
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
            source_context=self._source_context,
        )

    def __deepcopy__(self, memo):
        copied_value = deepcopy(self.value, memo)
        n = self.__class__(
            tag=self.tag,
            value=copied_value,
            start_mark=self.start_mark,
            end_mark=self.end_mark,
            flow_style=self.flow_style,
            comment=self.comment,
            anchor=self.anchor,
            source_context=self._source_context,
        )
        n.ctag = self.ctag
        n.id = self.id
        return n

    def append(self, newvalue: tuple[Node, Node]):
        key, _ = newvalue
        self.value.append(newvalue)
        key_str = str(key.value)
        if key_str in self.map:
            raise ValueError(f'Duplicate key: {key_str}')
        self.map[key_str] = len(self.value) - 1

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
            '_source_context': self._source_context,
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
        self._source_context = state.get('_source_context')

    @classmethod
    def make_empty(cls, tag: Any = DEFAULT_MAP_TAG, start_mark: Any = None, end_mark: Any = None):
        return cls(
            tag=tag,
            value=[],
            start_mark=start_mark,
            end_mark=end_mark,
            flow_style=None,
            comment=None,
            anchor=None,
        )


##────────────────────────────────────────────────────────────────────────────}}}


## {{{                       --     SequenceNode     --
class DraconSequenceNode(SequenceNode):
    def __init__(
        self, tag: Any, value: Any, start_mark: Any = None, end_mark: Any = None,
        flow_style: Any = None, comment: Any = None, anchor: Any = None,
        source_context: Optional["SourceContext"] = None,
    ) -> None:
        SequenceNode.__init__(self, tag, value, start_mark, end_mark, flow_style, comment, anchor)
        self._source_context = source_context

    @property
    def source_context(self) -> Optional["SourceContext"]:
        if self._source_context is None and self.start_mark is not None:
            self._source_context = make_source_context(self.start_mark)
        return self._source_context

    @source_context.setter
    def source_context(self, value: Optional["SourceContext"]):
        self._source_context = value

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
            source_context=self._source_context,
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
            '_source_context': self._source_context,
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
        self._source_context = state.get('_source_context')

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
            source_context=getattr(mapping, '_source_context', None),
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
        n = self.__class__(
            tag=self.tag,
            value=deepcopy(self.value, memo),
            start_mark=self.start_mark,
            end_mark=self.end_mark,
            flow_style=self.flow_style,
            comment=self.comment,
            anchor=self.anchor,
            source_context=self._source_context,
        )
        n.ctag = self.ctag
        n.id = self.id
        return n


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
    context_items = make_hashable(self.context)
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


# DraconScalarNode.__hash__ = dracon_scalar_node_hash
# ContextNode.__hash__ = context_node_hash
# IncludeNode.__hash__ = include_node_hash
# MergeNode.__hash__ = merge_node_hash
# UnsetNode.__hash__ = unset_node_hash
# DraconMappingNode.__hash__ = dracon_mapping_node_hash
# DraconSequenceNode.__hash__ = dracon_sequence_node_hash

##────────────────────────────────────────────────────────────────────────────}}}
