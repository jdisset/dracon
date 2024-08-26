import ast
import regex
import pyparsing as pp
import collections.abc as cabc
from asteval import Interpreter
import re
from typing import (
    Any,
    Dict,
    Callable,
    Optional,
    Tuple,
    List,
    TypeVar,
    Generic,
    ForwardRef,
    Annotated,
)
from typing import Generic, TypeVar, get_args
from dracon.keypath import KeyPath, ROOTPATH
from dracon.utils import DictLike, ListLike
from pydantic.dataclasses import dataclass
from pydantic import TypeAdapter, BaseModel, field_validator, ConfigDict, WrapValidator, Field
from copy import copy
from typing import Protocol, runtime_checkable, Optional


class InterpolationError(Exception):
    pass


## {{{                       --     find keypaths     --

# Find all keypaths in an expression string and replace them with a function call


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

## {{{                --     find interpolable variables     --

# an interpolable variable is a special $VARIABLE defined by dracon (or the user)
# they are immmediately replaced by their value when found in the expression string
# pattern is $ + CAPITAL_LETTER + [a-zA-Z0-9_]


@dataclass
class VarMatch:
    start: int
    end: int
    varname: str


def find_interpolable_variables(expr: str) -> List[VarMatch]:
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

## {{{                    --     interpolation exprs     --


@dataclass
class InterpolationMatch:
    start: int
    end: int
    expr: str


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
) -> List[InterpolationMatch]:
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

## {{{                      --     base functions and symbols   --

BASE_DRACON_SYMBOLS: Dict[str, Any] = {}

##────────────────────────────────────────────────────────────────────────────}}}

## {{{                           --     eval     --


def preprocess_expr(expr: str, symbols: Optional[dict] = None):
    expr = resolve_keypath(expr)
    expr = resolve_interpolable_variables(expr, symbols or {})
    return expr


def do_safe_eval(expr: str, symbols: Optional[dict] = None):
    expr = preprocess_expr(expr, symbols)
    safe_eval = Interpreter(user_symbols=symbols or {}, max_string_length=1000)
    return safe_eval(expr)


def resolve_eval_str(
    expr: str,
    current_path: str | KeyPath = '/',
    root_obj: Any = None,
    allow_recurse: int = 2,
    init_outermost_interpolations: Optional[List[InterpolationMatch]] = None,
    extra_symbols: Optional[Dict[str, Any]] = None,
) -> Any:
    interpolations = init_outermost_interpolations
    if init_outermost_interpolations is None:
        interpolations = outermost_interpolation_exprs(expr)

    if interpolations is None:
        return expr

    if isinstance(current_path, str):
        current_path = KeyPath(current_path)

    symbols = copy(BASE_DRACON_SYMBOLS)
    symbols.update(
        {
            "__DRACON__CURRENT_PATH": current_path,
            "__DRACON__PARENT_PATH": current_path.parent,
            "__DRACON__CURRENT_ROOT_OBJ": root_obj,
            "__dracon_KeyPath": KeyPath,
        }
    )
    symbols.update(extra_symbols or {})

    endexpr = None
    if not interpolations:
        return expr

    elif (
        len(interpolations) == 1
        and interpolations[0].start == 0
        and interpolations[0].end == len(expr)
    ):
        print(f"Match: {interpolations[0]}")
        expr = interpolations[0].expr
        endexpr = do_safe_eval(
            str(resolve_eval_str(expr, current_path, root_obj, allow_recurse=allow_recurse)),
            symbols,
        )
    else:
        offset = 0
        for match in interpolations:  # will be returned as a concatenation of strings
            print(f"Match: {match}")
            newexpr = str(
                do_safe_eval(
                    str(
                        resolve_eval_str(
                            match.expr, current_path, root_obj, allow_recurse=allow_recurse
                        )
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


class Lazy(Generic[T]):
    def __init__(
        self, value: Any = None, validator: Optional[Callable[[Any], Any]] = None, name=None
    ):
        self.value = value
        self.validator = validator
        self.name = name

    def validate(self, value):
        if self.validator is not None:
            try:
                return self.validator(value)
            except Exception as e:
                quoted_name = f' "{self.name}"' if self.name else ''
                raise InterpolationError(f"Failed to lazyly validate attribute{quoted_name}") from e
        return value

    def resolve(self) -> T:
        return self.validate(self.value)

    def get(self, owner_instance, setval=False):
        newval = self.resolve()
        if setval:
            setattr(owner_instance, self.name, newval)
        return newval

    def __set_name__(self, owner, name):
        self.name = name


class LazyInterpolable(Lazy[T]):
    """
    A lazy object that can be resolved (i.e. interpolated) to a value when needed.

    """

    def __init__(
        self,
        value: Any,
        validator: Optional[Callable[[Any], Any]] = None,
        name=None,
        current_path: KeyPath = ROOTPATH,
        root_obj: Any = None,
        init_outermost_interpolations: Optional[List[InterpolationMatch]] = None,
        permissive: bool = False,
        extra_symbols: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(value, validator, name)

        self.extra_symbols = extra_symbols
        self.current_path = current_path
        self.root_obj = root_obj
        self.init_outermost_interpolations = (
            init_outermost_interpolations  # to cache the result of the first parsing
        )
        self.permissive = permissive
        if not self.permissive:
            assert isinstance(
                value, (str, tuple)
            ), f"LazyInterpolable expected string, got {type(value)}. Did you mean to contruct with permissive=True?"

    def resolve(self) -> T:
        if isinstance(self.value, str):
            self.value = resolve_eval_str(
                self.value,
                self.current_path,
                self.root_obj,
                init_outermost_interpolations=self.init_outermost_interpolations,
                extra_symbols=self.extra_symbols,
            )

        return self.validate(self.value)

    def get(self, owner_instance, setval=False):
        """Get the value of the lazy object, and optionally set it as an attribute of the owner instance."""
        if hasattr(owner_instance, '_dracon_root_obj'):
            self.root_obj = owner_instance._dracon_root_obj
            assert hasattr(
                owner_instance, '_dracon_current_path'
            ), f"Instance {owner_instance} has no current path"
            self.current_path = owner_instance._dracon_current_path + self.name

        newval = self.resolve()
        if setval:
            setattr(owner_instance, self.name, newval)

        return newval


##────────────────────────────────────────────────────────────────────────────}}}


def recursive_update_lazy_container(obj, root_obj, current_path):
    if is_lazy_compatible(obj):
        obj._dracon_root_obj = root_obj
        obj._dracon_current_path = current_path

    if isinstance(obj, cabc.Mapping):  # also handles pydantic models
        for key, value in obj.items():
            new_path = current_path + KeyPath(str(key))
            recursive_update_lazy_container(value, root_obj, new_path)

    elif isinstance(obj, cabc.Iterable) and not isinstance(obj, (str, bytes)):
        for i, item in enumerate(obj):
            new_path = current_path + KeyPath(str(i))
            recursive_update_lazy_container(item, root_obj, new_path)


@runtime_checkable
class LazyCapable(Protocol):
    """
    A protocol for objects that can hold lazy values and resolve them
    even if they have relative and absolute keypath references.

    For example, a field like "${.name}" should be resolved to the value of the
    "name" field of the current object, while "${/sub.name}" should be resolved
    to the value of root_obj["sub"]["name"].

    For that to work, the object must have the following attributes:

    """

    _dracon_root_obj: Any  # The root object from which to resolve absolute keypaths
    _dracon_current_path: str  # The current path of the object in the root object


def is_lazy_compatible(v: Any) -> bool:
    return isinstance(v, LazyCapable)


def wrap_lazy_validator(v: Any, handler, info) -> Any:
    return Lazy(v, validator=handler, name=info.field_name)


LazyVal = Annotated[
    T | Lazy[T],
    WrapValidator(wrap_lazy_validator),
    Field(validate_default=True),
]


class LazyDraconModel(BaseModel):
    _dracon_root_obj: Optional[Any] = None
    _dracon_current_path: KeyPath = ROOTPATH

    def _update_lazy_container_attributes(self, root_obj, current_path, recurse=True):
        """
        Update the lazy attributes of the model with the root object and current path.
        """
        self._dracon_root_obj = root_obj
        self._dracon_current_path = current_path
        if recurse:
            for key, value in self.__dict__.items():
                if is_lazy_compatible(value):
                    new_path = current_path + KeyPath(str(key))
                    value._update_lazy_container_attributes(root_obj, new_path, recurse=True)

    model_config = ConfigDict(arbitrary_types_allowed=True, validate_default=True)

    @field_validator("*", mode="wrap")
    @classmethod
    def ignore_lazy(cls, v, handler, info):
        if isinstance(v, Lazy):
            if v.validator is None:
                v.validator = handler
            return v
        return handler(v, info)

    def __getattribute__(self, name):
        attr = super().__getattribute__(name)
        if isinstance(attr, Lazy):
            attr.__set_name__(self, name)
            return attr.__get__(self)
        # if it's a list or tuple of Lazy, resolve them
        if isinstance(attr, (list, tuple)):
            for i, item in enumerate(attr):
                if isinstance(item, Lazy):
                    item.name = f'{name}.{i}'
                    attr[i] = item.resolve()
            setattr(self, name, attr)
        return attr
