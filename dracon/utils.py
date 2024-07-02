import xxhash
from ruamel.yaml.nodes import MappingNode, SequenceNode, ScalarNode, Node
import base64
from typing import Iterable, TypeVar, Type, Tuple, Generic
from typing import Protocol, runtime_checkable


K = TypeVar('K')
V = TypeVar('V')
E = TypeVar('E')


@runtime_checkable
class DictLike(Protocol[K, V]):
    def keys(self) -> Iterable[K]:
        ...
    def values(self) -> Iterable[V]:
        ...
    def items(self) -> Iterable[Tuple[K, V]]:
        ...
    def __getitem__(self, key: K) -> V:
        ...
    def __contains__(self, key: K) -> bool:
        ...
    def __setitem__(self, key: K, value: V) -> None:
        ...

def dict_like(obj) -> bool:
    return isinstance(obj, DictLike)

@runtime_checkable
class ListLike_Permissive(Protocol[E]):
    def __getitem__(self, index: int) -> E:
        ...

    # can be concatenated with another list-like object:
    def __add__(self, other: 'ListLike_Permissive[E]') -> 'ListLike_Permissive[E]':
        ...

def permissive_list_like(obj) -> bool:
    return isinstance(obj, ListLike_Permissive)


class ListLikeMeta(type):
    def __instancecheck__(cls, instance):
        return permissive_list_like(instance) and not dict_like(instance)

class ListLike(Generic[E], metaclass=ListLikeMeta):
    pass

    def __getitem__(self, index: int) -> E:
        ...

    def __add__(self, other: 'ListLike[E]') -> 'ListLike[E]':
        ...


def list_like(obj) -> bool:
    return isinstance(obj, ListLike)


def with_indent(content: str, indent: int) -> str:
    # replace all \n with \n + indent*' ', ONLY if the line is not empty
    return '\n'.join([(indent*' ' + line) if line else '' for line in content.split('\n')])


def get_hash(data: str) -> str:
    hash_value = xxhash.xxh128(data).digest()
    return base64.b32encode(hash_value).decode('utf-8').rstrip('=')

def node_print(node: Node, indent_lvl=0, indent=2) -> str:
    out = ''
    if isinstance(node, MappingNode):
        if node.merge:
            out += f'{type(node)}'+' { MERGE='+str(node.merge)+'\n'
        else:
            out += f'{type(node)}'+' {\n'
        for key, value in node.value:
            if hasattr(key, 'value'):
                out += with_indent(f'{key.tag} - {key.value}: {node_print(value, indent_lvl+indent)}', indent_lvl)
            else:
                out += with_indent(f'noval(<{type(key)}>{key}): {node_print(value, indent_lvl+indent)}', indent_lvl)
        out += '},\n'
    elif isinstance(node, SequenceNode):
        indent_lvl += indent
        out += f'{type(node)}'+' [\n'
        for value in node.value:
            out += with_indent(node_print(value, indent_lvl+indent), indent_lvl)
        out += '],\n'
    elif isinstance(node, ScalarNode):
        out += f'{node.tag} - {node.value},\n'
    else:
        out += f'<{type(node)}> {node.value},\n'
    return out
