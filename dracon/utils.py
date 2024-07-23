import xxhash
from ruamel.yaml.nodes import MappingNode, SequenceNode, ScalarNode, Node
import base64
from typing import Iterable, TypeVar, Type, Tuple, Generic, Annotated, Union, Dict
from typing import Protocol, runtime_checkable
import typing
import importlib
import inspect

E = TypeVar('E')
T = TypeVar('T')

## {{{                      --     dict/list like     --
K = TypeVar('K')
V = TypeVar('V')


@runtime_checkable
class DictLike(Protocol[K, V]):
    def keys(self) -> Iterable[K]: ...
    def values(self) -> Iterable[V]: ...
    def items(self) -> Iterable[Tuple[K, V]]: ...
    def __getitem__(self, key: K) -> V: ...
    def __contains__(self, key: K) -> bool: ...
    def __setitem__(self, key: K, value: V) -> None: ...


@runtime_checkable
class MetadataDictLike(Protocol[K, V]):
    def keys(self) -> Iterable[K]: ...
    def values(self) -> Iterable[V]: ...
    def items(self) -> Iterable[Tuple[K, V]]: ...
    def __getitem__(self, key: K) -> V: ...
    def __contains__(self, key: K) -> bool: ...
    def __setitem__(self, key: K, value: V) -> None: ...
    def get_metadata(self) -> Dict: ...
    def set_metadata(self, metadata: Dict): ...


def metadata_dict_like(obj) -> bool:
    return isinstance(obj, MetadataDictLike)

def dict_like(obj) -> bool:
    return isinstance(obj, DictLike)


@runtime_checkable
class ListLike_Permissive(Protocol[E]):
    def __getitem__(self, index: int) -> E: ...

    # can be concatenated with another list-like object:
    def __add__(self, other: 'ListLike_Permissive[E]') -> 'ListLike_Permissive[E]': ...


def permissive_list_like(obj) -> bool:
    return isinstance(obj, ListLike_Permissive)


class ListLikeMeta(type):
    def __instancecheck__(cls, instance):
        return permissive_list_like(instance) and not dict_like(instance)


class ListLike(Generic[E], metaclass=ListLikeMeta):
    pass

    def __getitem__(self, index: int) -> E: ...

    def __add__(self, other: 'ListLike[E]') -> 'ListLike[E]': ...


def list_like(obj) -> bool:
    return isinstance(obj, ListLike)

##────────────────────────────────────────────────────────────────────────────}}}

## {{{                      --     type collection     --
def get_all_types(items):
    return {
        name: obj
        for name, obj in items.items()
        if isinstance(
            obj,
            (
                type,
                typing._GenericAlias,
                typing._SpecialForm,
                typing._SpecialGenericAlias,
            ),
        )
    }


def get_all_types_from_module(module):
    if isinstance(module, str):
        try:
            module = importlib.import_module(module)
        except ImportError:
            print(f"WARNING: Could not import module {module}")
            return {}
    return get_all_types(module.__dict__)


def get_globals_up_to_frame(frame_n):
    frames = inspect.stack()
    globalns = {}

    for frame_id in range(min(frame_n, len(frames)), 0, -1):
        frame = frames[frame_id]
        globalns.update(frame.frame.f_globals)

    return globalns


def collect_all_types(modules, capture_globals=True, globals_at_frame=5):
    types = {}
    for module in modules:
        types.update(get_all_types_from_module(module))
    if capture_globals:
        globalns = get_globals_up_to_frame(globals_at_frame)
        types.update(get_all_types(globalns))
    return types


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                         --     printing     --

def print_traceback():
    import traceback
    print("".join(traceback.format_stack()[:-2]))

def with_indent(content: str, indent: int) -> str:
    # replace all \n with \n + indent*' ', ONLY if the line is not empty
    return '\n'.join([(indent * ' ' + line) if line else '' for line in content.split('\n')])


def get_hash(data: str) -> str:
    hash_value = xxhash.xxh128(data).digest()
    return base64.b32encode(hash_value).decode('utf-8').rstrip('=')


def node_print(node: Node, indent_lvl=0, indent=2) -> str:
    out = ''
    if isinstance(node, MappingNode):
        if node.merge:
            out += f'{type(node)}' + ' { MERGE=' + str(node.merge) + '\n'
        else:
            out += f'{type(node)}' + ' {\n'
        for key, value in node.value:
            if hasattr(key, 'value'):
                out += with_indent(
                    f'{key.tag} - {key.value}: {node_print(value, indent_lvl+indent)}', indent_lvl
                )
            else:
                out += with_indent(
                    f'noval(<{type(key)}>{key}): {node_print(value, indent_lvl+indent)}', indent_lvl
                )
        out += '},\n'
    elif isinstance(node, SequenceNode):
        indent_lvl += indent
        out += f'{type(node)}' + ' [\n'
        for value in node.value:
            out += with_indent(node_print(value, indent_lvl + indent), indent_lvl)
        out += '],\n'
    elif isinstance(node, ScalarNode):
        out += f'{node.tag} - {node.value},\n'
    else:
        out += f'<{type(node)}> {node.value},\n'
    return out


##────────────────────────────────────────────────────────────────────────────}}}

