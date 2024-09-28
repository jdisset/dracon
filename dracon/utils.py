## {{{                          --     imports     --
import xxhash
from ruamel.yaml.nodes import MappingNode, SequenceNode, ScalarNode, Node
import base64
from typing import (
    Iterable,
    TypeVar,
    Type,
    Tuple,
    Generic,
    Dict,
    Any,
    Protocol,
    runtime_checkable,
    Iterator,
)
from typing import runtime_checkable, get_args, get_origin
import typing
import importlib
import inspect
import uuid
from collections.abc import MutableMapping, MutableSequence
##────────────────────────────────────────────────────────────────────────────}}}

E = TypeVar('E')
T = TypeVar('T')


def generate_unique_id() -> int:
    return uuid.uuid4().int


## {{{                      --     dict/list like     --
K = TypeVar('K')
V = TypeVar('V')


# a dict that doesnt't allow deep copying (it always returns a shallow copy)
class ShallowDict(MutableMapping, Generic[K, V]):
    def __init__(self, *args, **kwargs):
        self._dict = dict(*args, **kwargs)

    def __getitem__(self, key: K) -> V:
        return self._dict[key]

    def __setitem__(self, key: K, value: V) -> None:
        self._dict[key] = value

    def __delitem__(self, key: K) -> None:
        del self._dict[key]

    def __iter__(self) -> Iterator[K]:
        return iter(self._dict)

    def __len__(self) -> int:
        return len(self._dict)

    def __copy__(self):
        # Always return a shallow copy
        return ShallowDict(self._dict)

    def __deepcopy__(self, memo):
        # Force deep copy to behave as a shallow copy
        return self.__copy__()

    def copy(self):
        # Provide a custom copy method for explicit shallow copying
        return self.__copy__()


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
        return (
            permissive_list_like(instance)
            and not dict_like(instance)
            and not isinstance(instance, str)
        )


class ListLike(Generic[E], metaclass=ListLikeMeta):
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

    for frame_id in range(min(frame_n, len(frames) - 1), 0, -1):
        frame = frames[frame_id]
        globalns.update(frame.frame.f_globals)

    return globalns


def collect_all_types(modules, capture_globals=True, globals_at_frame=15):
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


def node_repr(node, prefix='', is_last=True, is_root=True, enable_colors=True):
    if enable_colors:
        BLUE = '\033[94m'
        GREEN = '\033[92m'
        YELLOW = '\033[93m'
        MAGENTA = '\033[95m'
        GREY = '\033[90m'
        DARK_BLUE = '\033[34m'
        DARK_GREEN = '\033[32m'
        WHITE = '\033[97m'
        RESET = '\033[0m'
    else:
        BLUE = ''
        GREEN = ''
        YELLOW = ''
        MAGENTA = ''
        GREY = ''
        DARK_BLUE = ''
        DARK_GREEN = ''
        WHITE = ''
        RESET = ''

    TAG_COLOR: str = DARK_BLUE
    YAML_TAG_COLOR: str = GREY
    VAL_COLOR: str = WHITE
    TYPE_COLOR: str = YELLOW
    KEY_COLOR: str = MAGENTA
    TREE_COLOR: str = GREY

    VERTICAL: str = TREE_COLOR + '│ ' + RESET
    ELBOW: str = TREE_COLOR + '├─' + RESET
    ELBOW_END: str = TREE_COLOR + '└─' + RESET
    EMPTY: str = TREE_COLOR + '  ' + RESET

    SHORT_TAGS = {
        'tag:yaml.org,2002:int': 'int',
        'tag:yaml.org,2002:str': 'str',
        'tag:yaml.org,2002:float': 'float',
        'tag:yaml.org,2002:bool': 'bool',
        'tag:yaml.org,2002:null': 'null',
        'tag:yaml.org,2002:map': 'map',
        'tag:yaml.org,2002:seq': 'seq',
    }
    for k, v in SHORT_TAGS.items():
        SHORT_TAGS[k] = YAML_TAG_COLOR + v + RESET

    NODE_TYPES = {
        'ScalarNode': '',
        'MappingNode': '',
        'SequenceNode': '',
        'InterpolableNode': '[INTRP]',
        'MergeNode': '[MERGE]',
    }

    def get_node_repr(node):
        tag = SHORT_TAGS.get(node.tag, node.tag)
        tstring = f'{TYPE_COLOR}{NODE_TYPES.get(type(node).__name__, "")}{RESET}'

        if isinstance(node, (MappingNode, SequenceNode)):
            return f'{TAG_COLOR}{tag}{RESET} {tstring}'

        return f'{TAG_COLOR}{tag}{RESET} {VAL_COLOR}{node.value}{RESET} {tstring}'

    output = ''

    if is_root:
        output += TREE_COLOR + '●─' + get_node_repr(node) + ' '
    else:
        connector: str = ELBOW_END if is_last else ELBOW
        line_prefix = prefix + connector
        output += line_prefix + get_node_repr(node) + '\n'

    if isinstance(node, MappingNode):
        if is_root:
            output = '\n' + output + '\n'
        child_prefix = prefix + (EMPTY if is_last else VERTICAL)
        items = node.value
        n = len(items)

        for i, (key, value) in enumerate(items):
            is_last_item = i == n - 1

            # Print the key
            key_connector: str = ELBOW_END if is_last_item else ELBOW
            key_line_prefix = child_prefix + key_connector

            if hasattr(key, 'value'):
                key_repr = f'{TAG_COLOR}{SHORT_TAGS.get(key.tag, key.tag)}{RESET} {TREE_COLOR}󰌆{KEY_COLOR} {key.value} {RESET}'
            else:
                key_repr = f'noval(<{type(key)}>{key}) [KEY]'
            output += key_line_prefix + key_repr + '\n'

            # Recursively print the value
            child_output = node_repr(
                value,
                prefix=child_prefix + (EMPTY if is_last_item else VERTICAL),
                is_last=True,
                is_root=False,
                enable_colors=enable_colors,
            )
            output += child_output

    elif isinstance(node, SequenceNode):
        child_prefix = prefix + (EMPTY if is_last else VERTICAL)
        items = node.value
        n = len(items)

        for i, value in enumerate(items):
            is_last_item = i == n - 1
            child_output = node_repr(
                value,
                prefix=child_prefix,
                is_last=is_last_item,
                is_root=False,
                enable_colors=enable_colors,
            )
            output += child_output

    return output


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                    --     resolvable helpers     --


def get_origin_type(t):
    orig = get_origin(t)
    if orig is None:
        return t
    return orig


def get_inner_type(resolvable_type: Type):
    args = get_args(resolvable_type)
    if args:
        return args[0]
    return Any


##────────────────────────────────────────────────────────────────────────────}}}
