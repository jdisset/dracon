from typing import (
    Any,
    Dict,
    Callable,
    Optional,
    List,
    TypeVar,
    Generic,
    Annotated,
    Protocol,
    runtime_checkable,
)
from dracon.keypath import KeyPath, ROOTPATH, MAPPING_KEY
from pydantic import BaseModel, field_validator, ConfigDict, WrapValidator, Field
from dracon.interpolation_utils import (
    InterpolationMatch,
)
from dracon.interpolation import evaluate_expression, InterpolationError, DraconError
from dracon.utils import list_like, dict_like

import inspect

import logging

logger = logging.getLogger(__name__)

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
                raise InterpolationError(
                    f"Failed to lazyly validate attribute {quoted_name}: {e}"
                ) from None
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
        engine: str = 'asteval',
        context: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(value, validator, name)

        self.context = context
        self.current_path = current_path
        self.root_obj = root_obj
        self.init_outermost_interpolations = init_outermost_interpolations
        self.permissive = permissive
        self.engine = engine
        if not self.permissive:
            assert isinstance(value, (str, tuple)), (
                f"LazyInterpolable expected string, got {type(value)}. Did you mean to contruct with permissive=True?"
            )

    def __getstate__(self):
        """Get the object's state for pickling."""
        state = {
            'value': self.value,
            'name': self.name,
            'current_path': self.current_path,
            'permissive': self.permissive,
            'context': self.context,
            'engine': self.engine,
            'init_outermost_interpolations': self.init_outermost_interpolations
            if self.init_outermost_interpolations
            else None,
        }

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
            engine=state['engine'],
            context=state['context'],
            validator=None,  # Validator will be reattached by the owner if needed
        )

    def __repr__(self):
        return f"LazyInterpolable({self.value})"

    def resolve(self, context_override=None) -> T:
        if isinstance(self.value, str):
            try:
                ctx = self.context if self.context is not None else {}
                if context_override is not None:
                    ctx.update(context_override)
                self.value = evaluate_expression(
                    self.value,
                    self.current_path,
                    self.root_obj,
                    init_outermost_interpolations=self.init_outermost_interpolations,
                    engine=self.engine,
                    context=ctx,
                )
            except Exception as e:
                raise type(e)(f"Error resolving lazy value \"{self.value}\": {str(e)}") from None

        return self.validate(self.value)

    def get(self, owner_instance, setval=False):
        """Get the value of the lazy object, and optionally set it as an attribute of the owner instance."""
        if hasattr(owner_instance, '_dracon_root_obj'):
            self.root_obj = owner_instance._dracon_root_obj
            assert hasattr(owner_instance, '_dracon_current_path'), (
                f"Instance {owner_instance} has no current path"
            )
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


def num_array_like(obj):
    return hasattr(obj, 'dtype') and hasattr(obj, 'shape') and hasattr(obj, 'ndim')


def resolve_single_key(path, key, root, context_override=None):
    """resolve a single lazy key and return info about the transformation"""
    parent_path = path.parent

    try:
        parent = parent_path.get_obj(root)
        key.root_obj = root
        key.current_path = path.removed_mapping_key()

        resolved_key = key.resolve(context_override=context_override)
        if not isinstance(resolved_key, (str, int, float, bool)):
            resolved_key = str(resolved_key)

        original_lazy_key_object = None
        for k_in_parent in parent.keys():
            if id(k_in_parent) == id(key) or (
                isinstance(k_in_parent, LazyInterpolable) and k_in_parent.value == key.value
            ):
                original_lazy_key_object = k_in_parent
                break

        if original_lazy_key_object is None:
            logger.warning(
                f"Lazy key {key!r} not found as object in parent keys at {parent_path}: {list(parent.keys())}"
            )
            if resolved_key in parent:
                return False, None
            logger.error(f"Lazy key {key!r} truly missing from parent {parent_path}.")
            return False, None

        if (
            resolved_key != str(original_lazy_key_object.value)
            or original_lazy_key_object in parent
        ):
            try:
                value = parent[original_lazy_key_object]
                logger.debug(f"Got value associated with lazy key: {type(value)}")

                if original_lazy_key_object in parent:
                    del parent[original_lazy_key_object]

                parent[resolved_key] = value

                if hasattr(parent, '_recompute_map'):
                    parent._recompute_map()

                # return transformation info only if a structural change occurred
                old_path = parent_path.down(MAPPING_KEY).down(str(original_lazy_key_object.value))
                new_path = parent_path.down(str(resolved_key))
                return True, (old_path, new_path)

            except KeyError:
                logger.error(
                    f"KeyError trying to access/delete lazy key {original_lazy_key_object!r} even after finding it."
                )
                return False, None
            except Exception as e_inner:
                logger.error(f"Error during key update for {path}: {e_inner}", exc_info=True)
                return False, None
        else:
            logger.debug(
                f"Resolved key '{resolved_key}' is same as lazy value representation. No update needed."
            )
            return True, None  # indicate success but no transformation

    except Exception as e:
        import traceback

        logger.error(f"Error resolving key {key} at {path}: {e}\n{traceback.format_exc()}")
        return False, None


def resolve_single_value(path, value, root, context_override=None):
    """resolve a single lazy value"""
    try:
        parent = path.parent.get_obj(root)
        value.root_obj = root
        value.current_path = path

        resolved_value = value.resolve(context_override=context_override)

        stem = path.stem
        if stem == '/' or stem == ROOTPATH:
            return False  # indicate no action taken here

        set_val(parent, stem, resolved_value)
        return True

    except Exception as e:
        import traceback

        logger.debug(f"error resolving value {value} at {path}: {e}\n{traceback.format_exc()}")
        return False


def set_val(parent: Any, key, value: Any) -> None:
    if list_like(parent):
        parent[int(key)] = value
    elif isinstance(parent, BaseModel):
        # handle pydantic models specifically
        setattr(parent, key, value)
    elif hasattr(parent, key):
        setattr(parent, key, value)
    else:
        try:
            parent[key] = value
        except TypeError:
            try:
                # last fallback: try setting attribute anyway
                setattr(parent, key, value)
            except AttributeError:
                raise AttributeError(f'Could not set attribute {key} in {parent}') from None


def collect_lazy_by_depth(obj, path=ROOTPATH, seen=None):
    """collect all lazy objects grouped by depth"""
    if seen is None:
        seen = set()

    lazy_keys_by_depth = {}  # depth -> list of (path, lazy_key)
    lazy_values = []  # list of (path, lazy_value)

    def _collect(o, p, seen_set):
        # skip None values and class types
        if o is None or isinstance(o, type):
            return

        obj_id = id(o)
        if obj_id in seen_set:
            return
        seen_set.add(obj_id)

        depth = len(p)

        # handle LazyInterpolable directly
        if isinstance(o, LazyInterpolable):
            if p.is_mapping_key():
                if depth not in lazy_keys_by_depth:
                    lazy_keys_by_depth[depth] = []
                lazy_keys_by_depth[depth].append((p, o))
            else:
                lazy_values.append((p, o))
            return

        # handle dict-like objects
        if dict_like(o):
            for k, v in list(o.items()):
                if isinstance(k, LazyInterpolable):
                    key_path = p.copy().down(MAPPING_KEY).down(str(k))
                    if depth not in lazy_keys_by_depth:
                        lazy_keys_by_depth[depth] = []
                    lazy_keys_by_depth[depth].append((key_path, k))

                value_path = p.copy().down(str(k))
                _collect(v, value_path, seen_set)

        # handle list-like objects (excluding strings, bytes, and numeric arrays)
        elif list_like(o) and not isinstance(o, (str, bytes, type)) and not num_array_like(o):
            try:
                # Double-check that we can actually enumerate this object
                for i, item in enumerate(o):
                    item_path = p.copy().down(str(i))
                    _collect(item, item_path, seen_set)
            except TypeError:
                pass

        # handle Pydantic models
        elif isinstance(o, BaseModel):
            # access model's fields directly through __dict__ to get raw values
            for field_name, field_value in o.__dict__.items():
                # skip private attributes and special pydantic fields
                if field_name.startswith('_'):
                    continue

                item_path = p.copy().down(field_name)
                _collect(field_value, item_path, seen_set)

        # handle other objects with attributes
        elif hasattr(o, '__dict__') and not isinstance(o, (str, int, float, bool, bytes, type)):
            # skip traversing built-in types and callables
            if (
                o.__class__.__module__ in ('builtins', '__builtin__')
                or callable(o)
                or inspect.isclass(o)
                or inspect.ismodule(o)
            ):
                return

            try:
                # get object attributes
                for attr_name, attr_value in vars(o).items():
                    # skip private attributes, methods, and special attributes
                    if (
                        attr_name.startswith('_')
                        or callable(attr_value)
                        or attr_name in {'__dict__', '__weakref__'}
                    ):
                        continue

                    attr_path = p.copy().down(attr_name)
                    _collect(attr_value, attr_path, seen_set)
            except (TypeError, ValueError, AttributeError) as e:
                logger.debug(
                    f"Error accessing attributes of object {o} at path {p}: {e}. Skipping."
                )
                pass

    _collect(obj, path, seen)
    return lazy_keys_by_depth, lazy_values


def resolve_all_lazy(
    obj,
    root_obj=None,
    current_path=None,
    visited_ids=None,
    context_override=None,
    max_passes=20,
):
    """Resolves all lazy objects in a multi-pass approach by depth level."""
    if visited_ids is None:
        visited_ids = set()

    obj_id = id(obj)
    if obj_id in visited_ids:
        return obj
    visited_ids.add(obj_id)

    if root_obj is None:
        root_obj = obj if not hasattr(obj, '_dracon_root_obj') else obj._dracon_root_obj

    if current_path is None:
        current_path = (
            ROOTPATH if not hasattr(obj, '_dracon_current_path') else obj._dracon_current_path
        )

    # handle case where the root object itself is lazy
    if isinstance(obj, LazyInterpolable) and current_path == ROOTPATH:
        try:
            obj.root_obj = root_obj  # ensure root is set
            resolved_root = obj.resolve(context_override=context_override)
            return resolve_all_lazy(
                resolved_root, root_obj, current_path, set(), context_override, max_passes - 1
            )
        except Exception as e:
            logger.warning(f"Error resolving root lazy object: {e}")
            return obj

    resolved_something_in_last_pass = True
    pass_num = 0
    while resolved_something_in_last_pass and pass_num < max_passes:
        resolved_something_in_last_pass = False
        pass_num += 1

        lazy_keys_by_depth, lazy_values = collect_lazy_by_depth(obj, current_path, seen=set())

        if not lazy_keys_by_depth and not lazy_values:
            break

        keys_resolved_this_pass = 0
        values_resolved_this_pass = 0
        keys_transformed = False

        # resolve keys by depth (shallowest first)
        depths = sorted(lazy_keys_by_depth.keys())
        if depths:
            current_depth = depths[0]
            keys_to_resolve = lazy_keys_by_depth.get(current_depth, [])
            for path, key in keys_to_resolve:
                success, transform = resolve_single_key(path, key, root_obj, context_override)
                if success:
                    keys_resolved_this_pass += 1
                    if transform:  # checks if path structure actually changed
                        keys_transformed = True

        if not keys_transformed:
            for path, value in lazy_values:
                success = resolve_single_value(path, value, root_obj, context_override)
                if success:
                    values_resolved_this_pass += 1

        if keys_resolved_this_pass > 0 or values_resolved_this_pass > 0:
            resolved_something_in_last_pass = True

    if pass_num == max_passes and resolved_something_in_last_pass:
        _, remaining_values = collect_lazy_by_depth(obj, current_path, seen=set())
        remaining_keys_by_depth, _ = collect_lazy_by_depth(obj, current_path, seen=set())
        if remaining_values or remaining_keys_by_depth:
            logger.warning(
                f"Max passes ({max_passes}) reached during resolve_all_lazy, potentially unresolved lazy objects remain."
            )

    visited_ids.remove(obj_id)
    return obj


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
