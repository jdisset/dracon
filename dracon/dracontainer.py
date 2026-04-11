# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

from typing import Any, Dict, List, Union, TypeVar, Generic, Optional, Set
from dracon.keypath import ROOTPATH, KeyPath
from dracon.utils import DictLike, ListLike, deepcopy, dict_like, list_like
from dracon.lazy import (
    Lazy,
    recursive_update_lazy_container,
    resolve_all_lazy,
)


K = TypeVar('K')
V = TypeVar('V')


class Tag:
    def __init__(self, name: str):
        self.name = name

    def __eq__(self, other):
        if isinstance(other, Tag):
            return self.name == other.name
        return False

    def __hash__(self):
        return hash(self.name)

    def __str__(self):
        return self.name


INTERPOLABLE = Tag("intrp")


class _RawMappingView:
    """Thin proxy over a Mapping that bypasses lazy resolution on reads.

    Exposed as `mapping._data` so existing code (the ruamel representer,
    internal tests, anywhere that wants to inspect the raw stored value)
    continues to see LazyInterpolable / Lazy wrappers instead of their
    resolved values.
    """

    __slots__ = ('_owner',)

    def __init__(self, owner):
        object.__setattr__(self, '_owner', owner)

    def __getitem__(self, key):
        return dict.__getitem__(self._owner, key)

    def __setitem__(self, key, value):
        dict.__setitem__(self._owner, key, value)

    def __delitem__(self, key):
        dict.__delitem__(self._owner, key)

    def __iter__(self):
        return dict.__iter__(self._owner)

    def __len__(self):
        return dict.__len__(self._owner)

    def __contains__(self, key):
        return dict.__contains__(self._owner, key)

    def items(self):
        return dict.items(self._owner)

    def keys(self):
        return dict.keys(self._owner)

    def values(self):
        return dict.values(self._owner)

    def get(self, key, default=None):
        return dict.get(self._owner, key, default)

    def __eq__(self, other):
        if isinstance(other, _RawMappingView):
            other = other._owner
        return dict.__eq__(self._owner, other)

    def __bool__(self):
        return dict.__len__(self._owner) > 0

    def __repr__(self):
        return dict.__repr__(self._owner)


class _RawSequenceView:
    """Thin proxy over a Sequence that bypasses lazy resolution on reads."""

    __slots__ = ('_owner',)

    def __init__(self, owner):
        object.__setattr__(self, '_owner', owner)

    def __getitem__(self, index):
        return list.__getitem__(self._owner, index)

    def __setitem__(self, index, value):
        list.__setitem__(self._owner, index, value)

    def __delitem__(self, index):
        list.__delitem__(self._owner, index)

    def __iter__(self):
        return list.__iter__(self._owner)

    def __len__(self):
        return list.__len__(self._owner)

    def __contains__(self, value):
        return list.__contains__(self._owner, value)

    def __eq__(self, other):
        if isinstance(other, _RawSequenceView):
            other = other._owner
        return list.__eq__(self._owner, other)

    def __bool__(self):
        return list.__len__(self._owner) > 0

    def __repr__(self):
        return list.__repr__(self._owner)


class Dracontainer:
    """Mixin that adds dracon bookkeeping (metadata, lazy resolution, root
    tracking) on top of a native container type. Concrete subclasses
    (`Mapping`, `Sequence`) inherit from `dict`/`list` so `isinstance` checks
    and native operations (json.dumps, {**m}, list(s), ==) behave naturally.

    Class-level defaults for bookkeeping attributes ensure the container
    is usable before __init__ runs. This matters during pickle restoration
    of dict/list subclasses, where SETITEMS is applied before BUILD (state),
    i.e. __setitem__ fires before instance __dict__ is populated.
    """

    _auto_interp = True
    _inplace_interp = True
    _metadata = None
    _per_item_metadata: Dict[Any, Any] = {}
    _dracon_root_obj = None
    _dracon_current_path = ROOTPATH
    _dracon_lazy_resolve = True

    def __init__(self):
        self._auto_interp = True
        self._inplace_interp = True
        self._metadata = None
        self._per_item_metadata = {}
        self._dracon_root_obj = self
        self._dracon_current_path = ROOTPATH
        self._dracon_lazy_resolve = True

    def cleanup(self):
        """Clear internal references and caches"""
        try:
            self.clear()
        except (AttributeError, TypeError):
            pass
        if self._metadata:
            self._metadata.clear()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()

    def _copy_metadata_into(self, new_obj, memo=None, deep=True):
        copy_fn = (lambda v: deepcopy(v, memo)) if deep else (lambda v: v)
        new_obj._auto_interp = self._auto_interp
        new_obj._inplace_interp = self._inplace_interp
        new_obj._metadata = copy_fn(self._metadata)
        new_obj._per_item_metadata = copy_fn(self._per_item_metadata)
        new_obj._dracon_root_obj = self._dracon_root_obj
        new_obj._dracon_current_path = self._dracon_current_path
        new_obj._dracon_lazy_resolve = self._dracon_lazy_resolve
        if self._dracon_root_obj is self:
            new_obj._dracon_root_obj = new_obj

    def __deepcopy__(self, memo):
        new_obj = self.__class__()
        self._copy_data_into(new_obj, memo, deep=True)
        self._copy_metadata_into(new_obj, memo, deep=True)
        recursive_update_lazy_container(
            new_obj,
            root_obj=new_obj._dracon_root_obj,
            current_path=new_obj._dracon_current_path,
        )
        return new_obj

    def __copy__(self):
        new_obj = self.__class__()
        self._copy_data_into(new_obj, None, deep=False)
        self._copy_metadata_into(new_obj, None, deep=False)
        recursive_update_lazy_container(
            new_obj,
            root_obj=new_obj._dracon_root_obj,
            current_path=new_obj._dracon_current_path,
        )
        return new_obj

    def _copy_data_into(self, new_obj, memo, deep):
        raise NotImplementedError

    def set_metadata(self, metadata):
        self._metadata = metadata

    def get_metadata(self):
        return self._metadata

    def set_item_metadata(self, key, metadata):
        self._per_item_metadata[key] = metadata

    def get_item_metadata(self, key):
        return self._per_item_metadata.get(key)

    def __setattr__(self, key, value):
        if key.startswith('_'):
            super().__setattr__(key, value)
        else:
            self[key] = value

    def _handle_lazy(self, name, value):
        if isinstance(value, Lazy) and self._dracon_lazy_resolve:
            value.name = name
            newval = value.get(self, setval=True)
            return newval
        return value

    @classmethod
    def create(cls, data: Union[DictLike[K, V], ListLike[V], None] = None):
        if dict_like(data):
            return Mapping(data)
        elif list_like(data):
            return Sequence(data)
        else:
            raise ValueError("Input must be either a dict or a list")

    def _to_dracontainer(self, value: Any, key: Any):
        newval = value
        if isinstance(value, (Mapping, Sequence)):
            newval = value
        elif isinstance(value, dict):
            newval = Mapping(value)
        elif isinstance(value, list) and not isinstance(value, str):
            newval = Sequence(value)

        recursive_update_lazy_container(
            newval,
            root_obj=self._dracon_root_obj,
            current_path=self._dracon_current_path + KeyPath(str(key)),
        )

        return newval

    def set_lazy_resolve(self, value, recursive=True):
        self._dracon_lazy_resolve = value
        if recursive:
            for item in self:
                if isinstance(item, Dracontainer):
                    item.set_lazy_resolve(value, recursive=True)

    def resolve_all_lazy(self, permissive: bool = False):
        resolve_all_lazy(self, permissive=permissive)


class Mapping(Dracontainer, dict, Generic[K, V]):
    """Dict subclass with dracon bookkeeping. Storage is the dict itself, so
    `isinstance(x, dict)`, `{**x}`, `dict(x)`, `json.dumps(x)`, `x == {...}`
    all work natively. `__getitem__` still passes values through
    `_handle_lazy` so interpolation and lazy resolution remain transparent."""

    def __init__(self, data: Optional[DictLike[K, V]] = None):
        dict.__init__(self)
        Dracontainer.__init__(self)
        if data:
            for key, value in data.items():
                self[key] = value

    @property
    def _data(self):
        return _RawMappingView(self)

    def __getattr__(self, key):
        # only called when normal attribute lookup fails
        if dict.__contains__(self, key):
            return self[key]
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{key}'")

    def __getitem__(self, key):
        element = dict.__getitem__(self, key)
        return self._handle_lazy(key, element)

    def __iter__(self):
        # defined in Python (not inherited from C dict) so CPython falls back
        # to the slow path in PyDict_Merge / `{**m}` / `dict(m)`, which calls
        # our __getitem__ for each value and therefore sees resolved lazies
        # instead of the raw wrappers stored in the underlying dict.
        return dict.__iter__(self)

    def __setitem__(self, key, value):
        # during pickle restoration, SETITEMS runs BEFORE BUILD (state), so
        # the dracon bookkeeping isn't set up yet. In that case we just
        # write the raw value - the child's own state was already restored
        # correctly during its own unpickling.
        if self._dracon_root_obj is None:
            dict.__setitem__(self, key, value)
            return
        dict.__setitem__(self, key, self._to_dracontainer(value, key))

    def update(self, other=(), /, **kwargs):
        if hasattr(other, 'items'):
            for key, value in other.items():
                self[key] = value
        else:
            for key, value in other:
                self[key] = value
        for key, value in kwargs.items():
            self[key] = value

    def __delitem__(self, key):
        dict.__delitem__(self, key)
        if key in self._per_item_metadata:
            del self._per_item_metadata[key]

    def __repr__(self):
        return f"{self.__class__.__name__}({dict.__repr__(self)})"

    def copy(self):
        return Mapping(self)

    def _copy_data_into(self, new_obj, memo, deep):
        copy_fn = (lambda v: deepcopy(v, memo)) if deep else (lambda v: v)
        for k in dict.__iter__(self):
            v = dict.__getitem__(self, k)
            dict.__setitem__(new_obj, copy_fn(k), copy_fn(v))


class Sequence(Dracontainer, list, Generic[V]):
    """List subclass with dracon bookkeeping. Storage is the list itself, so
    `isinstance(x, list)`, `list(x)`, `json.dumps(x)`, `x == [...]` work
    natively. `__getitem__` still passes values through `_handle_lazy`."""

    def __init__(self, data: Optional[ListLike[V]] = None):
        list.__init__(self)
        Dracontainer.__init__(self)
        if data:
            for item in data:
                self.append(item)

    @property
    def _data(self):
        return _RawSequenceView(self)

    def __setitem__(self, index, value):
        index = int(index)
        if self._dracon_root_obj is None:
            list.__setitem__(self, index, value)
            return
        list.__setitem__(self, index, self._to_dracontainer(value, index))

    def __delitem__(self, index):
        list.__delitem__(self, index)
        if index in self._per_item_metadata:
            del self._per_item_metadata[index]

    def __iter__(self):
        # defined in Python so consumers like `list(seq)` use the slow path
        # and resolve lazies via __getitem__
        for i in range(list.__len__(self)):
            yield self[i]

    def __getitem__(self, index):
        if isinstance(index, slice):
            return Sequence(list.__getitem__(self, index))
        else:
            index = int(index)
            element = list.__getitem__(self, index)
            return self._handle_lazy(str(index), element)

    def __repr__(self):
        return f"{self.__class__.__name__}({list.__repr__(self)})"

    def insert(self, index: int, value: V):
        if self._dracon_root_obj is None:
            list.insert(self, index, value)
            return
        list.insert(self, index, self._to_dracontainer(value, index))

    def append(self, value: V):
        if self._dracon_root_obj is None:
            list.append(self, value)
            return
        list.append(self, self._to_dracontainer(value, key=list.__len__(self)))

    def __append__(self, value):
        self.append(value)

    def extend(self, values):
        if self._dracon_root_obj is None:
            list.extend(self, values)
            return
        for value in values:
            self.append(value)

    def __add__(self, other) -> 'Sequence[V]':
        new_data = list(self)
        new_data.extend(other)
        return Sequence(new_data)  # type: ignore

    def _copy_data_into(self, new_obj, memo, deep):
        copy_fn = (lambda v: deepcopy(v, memo)) if deep else (lambda v: v)
        for v in list.__iter__(self):
            list.append(new_obj, copy_fn(v))


def create_dracontainer(
    data: Union[Dict, List],
) -> Union[Mapping, Sequence]:
    return Dracontainer.create(data)
