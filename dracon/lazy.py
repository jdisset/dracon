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
from dracon.interpolation import evaluate_expression, InterpolationError, DraconError
from dracon.utils import list_like, dict_like, ftrace, deepcopy
from dracon.interpolation_utils import find_field_references


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
            try:
                self.value = evaluate_expression(
                    self.value,
                    self.current_path,
                    self.root_obj,
                    init_outermost_interpolations=self.init_outermost_interpolations,
                    context=self.context,
                )
            except InterpolationError as e:
                raise InterpolationError(
                    f"Error at path {self.current_path}: {e.message}", traceback=e.traceback
                ) from e
            except Exception as e:
                raise type(e)("Error resolving lazy value") from e

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


def resolve_all_lazy(
    obj, root_obj=None, current_path=None, visited=None, iteration=0, max_iterations=5
):
    """
    Resolves all lazy objects in the object using breadth-first traversal.
    Added iteration limit and verification to ensure all lazy values are resolved.
    """

    if visited is None:
        visited = set()

    if root_obj is None:
        if hasattr(obj, '_dracon_root_obj'):
            root_obj = obj._dracon_root_obj
        else:
            root_obj = obj

    if current_path is None:
        if hasattr(obj, '_dracon_current_path'):
            current_path = obj._dracon_current_path
        else:
            current_path = ROOTPATH

    unresolved_count = 0

    from collections import deque

    queue = deque([(obj, current_path)])

    while queue:
        current_obj, path = queue.popleft()
        obj_id = id(current_obj)

        if obj_id in visited:
            continue

        visited.add(obj_id)

        try:
            if isinstance(current_obj, LazyInterpolable):
                if path.is_mapping_key():
                    raise NotImplementedError("Lazy objects in key mappings are not supported")
                parent = path.parent.get_obj(root_obj)
                current_obj.root_obj = root_obj
                current_obj.current_path = path
                try:
                    val = current_obj.resolve()
                except InterpolationError as e:
                    # Add path context to the message but preserve the original error
                    raise type(e)(f"Error at path {path}: {str(e)}") from None
                stem = path.stem
                if stem == '/' or stem == ROOTPATH:
                    raise ValueError("Cannot resolve root path")
                set_val(parent, stem, val)
                unresolved_count += 1
                # Get the resolved object for further processing
                current_obj = path.get_obj(root_obj)

            if isinstance(current_obj, BaseModel):
                for key, value in current_obj:
                    child_path = path + KeyPath(str(key))
                    queue.append((value, child_path))

            elif dict_like(current_obj):
                for key, value in current_obj.items():
                    key_path = path + MAPPING_KEY + str(key)
                    value_path = path + KeyPath(str(key))
                    queue.append((key, key_path))
                    queue.append((value, value_path))

            elif (
                list_like(current_obj)
                and not isinstance(current_obj, (str, bytes))
                and not num_array_like(current_obj)
            ):
                for i, item in enumerate(current_obj):
                    item_path = path + KeyPath(str(i))
                    queue.append((item, item_path))

        except InterpolationError as e:
            raise  # Pass through without wrapping
        except Exception as e:
            raise DraconError(f"Error resolving {path}: {str(e)}") from None

    # a bit hacky, but some resolutions trigger new lazy values in unexpected places, so, we recurse
    if unresolved_count > 0 and iteration < max_iterations:
        resolve_all_lazy(obj, root_obj, current_path, None, iteration + 1, max_iterations)


##────────────────────────────────────────────────────────────────────────────}}}

## {{{              --     recursive lazy container update     --


def recursive_update_lazy_container(obj, root_obj, current_path, seen=None):
    """
    Recursively update the root object and current path of all nested lazy objects.
    """

    if seen is None:
        seen = set()

    obj_id = id(obj)
    if obj_id in seen:
        return  # skip already processed objects to break cycles
    seen.add(obj_id)

    if is_lazy_compatible(obj):
        obj._dracon_root_obj = root_obj
        obj._dracon_current_path = current_path

    if dict_like(obj):
        for key, value in obj.items():
            new_path = current_path + str(key)
            recursive_update_lazy_container(value, root_obj, new_path, seen)

    elif list_like(obj) and not isinstance(obj, (str, bytes)) and not num_array_like(obj):
        for i, item in enumerate(obj):
            new_path = current_path + str(i)
            recursive_update_lazy_container(item, root_obj, new_path, seen)


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
