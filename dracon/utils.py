import xxhash
from ruamel.yaml.nodes import MappingNode, SequenceNode, ScalarNode, Node
import base64
from typing import (
    Iterable,
    TypeVar,
    Type,
    Tuple,
    Generic,
    Annotated,
    Union,
    Dict,
    Any,
    Protocol,
    Literal,
)
from typing import runtime_checkable, get_args, get_origin
import pyparsing as pp
import re
from pydantic.dataclasses import dataclass
import typing
import importlib
import inspect
import uuid

E = TypeVar('E')
T = TypeVar('T')


def generate_unique_id() -> int:
    return uuid.uuid4().int


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

## {{{                    --     interpolation exprs     --


@dataclass
class InterpolationMatch:
    start: int
    end: int
    expr: str

    def contains(self, pos: int) -> bool:
        return self.start <= pos < self.end


def fast_interpolation_exprs_check(  # about 1000x faster than the pyparsing version but can't handle nested expressions
    text: str, interpolation_start_char='$', interpolation_boundary_chars=('{}', '()')
) -> bool:
    patterns = [
        re.escape(interpolation_start_char) + re.escape(bound[0]) + r".*?" + re.escape(bound[1])
        for bound in interpolation_boundary_chars
    ]
    matches = re.search("|".join(patterns), text)
    return matches is not None


def fast_prescreen_interpolation_exprs_check(  # 5000x but very simple and limited
    text: str, interpolation_start_char='$', interpolation_boundary_chars=('{}', '()')
) -> bool:
    start_patterns = [interpolation_start_char + bound[0] for bound in interpolation_boundary_chars]
    for start_pattern in start_patterns:
        if start_pattern in text:
            return True
    return False


def outermost_interpolation_exprs(
    text: str, interpolation_start_char='$', interpolation_boundary_chars=('{}', '()')
) -> list[InterpolationMatch]:
    matches = []
    if not fast_prescreen_interpolation_exprs_check(
        text, interpolation_start_char, interpolation_boundary_chars
    ):
        return matches

    scanner = pp.MatchFirst(
        [
            pp.originalTextFor(pp.nestedExpr(bounds[0], bounds[1]))
            for bounds in interpolation_boundary_chars
        ]
    )
    scanner = pp.Combine(interpolation_start_char + scanner)
    for match, start, end in scanner.scanString(text):
        matches.append(InterpolationMatch(start, end, match[0][2:-1]))
    return sorted(matches, key=lambda m: m.start)


##────────────────────────────────────────────────────────────────────────────}}}
## {{{             --     find references [@,&](keypaths, anchors)     --

# Find all field references in an expression string and replace them with a function call


@dataclass
class ReferenceMatch:
    start: int
    end: int
    expr: str
    symbol: Literal['@', '&']


NOT_ESCAPED_REGEX = r"(?<!\\)(?:\\\\)*"
# INVALID_KEYPATH_CHARS = r'[]() ,:=+-*%<>!&|^~@#$?;{}"\'`'
INVALID_KEYPATH_CHARS = r'[]() ,+-*%<>!&|^~@#$?;{}"\'`'
SPECIAL_KEYPATH_CHARS = './\\'  # Added backslash to handle escaping of itself


def find_field_references(expr: str) -> list[ReferenceMatch]:
    # Regex pattern to match keypaths
    pattern = f"{NOT_ESCAPED_REGEX}[&@]([^{re.escape(INVALID_KEYPATH_CHARS)}]|(?:\\\\.))*"

    matches = []
    for match in re.finditer(pattern, expr):
        start, end = match.span()
        full_match = match.group()
        keypath = full_match[1:]
        symbol = full_match[0]
        assert symbol in ('@', '&')

        # Clean up escaping, but keep backslashes for special keypath characters
        cleaned_keypath = ''
        i = 0
        while i < len(keypath):
            if keypath[i] == '\\' and i + 1 < len(keypath):
                if keypath[i + 1] in SPECIAL_KEYPATH_CHARS:
                    cleaned_keypath += keypath[i : i + 2]
                    i += 2
                else:
                    cleaned_keypath += keypath[i + 1]
                    i += 2
            else:
                cleaned_keypath += keypath[i]
                i += 1

        # Check if the keypath ends with an odd number of backslashes
        if len(keypath) - len(keypath.rstrip('\\')) % 2 == 1:
            end -= 1
            cleaned_keypath = cleaned_keypath[:-1]

        matches.append(ReferenceMatch(start, end, cleaned_keypath, symbol))

    return matches


def resolve_field_references(expr: str):
    keypath_matches = find_field_references(expr)
    if not keypath_matches:
        return expr
    offset = 0
    for match in keypath_matches:
        if match.symbol == '@':
            newexpr = (
                f"(__DRACON__PARENT_PATH + __dracon_KeyPath('{match.expr}'))"
                f".get_obj(__DRACON__CURRENT_ROOT_OBJ)"
            )
        elif match.symbol == '&':
            raise ValueError(f"Ampersand references in {expr} should have been handled earlier")
        else:
            raise ValueError(f"Invalid symbol {match.symbol} in {expr}")

        expr = expr[: match.start + offset] + newexpr + expr[match.end + offset :]
        original_len = match.end - match.start
        offset += len(newexpr) - original_len
    return expr


##────────────────────────────────────────────────────────────────────────────}}}
## {{{                --     find interpolable variables     --

# an interpolable variable is a special $VARIABLE defined by dracon (or the user)
# they are immmediately replaced by their value when found in the expression string
# pattern is $ + CAPITAL_LETTER + [a-zA-Z0-9_]


@dataclass
class VarMatch:
    start: int
    end: int
    varname: str


def find_interpolable_variables(expr: str) -> list[VarMatch]:
    matches = []
    for match in re.finditer(rf"{NOT_ESCAPED_REGEX}\$[A-Z][a-zA-Z0-9_]*", expr):
        start, end = match.span()
        matches.append(VarMatch(start, end, match.group()))
    return matches


def resolve_interpolable_variables(expr: str, symbols: Dict[str, Any]) -> str:
    var_matches = find_interpolable_variables(expr)
    if not var_matches:
        return expr
    offset = 0
    for match in var_matches:
        if match.varname not in symbols:
            raise InterpolationError(f"Variable {match.varname} not found in symbols")
        newexpr = str(symbols[match.varname])
        expr = expr[: match.start + offset] + newexpr + expr[match.end + offset :]
        original_len = match.end - match.start
        offset += len(newexpr) - original_len
    return expr


##────────────────────────────────────────────────────────────────────────────}}}
