import collections.abc as cabc
from typing import (
    Any,
    Dict,
    Callable,
    Optional,
    List,
    TypeVar,
    Generic,
    Annotated,
)
from typing import Generic, TypeVar, get_args, get_origin, Literal
from dracon.keypath import KeyPath, ROOTPATH, MAPPING_KEY
from pydantic import TypeAdapter, BaseModel, field_validator, ConfigDict, WrapValidator, Field
from typing import Protocol, runtime_checkable, Optional
from dracon.interpolation_utils import (
    InterpolationMatch,
)
from dracon.interpolation import evaluate_expression
from dracon.utils import list_like, dict_like, ftrace


class InterpolationError(Exception):
    pass


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


T = TypeVar('T')


class LazyInterpolable(Lazy[T]):
    """A lazy object that can be resolved (i.e. interpolated) to a value when needed."""

    def __init__(
        self,
        value: Any,
        validator: Optional[Callable[[Any], Any]] = None,
        name=None,
        current_path: KeyPath = ROOTPATH,
        root_obj: Any = None,
        init_outermost_interpolations: Optional[List[InterpolationMatch]] = None,
        permissive: bool = False,
        context: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(value, validator, name)

        self.context = context
        self.current_path = current_path
        self.root_obj = root_obj
        self.init_outermost_interpolations = init_outermost_interpolations
        self.permissive = permissive
        if not self.permissive:
            assert isinstance(
                value, (str, tuple)
            ), f"LazyInterpolable expected string, got {type(value)}. Did you mean to contruct with permissive=True?"


    def __getstate__(self):
        """Get the object's state for pickling."""
        state = {
            'value': self.value,
            'name': self.name,
            'current_path': self.current_path,
            'permissive': self.permissive,
            'context': self.context,
            # Store init_outermost_interpolations if it's picklable
            'init_outermost_interpolations': self.init_outermost_interpolations
            if self.init_outermost_interpolations
            else None,
        }

        # Handle root_obj specially if needed
        if hasattr(self.root_obj, '__getstate__'):
            state['root_obj'] = self.root_obj
        else:
            state['root_obj'] = None  # Will be reattached after unpickling

        # Don't pickle the validator function - it will be reattached by the owner
        return state

    def __setstate__(self, state):
        """Restore the object's state after unpickling."""
        # Initialize with default values
        self.__init__(
            value=state['value'],
            name=state['name'],
            current_path=state['current_path'],
            root_obj=state['root_obj'],
            init_outermost_interpolations=state['init_outermost_interpolations'],
            permissive=state['permissive'],
            context=state['context'],
            validator=None,  # Validator will be reattached by the owner if needed
        )

    def __repr__(self):
        return f"LazyInterpolable({self.value})"

    def resolve(self) -> T:
        if isinstance(self.value, str):
            self.value = evaluate_expression(
                self.value,
                self.current_path,
                self.root_obj,
                init_outermost_interpolations=self.init_outermost_interpolations,
                context=self.context,
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

    def reattach_validator(self, validator: Optional[Callable[[Any], Any]]):
        """Reattach a validator after unpickling."""
        self._validator = validator


##────────────────────────────────────────────────────────────────────────────}}}

## {{{                     --     resolve all lazy     --


def set_val(parent: Any, key, value: Any) -> None:
    if list_like(parent):
        parent[int(key)] = value
    elif hasattr(parent, key):
        setattr(parent, key, value)
    else:
        try:
            parent[key] = value
        except TypeError:
            raise AttributeError(f'Could not set attribute {key} in {parent}')


def num_array_like(obj):
    return hasattr(obj, 'dtype') and hasattr(obj, 'shape') and obj.dtype.kind in 'iuf'


@ftrace()
def resolve_all_lazy(obj, root_obj=None, current_path=None):
    """will do its best to resolve all lazy objects in the object"""

    if root_obj is None:
        if hasattr(obj, '_dracon_root_obj'):  # if the object has a root object, use that
            root_obj = obj._dracon_root_obj
        else:
            root_obj = obj
    if current_path is None:
        if hasattr(obj, '_dracon_current_path'):
            current_path = obj._dracon_current_path
        else:
            current_path = ROOTPATH

    # recursively call resolve_all_lazy on all items in the object (including keys in mappings)
    if isinstance(obj, BaseModel):
        for key, value in obj:
            resolve_all_lazy(value, root_obj, current_path + KeyPath(str(key)))

    elif dict_like(obj):
        for key, value in obj.items():
            resolve_all_lazy(key, root_obj, current_path + MAPPING_KEY + str(key))
            resolve_all_lazy(value, root_obj, current_path + key)

    elif list_like(obj) and not isinstance(obj, (str, bytes)) and not num_array_like(obj):
        for i, item in enumerate(obj):
            resolve_all_lazy(item, root_obj, current_path + KeyPath(str(i)))

    # now check if we have a lazy interpolable object
    elif isinstance(obj, LazyInterpolable):
        if current_path.is_mapping_key():
            raise NotImplementedError("Lazy objects in key mappings are not supported")
        parent = current_path.parent.get_obj(root_obj)
        obj.root_obj = root_obj
        obj.current_path = current_path
        val = obj.resolve()
        set_val(parent, current_path.stem, val)
        # recurse (if the value is itself a lazy object or contain lazy objects)
        resolve_all_lazy(current_path.get_obj(root_obj), root_obj, current_path)


##────────────────────────────────────────────────────────────────────────────}}}

## {{{              --     recursive lazy container update     --


def recursive_update_lazy_container(obj, root_obj, current_path):
    """
    Recursively update the root and current path of all nested lazy objects,
    so that later they can be interpolated correctly.
    """
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


##────────────────────────────────────────────────────────────────────────────}}}


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
