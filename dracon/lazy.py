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
                    context=ctx,
                )
            except Exception as e:
                raise type(e)(f"Error resolving lazy value \"{self.value}\": {str(e)}") from None

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
            raise AttributeError(f'Could not set attribute {key} in {parent}') from None


def num_array_like(obj):
    return hasattr(obj, 'dtype') and hasattr(obj, 'shape') and obj.dtype.kind in 'iuf'


def collect_lazy_by_depth(obj, path=ROOTPATH, seen=None):
    """collect all lazy objects grouped by depth"""
    if seen is None:
        seen = set()

    lazy_keys_by_depth = {}  # depth -> list of (path, lazy_key)
    lazy_values = []  # list of (path, lazy_value)

    def _collect(o, p, seen_set):
        obj_id = id(o)
        if obj_id in seen_set:
            return
        seen_set.add(obj_id)

        depth = len(p)

        if isinstance(o, LazyInterpolable):
            if p.is_mapping_key():
                if depth not in lazy_keys_by_depth:
                    lazy_keys_by_depth[depth] = []
                lazy_keys_by_depth[depth].append((p, o))
            else:
                lazy_values.append((p, o))
            return

        if dict_like(o):
            for k, v in list(o.items()):
                if isinstance(k, LazyInterpolable):
                    key_path = p.copy().down(MAPPING_KEY).down(str(k))
                    if depth not in lazy_keys_by_depth:
                        lazy_keys_by_depth[depth] = []
                    lazy_keys_by_depth[depth].append((key_path, k))

                value_path = p.copy().down(str(k))
                _collect(v, value_path, seen_set)

        elif list_like(o) and not isinstance(o, (str, bytes)) and not num_array_like(o):
            for i, item in enumerate(o):
                item_path = p.copy().down(str(i))
                _collect(item, item_path, seen_set)

    _collect(obj, path, seen)
    return lazy_keys_by_depth, lazy_values


def resolve_single_key(path, key, root, context_override=None):
    """resolve a single lazy key and return info about the transformation"""
    parent_path = path.parent

    try:
        parent = parent_path.get_obj(root)
        key.root_obj = root
        key.current_path = path.removed_mapping_key()

        # find the actual key in parent
        lazy_key = None
        for k in parent.keys():
            if isinstance(k, LazyInterpolable) and (id(k) == id(key) or str(k) == str(key)):
                lazy_key = k
                break

        if lazy_key is None:
            raise DraconError(f"couldn't find LazyInterpolable key in parent at {path}")

        # resolve the key
        resolved_key = key.resolve(context_override=context_override)
        if not isinstance(resolved_key, (str, int, float, bool)):
            resolved_key = str(resolved_key)

        # update mapping
        value = parent[lazy_key]
        del parent[lazy_key]
        parent[resolved_key] = value

        if hasattr(parent, '_recompute_map'):
            parent._recompute_map()

        # return the transformation info
        old_path = parent_path.down(str(lazy_key))
        new_path = parent_path.down(str(resolved_key))
        return True, (old_path, new_path)

    except Exception as e:
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
            raise ValueError("cannot resolve root path")

        set_val(parent, stem, resolved_value)
        return True

    except Exception as e:
        return False


def resolve_all_lazy(
    obj,
    root_obj=None,
    current_path=None,
    visited=None,
    context_override=None,
    max_passes=20,
):
    """resolves all lazy objects in a multi-pass approach by depth level"""
    if visited is None:
        visited = set()

    if root_obj is None:
        root_obj = obj if not hasattr(obj, '_dracon_root_obj') else obj._dracon_root_obj

    if current_path is None:
        current_path = (
            ROOTPATH if not hasattr(obj, '_dracon_current_path') else obj._dracon_current_path
        )

    # process key resolution in multiple passes by depth
    unresolved_count = 0
    pass_num = 0

    while pass_num < max_passes:
        lazy_keys_by_depth, lazy_values = collect_lazy_by_depth(obj, current_path)

        if not lazy_keys_by_depth and not lazy_values:
            break

        # resolve keys by depth (shallowest first)
        depths = sorted(lazy_keys_by_depth.keys())
        if not depths:  # no more keys to resolve, move on to values
            keys_resolved = 0
        else:  # resolve keys at the shallowest depth only
            current_depth = depths[0]
            keys_resolved = 0
            for path, key in lazy_keys_by_depth[current_depth]:
                success, _ = resolve_single_key(path, key, root_obj, context_override)
                if success:
                    keys_resolved += 1

        # if no keys were resolved, move on to values
        if not keys_resolved:
            values_resolved = 0
            for path, value in lazy_values:
                success = resolve_single_value(path, value, root_obj, context_override)
                if success:
                    values_resolved += 1

            unresolved_count += values_resolved
            if values_resolved == 0:  # nothing more to resolve
                break
        else:
            unresolved_count += keys_resolved

        pass_num += 1

    if unresolved_count > 0:  # should not happen, I think?
        print(f"WARNING: dracon.resolve_all_lazy: unresolved_count = {unresolved_count}")
        return resolve_all_lazy(obj, root_obj, current_path, visited, context_override, max_passes)

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
