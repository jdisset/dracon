import ast
import collections.abc as cabc
from asteval import Interpreter
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
from typing import Generic, TypeVar, get_args, get_origin, Literal
from dracon.keypath import KeyPath, ROOTPATH
from pydantic.dataclasses import dataclass
from pydantic import TypeAdapter, BaseModel, field_validator, ConfigDict, WrapValidator, Field
from copy import copy
from typing import Protocol, runtime_checkable, Optional
from dracon.merge import merged, MergeKey
from dracon.utils import (
    outermost_interpolation_exprs,
    InterpolationMatch,
    resolve_field_references,
    resolve_interpolable_variables,
)


class InterpolationError(Exception):
    pass


## {{{                      --     base functions and symbols   --

BASE_DRACON_SYMBOLS: Dict[str, Any] = {}

##────────────────────────────────────────────────────────────────────────────}}}

## {{{                           --     eval     --


def preprocess_expr(expr: str, symbols: Optional[dict] = None):
    expr = resolve_field_references(expr)
    expr = resolve_interpolable_variables(expr, symbols or {})
    return expr


def do_safe_eval(expr: str, symbols: Optional[dict] = None):
    expr = preprocess_expr(expr, symbols)
    safe_eval = Interpreter(user_symbols=symbols or {}, max_string_length=1000)
    return safe_eval.eval(expr, raise_errors=True)


def resolve_eval_str(
    expr: str,
    current_path: str | KeyPath = '/',
    root_obj: Any = None,
    allow_recurse: int = 5,
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

    def recurse_lazy_resolve(expr):
        if isinstance(expr, Lazy):
            expr.current_path = current_path
            expr.root_obj = root_obj
            expr.extra_symbols = merged(expr.extra_symbols, extra_symbols, MergeKey(raw='{<+}'))
            expr = expr.resolve()
        return expr

    endexpr = None
    if not interpolations:
        return expr

    elif (
        len(interpolations) == 1
        and interpolations[0].start == 0
        and interpolations[0].end == len(expr)
    ):
        expr = interpolations[0].expr
        endexpr = do_safe_eval(
            str(
                resolve_eval_str(
                    expr,
                    current_path,
                    root_obj,
                    allow_recurse=allow_recurse,
                    extra_symbols=extra_symbols,
                )
            ),
            symbols,
        )

        endexpr = recurse_lazy_resolve(endexpr)

    else:
        offset = 0
        for match in interpolations:  # will be returned as a concatenation of strings
            newexpr = do_safe_eval(
                str(
                    resolve_eval_str(
                        match.expr,
                        current_path,
                        root_obj,
                        allow_recurse=allow_recurse,
                        extra_symbols=extra_symbols,
                    )
                ),
                symbols,
            )

            newexpr = str(recurse_lazy_resolve(newexpr))
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

    def __repr__(self):
        return f"LazyInterpolable({self.value})"

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
