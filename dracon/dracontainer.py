from typing import Any, Dict, List, Union, TypeVar, Generic, Optional, Set
from collections.abc import MutableMapping, MutableSequence
from copy import deepcopy
from dracon.keypath import ROOTPATH, KeyPath
from dracon.utils import DictLike, ListLike
from dracon.interpolation import Lazy, is_lazy_compatible


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


class Dracontainer:
    def __init__(self):
        self._auto_interp = True
        self._inplace_interp = True
        self._metadata = None
        self._per_item_metadata: Dict[Any, Any] = {}
        self._dracon_root_obj = self
        self._dracon_current_path = ROOTPATH
        self._dracon_lazy_resolve = True

    def set_metadata(self, metadata):
        self._metadata = metadata

    def get_metadata(self):
        return self._metadata

    def set_item_metadata(self, key, metadata):
        self._per_item_metadata[key] = metadata

    def get_item_metadata(self, key):
        return self._per_item_metadata.get(key)

    def __setitem__(self, key, value):
        raise NotImplementedError

    def __getitem__(self, key):
        raise NotImplementedError

    def __iter__(self):
        raise NotImplementedError

    def __getattr__(self, key):
        if key in self:
            return self[key]
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{key}'")

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

    def _handle_lazy_container(self, at_key, container):
        if is_lazy_compatible(container):
            print(f"Handling lazy container at key {at_key}. self.current_path: {self._dracon_current_path}")
            new_path = self._dracon_current_path + KeyPath(str(at_key))
            container._update_lazy_container_attributes(self._dracon_root_obj, new_path)
            print(f"current path: {container._dracon_current_path}")

    def _update_lazy_container_attributes(self, root_obj, current_path, recurse=True):
        self._dracon_root_obj = root_obj
        self._dracon_current_path = current_path
        if recurse:
            if isinstance(self, DictLike):
                for key, item in self.items():
                    if is_lazy_compatible(item):
                        new_path = current_path + KeyPath(str(key))
                        item._update_lazy_container_attributes(root_obj, new_path, recurse=True)
            elif isinstance(self, ListLike):
                for index, item in enumerate(self):
                    if is_lazy_compatible(item):
                        new_path = current_path + KeyPath(str(index))
                        item._update_lazy_container_attributes(root_obj, new_path, recurse=True)

    @classmethod
    def create(cls, data: Union[DictLike[K, V], ListLike[V], None] = None):
        if isinstance(data, DictLike):
            return Mapping(data)
        elif isinstance(data, ListLike):
            return Sequence(data)
        else:
            raise ValueError("Input must be either a dict or a list")

    def _to_dracontainer(self, value: Any, key: Any):
        newval = value
        if isinstance(value, (Mapping, Sequence)):
            newval = value
        elif isinstance(value, DictLike):
            newval = Mapping(value)
        elif isinstance(value, ListLike) and not isinstance(value, str):
            newval = Sequence(value)

        self._handle_lazy_container(str(key), newval)

        return newval

    def set_lazy_resolve(self, value, recursive=True):
        self._dracon_lazy_resolve = value
        if recursive:
            for item in self:
                if isinstance(item, Dracontainer):
                    item.set_lazy_resolve(value, recursive=True)


class Mapping(Dracontainer, MutableMapping[K, V], Generic[K, V]):
    def __init__(self, data: Optional[DictLike[K, V]] = None):
        super().__init__()
        self._data: Dict[K, V] = {}
        if data:
            for key, value in data.items():
                self[key] = value

    def __getitem__(self, key):
        element = self._data[key]
        return self._handle_lazy(key, element)

    def __setitem__(self, key: K, value: V):
        self._data[key] = self._to_dracontainer(value, key)

    def update(self, other):
        for key, value in other.items():
            self._data[key] = self._to_dracontainer(value, key)

    def __delitem__(self, key):
        del self._data[key]
        if key in self._per_item_metadata:
            del self._per_item_metadata[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)

    def __repr__(self):
        return f"{self.__class__.__name__}({self._data})"

    def __contains__(self, key):
        return key in self._data

    def items(self):
        return self._data.items()

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()


class Sequence(Dracontainer, MutableSequence[V]):
    def __init__(self, data: Optional[ListLike[V]] = None):
        super().__init__()
        self._data: List[V] = []
        if data:
            for item in data:
                self.append(item)

    def __setitem__(self, index, value):
        self._data[index] = self._to_dracontainer(value, index)

    def __delitem__(self, index):
        del self._data[index]
        if index in self._per_item_metadata:
            del self._per_item_metadata[index]

    def __getitem__(self, index):
        element = self._data[index]
        return self._handle_lazy(str(index), element)

    def __len__(self):
        return len(self._data)

    def __repr__(self):
        return f"{self.__class__.__name__}({self._data})"

    def __contains__(self, value):
        return value in self._data

    def __iter__(self):
        return iter(self._data)

    def __reversed__(self):
        return reversed(self._data)

    def clear(self):
        self._data.clear()

    def insert(self, index, value):
        self._data.insert(index, self._to_dracontainer(value, index))

    def append(self, value):
        self._data.append(self._to_dracontainer(value, key=len(self._data)))

    def extend(self, values):
        for value in values:
            self.append(value)

    def __add__(self, other: 'Sequence[V]'):
        new_data = deepcopy(self._data)
        new_data.extend(other)
        return Sequence(new_data)

    def __eq__(self, other):
        if isinstance(other, Sequence):
            return self._data == other._data
        elif isinstance(other, List):
            return self._data == other


def create_dracontainer(
    data: Union[Dict, List],
) -> Union[Mapping, Sequence]:
    return Dracontainer.create(data)
