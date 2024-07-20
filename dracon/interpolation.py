import ast
from asteval import Interpreter
import re
from typing import Any, Dict, Callable, Optional, Tuple, List, TypeVar, Generic, ForwardRef
from typing import Generic, TypeVar, get_args
from dracon.keypath import KeyPath, ROOTPATH
from dracon.utils import DictLike, ListLike
from pydantic.dataclasses import dataclass
from pydantic import TypeAdapter


class InterpolationError(Exception):
    pass


## {{{                       --     find keypaths     --
@dataclass
class KeypathMatch:
    start: int
    end: int
    expr: str


NOT_ESCAPED_REGEX = r"(?<!\\)(?:\\\\)*"
INVALID_KEYPATH_CHARS = r'[]() ,:=+-*%<>!&|^~@#$?;{}"\'`'
KEYPATH_START_CHAR = "@"
SPECIAL_KEYPATH_CHARS = './\\'  # Added backslash to handle escaping of itself


def find_keypaths(expr: str) -> List[KeypathMatch]:
    # Regex pattern to match keypaths
    pattern = (
        f"{NOT_ESCAPED_REGEX}{KEYPATH_START_CHAR}([^{re.escape(INVALID_KEYPATH_CHARS)}]|(?:\\\\.))*"
    )

    matches = []
    for match in re.finditer(pattern, expr):
        start, end = match.span()
        keypath = match.group()

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

        matches.append(KeypathMatch(start, end, cleaned_keypath[1:]))

    return matches


def resolve_keypath(expr: str):
    keypath_matches = find_keypaths(expr)
    if not keypath_matches:
        return expr
    PREPEND = "(__DRACON__PARENT_PATH + __dracon_KeyPath('"
    APPEND = "')).get_obj(__DRACON__CURRENT_ROOT_OBJ)"
    offset = 0
    for match in keypath_matches:
        newexpr = PREPEND + match.expr + APPEND
        expr = expr[: match.start + offset] + newexpr + expr[match.end + offset :]
        original_len = match.end - match.start
        offset += len(newexpr) - original_len
    return expr


##────────────────────────────────────────────────────────────────────────────}}}


## {{{                    --     interpolation exprs     --
@dataclass
class InterpolationMatch:
    start: int
    end: int
    expr: str


def outermost_interpolation_exprs(text: str) -> List[InterpolationMatch]:
    # match all ${...} expressions
    matches = list(re.finditer(r"\${[^}]+}", text))
    return [InterpolationMatch(m.start(), m.end(), m.group(0)[2:-1]) for m in matches]


def find_first_occurence(expr, *substrings) -> Optional[int]:
    pat = re.compile("|".join([NOT_ESCAPED_REGEX + re.escape(s) for s in substrings]))
    match = pat.search(expr)
    if match is None:
        return None
    else:
        return match.start()


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                           --     eval     --


def do_safe_eval(expr: str, symbols: Optional[dict] = None):
    expr = resolve_keypath(expr)
    print(f'evaluating: {expr}')
    safe_eval = Interpreter(user_symbols=symbols or {}, max_string_length=1000)
    return safe_eval(expr)


def resolve_eval_str(
    expr: str,
    current_path: str | KeyPath = '/',
    root_obj: Any = None,
    allow_recurse: int = 2,
    init_outermost_interpolations: Optional[List[InterpolationMatch]] = None,
) -> Any:
    interpolations = init_outermost_interpolations
    if init_outermost_interpolations is None:
        interpolations = outermost_interpolation_exprs(expr)

    if isinstance(current_path, str):
        current_path = KeyPath(current_path)

    symbols = {
        "__DRACON__CURRENT_PATH": current_path,
        "__DRACON__PARENT_PATH": current_path.parent,
        "__DRACON__CURRENT_ROOT_OBJ": root_obj,
        "__dracon_KeyPath": KeyPath,
    }

    endexpr = None
    if not interpolations:
        return expr

    elif (
        len(interpolations) == 1
        and interpolations[0].start == 0
        and interpolations[0].end == len(expr)
    ):
        endexpr = do_safe_eval(interpolations[0].expr, symbols)

    else:
        offset = 0
        for match in interpolations:  # will be returned as a concatenation of strings
            newexpr = str(
                do_safe_eval(
                    resolve_eval_str(
                        match.expr, current_path, root_obj, allow_recurse=allow_recurse
                    ),
                    symbols,
                )
            )
            expr = expr[: match.start + offset] + newexpr + expr[match.end + offset :]
            original_len = match.end - match.start
            offset += len(newexpr) - original_len
        endexpr = str(expr)

    if allow_recurse != 0 and isinstance(endexpr, str):
        return resolve_eval_str(endexpr, current_path, root_obj, allow_recurse=allow_recurse - 1)

    return endexpr


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                     --     LazyInterpolable     --

T = TypeVar('T')


class LazyInterpolable(Generic[T]):
    def __init__(
        self,
        expr: str,
        current_path: KeyPath = ROOTPATH,
        root_obj: Any = None,
        init_outermost_interpolations: Optional[List[InterpolationMatch]] = None,
        type_tag: Optional[str] = None,
    ):
        self.expr = expr
        self.current_path = current_path
        self.root_obj = root_obj
        self.init_outermost_interpolations = (
            init_outermost_interpolations  # to cache the result of the first parsing
        )
        self.type_tag = type_tag
        self.name = None

    def __get__(self, owner_instance, owner_type=None):

        if self.type_tag is None:
            t = get_args(self.__orig_class__)[0] # type: ignore
        else:
            t = ForwardRef(self.type_tag)

        if owner_instance is None:
            return self

        if hasattr(owner_instance, '_dracon_root_obj'):
            self.root_obj = owner_instance._dracon_root_obj
            assert hasattr(
                owner_instance, '_dracon_current_path'
            ), f"Instance {owner_instance} has no current path"
            self.current_path = owner_instance._dracon_current_path + self.name

        value = resolve_eval_str(
            self.expr,
            self.current_path,
            self.root_obj,
            init_outermost_interpolations=self.init_outermost_interpolations,
        )

        constructed_value = TypeAdapter(t).validate_python(value)
        setattr(owner_instance, self.name, constructed_value)
        return constructed_value

    def __set_name__(self, owner, name):
        self.name = name
        if hasattr(owner, '_dracon_lazy_interpolables'):
            owner._dracon_lazy_interpolables.append(self)


##────────────────────────────────────────────────────────────────────────────}}}

