## {{{                          --     imports     --
from collections.abc import Mapping, Sequence, Set
from ruamel.yaml.nodes import MappingNode, SequenceNode
from types import ModuleType, FunctionType
from typing import (
    Iterable,
    Hashable,
    Optional,
    TypeVar,
    Type,
    Tuple,
    Generic,
    Dict,
    Any,
    Protocol,
    Iterator,
    runtime_checkable,
    get_args,
)

from dracon.trace import ftrace as ftrace

from collections.abc import MutableMapping
##────────────────────────────────────────────────────────────────────────────}}}

## {{{                      --     dict/list like     --{{{
K = TypeVar('K')
V = TypeVar('V')
E = TypeVar('E')
T = TypeVar('T')


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

    def __repr__(self):
        return f'ShallowDict({self._dict})'


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
    return all(
        callable(getattr(obj, method, None))
        for method in ('keys', 'values', 'items', '__getitem__', '__contains__', '__setitem__')
    )


@runtime_checkable
class ListLike_Permissive(Protocol[E]):
    def __getitem__(self, index: int) -> Any: ...

    # can be concatenated with another list-like object:
    def __add__(self, other: 'ListLike_Permissive[E]') -> 'ListLike_Permissive[E]': ...

    def __iter__(self) -> Iterator[E]: ...

    def __len__(self) -> int: ...


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
    def __getitem__(self, index: int) -> Any: ...

    def __add__(self, other: 'ListLike[E]') -> 'ListLike[E]': ...

    def __append__(self, item: E) -> None: ...

    def __len__(self) -> int: ...

    def __iter__(self) -> Iterator[E]: ...


def list_like(obj) -> bool:
    return (
        all(
            callable(getattr(obj, method, None))
            for method in ('__getitem__', '__add__', '__iter__', '__len__')
        )
        and not dict_like(obj)
        and not isinstance(obj, str)
    )


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                         --     deepcopy     --


def make_hashable(obj: Any) -> Hashable:
    """
    Recursively converts unhashable objects into hashable ones.

    Handles:
    - Basic hashable types (int, str, float, bool, etc.)
    - Dictionaries -> frozenset of tuples
    - Lists/Tuples -> tuple of hashable items
    - Sets -> frozenset
    - Custom objects -> string representation
    - None -> None

    Args:
        obj: Any Python object

    Returns:
        A hashable version of the input object
    """
    # Handle None
    if obj is None:
        return None

    # Try direct hashing first
    try:
        hash(obj)
        return obj
    except TypeError:
        pass

    # Handle mappings (dict-like objects)
    if isinstance(obj, Mapping):
        items = sorted((make_hashable(k), make_hashable(v)) for k, v in obj.items())
        return frozenset(items)

    # Handle sequences (list-like objects)
    if isinstance(obj, Sequence) and not isinstance(obj, (str, bytes)):
        return tuple(make_hashable(item) for item in obj)

    # Handle sets
    if isinstance(obj, Set):
        return frozenset(make_hashable(item) for item in obj)

    # Handle numpy arrays if present
    try:
        import numpy as np

        if isinstance(obj, np.ndarray):
            return hash(obj.tobytes())
    except ImportError:
        pass

    # Handle pandas objects if present
    try:
        import pandas as pd

        if isinstance(obj, (pd.DataFrame, pd.Series)):
            return hash(obj.to_string())
    except ImportError:
        pass

    # Fallback for other objects
    try:
        return str(obj)
    except Exception:
        return f"<unhashable-{type(obj).__name__}>"


def _try_marshal(obj: T) -> Optional[T]:
    """Attempt to marshal and unmarshal an object. Return None if not possible."""
    try:
        import marshal

        return marshal.loads(marshal.dumps(obj))
    except Exception:
        return None


def _deepcopy(obj: T, memo=None) -> T:
    if obj is None:
        return obj

    if memo is None:
        memo = {}

    obj_id = id(obj)
    if obj_id in memo:
        return memo[obj_id]

    if hasattr(obj, '__deepcopy__'):
        result = obj.__deepcopy__(memo)
        memo[obj_id] = result
        return result

    result = _try_marshal(obj)
    if result is not None:
        memo[obj_id] = result
        return result

    try:
        import copy

        return copy.deepcopy(obj, memo)

    except Exception as e:
        if isinstance(obj, (ModuleType, FunctionType, type)):
            return obj  # Return the object itself for modules, functions and types
        else:
            # print(f"Failed to deepcopy object of type {type(obj)}")
            return copy.copy(obj)  # Fallback to shallow copy for other types


T = TypeVar('T')


deepcopy = _deepcopy
##────────────────────────────────────────────────────────────────────────────}}}

## {{{                         --     printing     --


def node_repr(
    node,
    prefix='',
    is_last=True,
    is_root=True,
    enable_colors=True,
    context_paths=None,
    _seen=None,
):
    if _seen is None:
        _seen = set()

    if context_paths is None:
        context_paths = ['/var']

    node_id = id(node)
    if node_id in _seen:
        return f"<circular reference to {node.__class__.__name__}>"

    _seen.add(node_id)

    try:
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
        CONTEXT_COLOR: str = GREEN
        DEFERRED_COLOR: str = BLUE

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
            'IncludeNode': '[INCL]',
            'DeferredNode': f'{DEFERRED_COLOR}[DEFER]{RESET}',
        }

        def format_context(node):
            if not hasattr(node, 'context') or not node.context or not context_paths:
                return ''

            # Convert string paths to KeyPath objects
            from dracon.keypath import KeyPath

            paths = [KeyPath(p) if isinstance(p, str) else p for p in context_paths]

            # Filter context based on paths
            matching_items = []
            for key, value in node.context.items():
                key_path = f"/{key}"  # Convert context key to path format
                if any(path.match(KeyPath(key_path)) for path in paths):
                    matching_items.append(f"{key}={value}")

            if matching_items:
                items_str = ', '.join(matching_items)
                return f'{CONTEXT_COLOR}[ctx: {items_str}]{RESET}'
            return ''

        def get_node_repr(node):
            # Special handling for DeferredNode - just add the [DEFER] tag
            is_deferred = hasattr(node, '__class__') and node.__class__.__name__ == 'DeferredNode'
            if is_deferred:
                defer_tag = NODE_TYPES.get('DeferredNode', '')
            else:
                defer_tag = ''

            ntag = ''
            if hasattr(node, 'tag'):
                ntag = node.tag
            tag = SHORT_TAGS.get(ntag, ntag)
            node_type = type(node).__name__ if not is_deferred else type(node.value).__name__
            tstring = f'{TYPE_COLOR}{NODE_TYPES.get(node_type,"")}{RESET}'
            nctx = format_context(node)

            if isinstance(node, (MappingNode, SequenceNode)) or (
                is_deferred and isinstance(node.value, (MappingNode, SequenceNode))
            ):
                return f'{TAG_COLOR}{tag}{RESET} {nctx} {tstring} {defer_tag}'

            nvalue = node.value if is_deferred else node
            if hasattr(nvalue, 'value'):
                nvalue = nvalue.value

            return (
                f'{TAG_COLOR}{tag}{RESET} {nctx} {VAL_COLOR}{nvalue}{RESET} {tstring} {defer_tag}'
            )

        output = ''

        if is_root:
            output += TREE_COLOR + '●─' + get_node_repr(node) + ' '
        else:
            connector: str = ELBOW_END if is_last else ELBOW
            line_prefix = prefix + connector
            output += line_prefix + get_node_repr(node) + '\n'

        # For DeferredNode, we want to traverse its value
        traverse_node = (
            node.value
            if hasattr(node, '__class__') and node.__class__.__name__ == 'DeferredNode'
            else node
        )

        if isinstance(traverse_node, MappingNode):
            if is_root:
                output = '\n' + output + '\n'
            child_prefix = prefix + (EMPTY if is_last else VERTICAL)
            items = traverse_node.value
            n = len(items)

            for i, (key, value) in enumerate(items):
                is_last_item = i == n - 1

                # Print the key
                key_connector: str = ELBOW_END if is_last_item else ELBOW
                key_line_prefix = child_prefix + key_connector

                if hasattr(key, 'value'):
                    key_repr = f'{TAG_COLOR}{SHORT_TAGS.get(key.tag, key.tag)}{RESET} {TREE_COLOR}󰌆{KEY_COLOR} {key.value} {RESET}'
                    keytypestr = f'{TYPE_COLOR}{NODE_TYPES.get(type(key).__name__,"")}{RESET}'
                    key_repr += f'{keytypestr}'
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
                    context_paths=context_paths,
                    _seen=_seen,
                )
                output += child_output

        elif isinstance(traverse_node, SequenceNode):
            child_prefix = prefix + (EMPTY if is_last else VERTICAL)
            items = traverse_node.value
            n = len(items)

            for i, value in enumerate(items):
                is_last_item = i == n - 1
                child_output = node_repr(
                    value,
                    prefix=child_prefix,
                    is_last=is_last_item,
                    is_root=False,
                    enable_colors=enable_colors,
                    context_paths=context_paths,
                    _seen=_seen,
                )
                output += child_output

        return output
    finally:
        _seen.remove(node_id)


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                    --     resolvable helpers     --


def get_inner_type(resolvable_type: Type):
    args = get_args(resolvable_type)
    if args:
        return args[0]
    return Any


##────────────────────────────────────────────────────────────────────────────}}}
