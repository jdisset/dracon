# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

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
    Type,
    get_args,
)
from dracon.keypath import KeyPath, ROOTPATH, MAPPING_KEY
from pydantic import (
    BaseModel,
    field_validator,
    ConfigDict,
    WrapValidator,
    Field,
    GetCoreSchemaHandler,
)
from dracon.interpolation_utils import (
    InterpolationMatch,
)
from dracon.interpolation import evaluate_expression, InterpolationError, DraconError
from dracon.utils import list_like, dict_like

import inspect
from pydantic_core import core_schema  # Added core_schema

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
            validator=None,
        )

    def __repr__(self):
        return f"LazyInterpolable({self.value})"

    def resolve(self, context_override=None) -> T:
        if isinstance(self.value, str):
            try:
                ctx = self.context if self.context is not None else {}
                logger.debug(
                    f"Resolving lazy value: {self.value}, with context_override: {context_override} and context: {ctx}"
                )
                if context_override is not None:
                    ctx = {**ctx, **context_override}
                resolved_value = evaluate_expression(
                    self.value,
                    self.current_path,
                    self.root_obj,
                    init_outermost_interpolations=self.init_outermost_interpolations,
                    engine=self.engine,
                    context=ctx,
                )
                return self.validate(resolved_value)
            except Exception as e:
                import traceback

                logger.error(
                    f"Error evaluating expression '{self.value}' at path {self.current_path}: {e}\n{traceback.format_exc()}"
                )
                raise InterpolationError(
                    f"Error evaluating expression '{self.value}' at path {self.current_path}: {e}"
                ) from None
        return self.validate(self.value)

    def get(self, owner_instance, setval=False):
        if hasattr(owner_instance, '_dracon_root_obj'):
            self.root_obj = owner_instance._dracon_root_obj
            assert hasattr(owner_instance, '_dracon_current_path'), (
                f"Instance {owner_instance} has no current path"
            )
            if self.name and isinstance(self.current_path, KeyPath):
                self.current_path = owner_instance._dracon_current_path + self.name

        newval = self.resolve()

        if setval:
            setattr(owner_instance, self.name, newval)

        return newval

    def reattach_validator(self, validator: Optional[Callable[[Any], Any]]):
        """Reattach a validator after unpickling."""
        self.validator = validator

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: Type[Any], handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        """
        Pydantic v2 core schema generation for LazyInterpolable.

        Allows Pydantic to handle LazyInterpolable inputs during validation
        by attempting to resolve them first.
        """

        # define a validation function that tries to resolve LazyInterpolable
        def validate_lazy(value: Any) -> Any:
            if isinstance(value, cls):
                try:
                    # attempt to resolve the lazy value immediately
                    resolved = value.resolve()
                    logger.debug(f"pydantic validator resolved {value!r} to {resolved!r}")
                    return resolved
                except InterpolationError as e:
                    logger.debug(
                        f"failed to resolve {value!r} during pydantic validation: {e}, returning original lazy object."
                    )
                    return value
            return value

        # get the schema for the inner type T if LazyInterpolable[T] is used
        args = get_args(source)
        if args:
            inner_schema = handler(args[0])
            return core_schema.union_schema(
                [
                    core_schema.no_info_before_validator_function(validate_lazy, inner_schema),
                    core_schema.is_instance_schema(cls),
                ]
            )
        else:
            return core_schema.no_info_plain_validator_function(validate_lazy)


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
        for k_in_parent in list(parent.keys()):  # iterate over a copy of keys
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
            or original_lazy_key_object in parent  # check if original lazy obj is still a key
        ):
            try:
                value = parent[original_lazy_key_object]
                logger.debug(f"Got value associated with lazy key: {type(value)}")

                if original_lazy_key_object in parent:
                    del parent[original_lazy_key_object]

                parent[resolved_key] = value

                old_path = parent_path.down(MAPPING_KEY).down(str(original_lazy_key_object.value))
                new_path = parent_path.down(str(resolved_key))
                # report transformation only if key value changed
                if str(original_lazy_key_object.value) != str(resolved_key):
                    return True, (old_path, new_path)
                else:
                    return True, None

            except KeyError:
                logger.warning(
                    f"KeyError trying to access/delete lazy key {original_lazy_key_object!r}. It might have been processed already."
                )
                return False, None
            except Exception as e_inner:
                logger.error(f"Error during key update for {path}: {e_inner}", exc_info=True)
                return False, None
        else:
            logger.debug(
                f"Resolved key '{resolved_key}' matches lazy value and object is gone. No update needed."
            )
            return True, None  # indicate success but no transformation

    except Exception as e:
        import traceback

        logger.error(f"Error resolving key {key} at {path}: {e}\n{traceback.format_exc()}")
        raise e


def resolve_single_value(path, value, root, context_override=None):
    """resolve a single lazy value"""
    try:
        parent = path.parent.get_obj(root)
        value.root_obj = root
        value.current_path = path

        resolved_value = value.resolve(context_override=context_override)

        stem = path.stem
        if stem == '/' or stem == ROOTPATH:
            logger.warning(f"Attempted to set value at root path {path}. This is likely an error.")
            return False

        set_val(parent, stem, resolved_value)
        return True

    except Exception as e:
        import traceback

        logger.error(f"error resolving value {value} at {path}: {e}\n{traceback.format_exc()}")
        raise e


def set_val(parent: Any, key, value: Any) -> None:
    if list_like(parent):
        parent[int(key)] = value
    elif isinstance(parent, BaseModel):
        # handle pydantic models specifically
        setattr(parent, key, value)
    elif (
        hasattr(parent, key)
        and not callable(getattr(parent, key))
        and not inspect.isclass(getattr(parent, key))
    ):
        # try setattr if attribute exists and is not callable/class
        try:
            setattr(parent, key, value)
        except (AttributeError, TypeError):
            try:
                parent[key] = value
            except Exception as e:
                raise AttributeError(
                    f"Could not set attribute or item '{key}' in {parent}: {e}"
                ) from None
    else:
        try:
            parent[key] = value
        except TypeError:
            try:
                # last fallback: try setting attribute anyway
                setattr(parent, key, value)
            except AttributeError:
                raise AttributeError(
                    f'Could not set attribute or item \'{key}\' in {parent}'
                ) from None


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
                    key_path = p.copy().down(MAPPING_KEY).down(str(k.value))
                    if depth not in lazy_keys_by_depth:
                        lazy_keys_by_depth[depth] = []
                    lazy_keys_by_depth[depth].append((key_path, k))

                value_path_key = k.value if isinstance(k, LazyInterpolable) else str(k)
                value_path = p.copy().down(value_path_key)
                _collect(v, value_path, seen_set)

        # handle list-like objects (excluding strings, bytes, and numeric arrays)
        elif list_like(o) and not isinstance(o, (str, bytes, type)) and not num_array_like(o):
            try:
                # iterate over a copy in case list is modified during recursion
                for i, item in enumerate(list(o)):
                    item_path = p.copy().down(str(i))
                    _collect(item, item_path, seen_set)
            except TypeError:
                pass

        # Pydantic models
        elif isinstance(o, BaseModel):
            # Iterate through model fields directly
            for field_name in o.model_fields_set:
                field_value = getattr(o, field_name)

                item_path = p.copy().down(field_name)
                _collect(field_value, item_path, seen_set)

            if hasattr(o, '__dict__'):
                model_cls = type(o)
                for attr_name, attr_value in o.__dict__.items():
                    if attr_name.startswith('_') or attr_name in model_cls.model_fields:
                        continue
                    attr_path = p.copy().down(attr_name)
                    _collect(attr_value, attr_path, seen_set)

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
                for attr_name, attr_value in list(vars(o).items()):
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

    if not (dict_like(obj) or list_like(obj) or isinstance(obj, BaseModel)):
        if isinstance(obj, LazyInterpolable):
            # if the root object itself is lazy
            if root_obj is None:
                root_obj = obj  # Set root_obj if None
            if current_path is None:
                current_path = ROOTPATH
            obj.root_obj = root_obj
            obj.current_path = current_path
            return obj.resolve(context_override=context_override)
        return obj  # return non-lazy, non-container types as is

    obj_id = id(obj)
    if obj_id in visited_ids:
        logger.debug(f"Skipping already visited object {type(obj)} at {current_path}")
        return obj
    visited_ids.add(obj_id)

    if root_obj is None:
        root_obj = obj if not hasattr(obj, '_dracon_root_obj') else obj._dracon_root_obj

    if current_path is None:
        current_path = (
            ROOTPATH if not hasattr(obj, '_dracon_current_path') else obj._dracon_current_path
        )

    logger.debug(f"Starting resolve_all_lazy for obj {type(obj)} at path {current_path}")

    resolved_something_in_last_pass = True
    pass_num = 0
    max_passes = max_passes

    while resolved_something_in_last_pass and pass_num < max_passes:
        resolved_something_in_last_pass = False
        pass_num += 1
        logger.debug(f"Resolve pass {pass_num} for path {current_path}")

        lazy_keys_by_depth, lazy_values = collect_lazy_by_depth(obj, current_path, seen=set())

        if not lazy_keys_by_depth and not lazy_values:
            logger.debug(
                f"No lazy objects found at path {current_path} in pass {pass_num}. Breaking."
            )
            break

        keys_resolved_this_pass = 0
        keys_transformed = False
        transformed_paths = {}  # old_path_str -> new_path

        depths = sorted(lazy_keys_by_depth.keys())
        logger.debug(f"Lazy keys found at depths: {depths}")
        if depths:
            # Process keys level by level might be complex if structure changes.
            # Let's try resolving all keys found in this pass first.
            all_keys_to_resolve = []
            for depth in depths:
                all_keys_to_resolve.extend(lazy_keys_by_depth.get(depth, []))

            logger.debug(
                f"Keys to resolve in pass {pass_num}: {[p for p, k in all_keys_to_resolve]}"
            )
            for path, key in all_keys_to_resolve:
                # Adjust path based on previous transformations in this pass
                adjusted_path_str = str(path)
                for old_prefix, new_prefix in transformed_paths.items():
                    if adjusted_path_str.startswith(old_prefix):
                        adjusted_path_str = new_prefix + adjusted_path_str[len(old_prefix) :]
                        break
                adjusted_path = KeyPath(adjusted_path_str)

                # Pass the container `obj` as the root for key resolution relative to itself
                success, transform = resolve_single_key(
                    adjusted_path, key, root_obj, context_override
                )
                if success:
                    resolved_something_in_last_pass = True
                    keys_resolved_this_pass += 1
                    if transform:  # checks if path structure actually changed
                        keys_transformed = True
                        old_path_str, new_path = transform
                        # Store transformation relative to the root_obj
                        transformed_paths[str(old_path_str)] = str(new_path)
                        logger.debug(f"Key transformation recorded: {old_path_str} -> {new_path}")

        # --- Resolve Values ---
        values_resolved_this_pass = 0
        logger.debug(f"Values to resolve in pass {pass_num}: {[p for p, v in lazy_values]}")
        for path, value in lazy_values:
            # Adjust path based on key transformations in this pass
            adjusted_path_str = str(path)
            for old_prefix, new_prefix in transformed_paths.items():
                if adjusted_path_str.startswith(old_prefix):
                    adjusted_path_str = new_prefix + adjusted_path_str[len(old_prefix) :]
                    break
            adjusted_path = KeyPath(adjusted_path_str)

            success = resolve_single_value(adjusted_path, value, root_obj, context_override)
            if success:
                resolved_something_in_last_pass = True
                values_resolved_this_pass += 1

        logger.debug(
            f"Pass {pass_num} summary: Keys resolved: {keys_resolved_this_pass}, Values resolved: {values_resolved_this_pass}, Keys transformed: {keys_transformed}"
        )

        # --- Recurse into children AFTER resolving current level ---
        if not resolved_something_in_last_pass:
            logger.debug(f"No changes in pass {pass_num}, proceeding to children recursion.")
            if dict_like(obj):
                for k, v in list(obj.items()):
                    key_str = k.value if isinstance(k, LazyInterpolable) else str(k)
                    child_path = current_path + key_str
                    obj[k] = resolve_all_lazy(
                        v, root_obj, child_path, visited_ids, context_override, max_passes
                    )
            elif list_like(obj) and not isinstance(obj, (str, bytes)):
                for i, item in enumerate(list(obj)):  # iterate copy
                    child_path = current_path + str(i)
                    obj[i] = resolve_all_lazy(
                        item, root_obj, child_path, visited_ids, context_override, max_passes
                    )
            elif isinstance(obj, BaseModel):
                for field_name in list(obj.model_fields_set):  # iterate copy
                    child_path = current_path + field_name
                    current_val = getattr(obj, field_name)
                    resolved_val = resolve_all_lazy(
                        current_val, root_obj, child_path, visited_ids, context_override, max_passes
                    )
                    try:
                        setattr(obj, field_name, resolved_val)
                    except Exception as e:
                        logger.error(f"Failed to set attribute {field_name} on {type(obj)}: {e}")

    if pass_num == max_passes and resolved_something_in_last_pass:
        # check again if lazy objects remain after max passes
        remaining_keys_by_depth, remaining_values = collect_lazy_by_depth(
            obj, current_path, seen=set()
        )
        if remaining_values or any(remaining_keys_by_depth.values()):
            logger.warning(
                f"Max passes ({max_passes}) reached during resolve_all_lazy for path {current_path}, potentially unresolved lazy objects remain."
            )
            logger.warning(f"Remaining Keys: {remaining_keys_by_depth}")
            logger.warning(f"Remaining Values: {remaining_values}")

    visited_ids.remove(obj_id)
    logger.debug(f"Finished resolve_all_lazy for obj {type(obj)} at path {current_path}")
    return obj


##────────────────────────────────────────────────────────────────────────────}}}

## {{{              --     recursive lazy container update     --


def recursive_update_lazy_container(obj, root_obj, current_path, seen=None):
    """
    Recursively update the root object and current path of all nested lazy objects.
    """

    if seen is None:
        seen = set()

    # handle non-container types first
    if not (dict_like(obj) or list_like(obj) or isinstance(obj, BaseModel)):
        if isinstance(obj, LazyInterpolable):
            obj.root_obj = root_obj
            obj.current_path = current_path
        return

    obj_id = id(obj)
    if obj_id in seen:
        return  # skip already processed objects to break cycles
    seen.add(obj_id)

    if is_lazy_compatible(obj):
        obj._dracon_root_obj = root_obj
        obj._dracon_current_path = current_path

    if dict_like(obj):
        # iterate over copy of items for safety if dict changes
        for key, value in list(obj.items()):
            # update key if it's lazy
            if isinstance(key, LazyInterpolable):
                key.root_obj = root_obj
                # key's path needs care, it's relative to the parent dict path
                key.current_path = current_path  # Assign parent path for context, actual resolution uses MAPPING_KEY logic

            # update value
            key_str = key.value if isinstance(key, LazyInterpolable) else str(key)
            new_path = current_path + str(key_str)
            recursive_update_lazy_container(value, root_obj, new_path, seen)

    elif list_like(obj) and not isinstance(obj, (str, bytes)) and not num_array_like(obj):
        # iterate over copy in case list is modified
        for i, item in enumerate(list(obj)):
            new_path = current_path + str(i)
            recursive_update_lazy_container(item, root_obj, new_path, seen)

    elif isinstance(obj, BaseModel):
        # update base model attributes first
        if hasattr(obj, '_dracon_root_obj'):
            obj._dracon_root_obj = root_obj
        if hasattr(obj, '_dracon_current_path'):
            obj._dracon_current_path = current_path
        # then recurse into fields
        for field_name in obj.model_fields_set:  # Use model_fields_set
            value = getattr(obj, field_name)
            new_path = current_path + field_name
            recursive_update_lazy_container(value, root_obj, new_path, seen)
        # also check __dict__ for non-field lazy attributes
        if hasattr(obj, '__dict__'):
            model_cls = type(obj)
            for attr_name, value in obj.__dict__.items():
                if attr_name.startswith('_') or attr_name in model_cls.model_fields:
                    continue
                new_path = current_path + attr_name
                recursive_update_lazy_container(value, root_obj, new_path, seen)


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
            if isinstance(attr, LazyInterpolable):
                attr.root_obj = self._dracon_root_obj
                attr.current_path = self._dracon_current_path + name
            return attr.get(self)  # get() calls resolve() internally
        return attr
