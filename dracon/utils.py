## {{{                          --     imports     --
import xxhash
import types
from typing import Any, Hashable
from collections.abc import Mapping, Sequence, Set
from ruamel.yaml.nodes import MappingNode, SequenceNode, ScalarNode, Node
from collections import deque
import base64
import copy
from types import ModuleType, FunctionType
from typing import TypeVar, Any, Optional
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
from types import ModuleType, FunctionType
import typing
import inspect
import importlib

import uuid
import sys
import re
import os
from contextlib import ContextDecorator
import threading
import copy
# from copy import deepcopy as deepcopy

from collections.abc import MutableMapping, MutableSequence
##────────────────────────────────────────────────────────────────────────────}}}

E = TypeVar('E')
T = TypeVar('T')


def generate_unique_id() -> int:
    return uuid.uuid4().int


def printcontext(ctx):
    if ctx is None or not ctx:
        return 'empty context'
    else:
        if '$FILE_STEM' in ctx:
            return '$FILE_STEM=' + ctx['$FILE_STEM']
        else:
            return 'no $FILE in context'


def printdir(node):
    if hasattr(node, 'context'):
        return printcontext(node.context)
    else:
        return 'no context'


## {{{                      --     dict/list like     --{{{
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


def make_hashable(ctx):
    hashable_dict = {}
    for k, v in ctx.items():
        try:
            hash(v)
            hashable_dict[k] = v
        except TypeError:
            # Skip unhashable items but include their keys
            hashable_dict[k] = f"<unhashable-{type(v).__name__}>"

    h = frozenset(hashable_dict.items())
    return h


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


# Example usage:
if __name__ == "__main__":
    # Test with various types
    test_data = {
        "number": 42,
        "text": "hello",
        "list": [1, 2, [3, 4]],
        "dict": {"a": 1, "b": [2, 3]},
        "set": {1, 2, 3},
        "tuple": (1, 2, {3, 4}),
        "none": None,
    }

    hashable_result = make_hashable(test_data)
    print(f"Hashable result: {hashable_result}")
    print(f"Hash value: {hash(hashable_result)}")


def _try_marshal(obj: T) -> Optional[T]:
    """Attempt to marshal and unmarshal an object. Return None if not possible."""
    try:
        import marshal

        return marshal.loads(marshal.dumps(obj))
    except Exception:
        return None


def _try_pickle(obj: Any) -> Optional[Any]:
    """Attempt to pickle and unpickle an object. Return None if not possible."""
    try:
        import pickle

        return pickle.loads(pickle.dumps(obj))
    except Exception as e:
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


def node_repr(
    node,
    prefix='',
    is_last=True,
    is_root=True,
    enable_colors=False,
    context_paths=None,
    _seen=None,
):
    if _seen is None:
        _seen = set()

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


def old_node_repr(
    node,
    prefix='',
    is_last=True,
    is_root=True,
    enable_colors=False,
    show_file_context=True,
    _seen=None,
):
    if _seen is None:
        _seen = set()

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
        }

        def get_node_repr(node):
            ntag = ''
            if hasattr(node, 'tag'):
                ntag = node.tag
            tag = SHORT_TAGS.get(ntag, ntag)
            tstring = f'{TYPE_COLOR}{NODE_TYPES.get(type(node).__name__,"")}{RESET}'

            if isinstance(node, (MappingNode, SequenceNode)):
                return f'{TAG_COLOR}{tag}{RESET} {tstring}'

            nvalue = node
            if hasattr(node, 'value'):
                nvalue = node.value

            nctx = ''
            if hasattr(node, 'context') and show_file_context:
                nctx = f'[ctx: {printcontext(node.context)}] '

            return f'{TAG_COLOR}{tag}{RESET} {nctx} {VAL_COLOR}{nvalue}{RESET} {tstring}'

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
    finally:
        _seen.remove(node_id)


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


## {{{                          --     padded     --


class pad_output(ContextDecorator):
    def __init__(self, padding):
        self.padding = padding

    def __enter__(self):
        self._old_stdout = sys.stdout
        sys.stdout = PaddedStdout(sys.stdout, self.padding)

    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout = self._old_stdout


class PaddedStdout:
    def __init__(self, stream, padding):
        if isinstance(stream, PaddedStdout):
            self.base_stream = stream.base_stream
            self.padding = stream.padding + padding
        else:
            self.base_stream = stream
            self.padding = padding
        self.buffer = ''

    def write(self, data):
        self.buffer += data
        while '\n' in self.buffer:
            line, self.buffer = self.buffer.split('\n', 1)
            self.base_stream.write(self.padding + line + '\n')

    def flush(self):
        if self.buffer:
            self.base_stream.write(self.padding + self.buffer)
            self.buffer = ''
        self.base_stream.flush()


##────────────────────────────────────────────────────────────────────────────}}}
## {{{                          --     ftrace     --

import os
import sys
import re
import inspect
from contextlib import ContextDecorator


def get_color_for_func(func_name):
    colors_list = [
        '\033[38;2;249;65;68m',
        '\033[38;2;243;114;44m',
        '\033[38;2;248;150;30m',
        '\033[38;2;249;132;74m',
        '\033[38;2;249;199;79m',
        '\033[38;2;144;190;109m',
        '\033[38;2;67;170;139m',
        '\033[38;2;77;144;142m',
        '\033[38;2;87;117;144m',
        '\033[38;2;39;125;161m',
    ]
    hash_value = sum([ord(c) for c in func_name]) % len(colors_list)
    color = colors_list[hash_value]
    return color


def ftrace(
    inputs=True,
    output=True,
    watch=None,
    preface_filename=True,
    colors=None,
    glyphs=None,
    truncate_length=200,
    name=None,
):
    """
    A function decorator to trace the execution of a function, displaying input arguments, output, and watched variables.
    """
    # Check if tracing is enabled via the environment variable
    enable_ftrace = os.getenv('ENABLE_FTRACE')

    if not enable_ftrace:
        # Tracing is disabled; return a decorator that returns the function unmodified
        def dec(func):
            return func

        return dec

    default_colors = {
        'line_number': '\033[90m',  # Grey
        'input': '',  # Green
        'input_name': '\033[38;2;144;190;109m',  # Green
        'output': '',  # Blue
        'reset': '\033[0m',
    }
    if colors:
        default_colors.update(colors)

    default_glyphs = {
        'assign': '←',
        'create': '=',
        'return': '>',
    }
    if glyphs:
        default_glyphs.update(glyphs)

    def truncate(s, length=truncate_length):
        # Truncate a string to a maximum length, showing half of the characters on each side
        s = str(s)
        lines = []
        for line in s.split('\n'):
            if len(line) > length:
                half = (length - 3) // 2
                out = line[:half] + '...' + line[-half:]
                lines.append(out)
            else:
                lines.append(line)
        out = '\n'.join(lines)
        return out

    def strip_ansi_codes(s):
        ansi_escape = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')
        return ansi_escape.sub('', s)

    def get_filename(func):
        filename = inspect.getsourcefile(func)
        if filename:
            filename = filename.split("/")[-1]
        else:
            filename = "<unknown>"
        return filename

    def get_line_info(frame, preface_filename, filename=None):
        lineno = frame.f_lineno
        if preface_filename:
            if not filename:
                filename = frame.f_code.co_filename.split("/")[-1]
            line_info = f"{filename}:l.{lineno}"
        else:
            line_info = f"l.{lineno}"
        return line_info

    def decorator(func):
        # Get a color based on the function name
        color_code = get_color_for_func(func.__name__)
        padding = f'{color_code}│ \033[0m'

        @pad_output(padding)
        def wrapper(*args, **kwargs):
            # func_module = func.__module__
            func_class = ''
            if hasattr(func, '__qualname__') and '.' in func.__qualname__:
                func_class = f'{func.__qualname__.split(".")[0]}.'
            func_name = f"{func_class}{func.__name__}"
            filename = get_filename(func)
            line_info = get_line_info(inspect.currentframe(), preface_filename, filename=filename)

            # Handle input arguments
            if preface_filename:
                preface_str = (
                    f"{default_colors['line_number']}@{line_info}{default_colors['reset']}"
                )
            else:
                preface_str = ""

            # Include color for the function name
            func_call_str = f"{color_code}┌ {func_name}{preface_str}{default_colors['reset']}("

            sys.stdout.write('\b\b')
            if inputs:
                sig = inspect.signature(func)
                bound_args = sig.bind(*args, **kwargs)
                bound_args.apply_defaults()
                arg_strings = []
                input_arg_names = set(bound_args.arguments.keys())
                print(f"{func_call_str}")
                for name, value in bound_args.arguments.items():
                    arg_str = f"{default_colors['input']}{truncate(value)}{default_colors['reset']}"
                    if '\n' in arg_str:
                        print(f"{color_code}  {name} = {default_colors['reset']}")
                        # strip starting \n
                        arg_str = arg_str.lstrip('\n')
                        with pad_output("    "):
                            print(arg_str)
                    else:
                        arg_strings.append(
                            f"{color_code}  {name} = {default_colors['reset']}{arg_str}"
                        )
                print("):")

            else:
                print(f"{func_call_str})")
                input_arg_names = set()  # No input arguments to skip

            watched_vars_prev = {}
            watching_all = False

            if watch is None:
                watching_all = True
            elif not watch:
                watching_all = False
            else:
                for var in watch:
                    watched_vars_prev[var] = None

            def local_trace(frame, event, arg):
                if event == 'line':
                    local_filename = filename  # Use the filename from outer scope
                    line_info = get_line_info(frame, preface_filename, filename=local_filename)
                    local_vars = frame.f_locals

                    if watching_all:
                        vars_to_watch = local_vars.keys()
                    else:
                        vars_to_watch = watch

                    for var in vars_to_watch:
                        if var in local_vars:
                            value = local_vars[var]
                            prev_value = watched_vars_prev.get(var, '__UNINITIALIZED__')

                            if prev_value == '__UNINITIALIZED__':
                                # Variable seen for the first time
                                if var in input_arg_names:
                                    # Skip printing input arguments' initial assignment
                                    watched_vars_prev[var] = value
                                else:
                                    # Variable created
                                    glyph = default_glyphs['create']
                                    print(
                                        f"{default_colors['line_number']}{line_info}:{default_colors['reset']}{var} {glyph} {truncate(value)}"
                                    )
                                    watched_vars_prev[var] = value
                            elif value != prev_value:
                                # Variable updated
                                glyph = default_glyphs['assign']
                                print(
                                    f"{default_colors['line_number']}{line_info}:{default_colors['reset']}{var} {glyph} {truncate(value)}"
                                )
                                watched_vars_prev[var] = value
                    return local_trace

            def global_trace(frame, event, arg):
                if event == 'call' and frame.f_code == func.__code__:
                    return local_trace
                return None

            sys.settrace(global_trace)
            try:
                result = 'ERROR'
                result = func(*args, **kwargs)
            finally:
                sys.settrace(None)
                frame = inspect.currentframe().f_back
                line_info = get_line_info(frame, preface_filename, filename=filename)
                sys.stdout.write('\b\b')
                print(f"{color_code}└ {func_name}{default_colors['reset']} ")

                @pad_output(
                    f"\b\b  {color_code}{default_glyphs['return']} {default_colors['reset']}"
                )
                def print_res():
                    print(f"{default_colors['output']}{truncate(result)}{default_colors['reset']}")

                print_res()
            return result

        return wrapper

    return decorator
    ##────────────────────────────────────────────────────────────────────────────}}}
