from ruamel.yaml.nodes import Node, MappingNode, SequenceNode, ScalarNode
from ruamel.yaml.tag import Tag
from dracon.interpolation_utils import find_field_references, outermost_interpolation_exprs
from dracon.utils import dict_like, list_like, generate_unique_id
from typing import Any, Hashable
from dracon.keypath import KeyPath, ROOTPATH, escape_keypath_part
from copy import deepcopy

## {{{                           --     utils     --

MERGE_TAG = Tag(suffix='tag:yaml.org,2002:merge')
STR_TAG = Tag(suffix='tag:yaml.org,2002:str')

DRACON_UNSET_VALUE = '__!DRACON_UNSET_VALUE!__'
DEFAULT_MAP_TAG = 'tag:yaml.org,2002:map'
DEFAULT_SEQ_TAG = 'tag:yaml.org,2002:seq'
DEFAULT_SCALAR_TAG = 'tag:yaml.org,2002:str'


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
    def __init__(self, value, start_mark=None, end_mark=None, tag=None, anchor=None, comment=None):
        ScalarNode.__init__(self, tag, value, start_mark, end_mark, comment=comment, anchor=anchor)


class IncludeNode(ScalarNode):
    def __init__(self, value, start_mark=None, end_mark=None, tag=None, anchor=None, comment=None):
        ScalarNode.__init__(self, tag, value, start_mark, end_mark, comment=comment, anchor=anchor)


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


## {{{                     --     InterpolableNode     --
class InterpolableNode(ScalarNode):
    def __init__(
        self,
        value,
        start_mark=None,
        end_mark=None,
        tag=None,
        anchor=None,
        comment=None,
        init_outermost_interpolations=None,
        extra_symbols=None,
    ):
        self.init_outermost_interpolations = init_outermost_interpolations
        ScalarNode.__init__(self, tag, value, start_mark, end_mark, comment=comment, anchor=anchor)
        self.referenced_nodes = {}  # unique_id -> node (for later resolving ampersand references)
        self.extra_symbols = extra_symbols or {}

    def preprocess_ampersand_references(self, match, comp_res, current_path):
        available_anchors = comp_res.anchor_paths
        context_str = ''
        # references can also have a list of variable definitions attached to them
        # syntax is ${&unique_id:var1=expr1,var2=expr2}
        if ':' in match.expr:
            match.expr, vardefs = match.expr.split(':')
            context_str = f'context=dict({vardefs})'

        match_parts = match.expr.split('.', 1)
        if match_parts[0] in available_anchors:  # we're matching an anchor
            keypath = available_anchors[match_parts[0]].copy()
            keypath = keypath.down(match_parts[1]) if len(match_parts) > 1 else keypath
        else:  # we're trying to match a keypath
            keypath = current_path.parent.down(KeyPath(match.expr))

        unique_id = generate_unique_id()
        self.referenced_nodes[unique_id] = keypath.get_obj(comp_res.root)

        newexpr = f'__DRACON_RESOLVABLES[{unique_id}].resolve({context_str})'
        return newexpr

    def preprocess_references(self, comp_res, current_path):
        if self.init_outermost_interpolations is None:
            self.init_outermost_interpolations = outermost_interpolation_exprs(self.value)

        assert self.init_outermost_interpolations is not None
        interps = self.init_outermost_interpolations
        references = find_field_references(self.value)

        offset = 0
        for match in references:
            newexpr = match.expr
            if match.symbol == '&' and any([i.contains(match.start) for i in interps]):
                newexpr = self.preprocess_ampersand_references(match, comp_res, current_path)

                self.value = (
                    self.value[: match.start + offset] + newexpr + self.value[match.end + offset :]
                )
                offset += len(newexpr) - match.end + match.start
            elif match.symbol == '@' and any([i.contains(match.start) for i in interps]):
                ...  # handled in postproc
            else:
                raise ValueError(f'Unknown interpolation symbol: {match.symbol}')

        if references:
            self.init_outermost_interpolations = outermost_interpolation_exprs(self.value)


##────────────────────────────────────────────────────────────────────────────}}}
