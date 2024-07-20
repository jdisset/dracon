from typing import Any, Dict, List, Union, TypeVar, Generic, Optional, Set
from collections.abc import MutableMapping, MutableSequence
from copy import deepcopy
from dracon.keypath import ROOTPATH

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
        # self._per_item_tags: Dict[Any, Set[Tag]] = {}
        self._dracon_root_obj = self
        self._dracon_current_path = ROOTPATH

    def set_metadata(self, metadata):
        self._metadata = metadata

    def get_metadata(self):
        return self._metadata

    def set_item_metadata(self, key, metadata):
        self._per_item_metadata[key] = metadata

    def get_item_metadata(self, key):
        return self._per_item_metadata.get(key)


        # problem with the tag approach is that it won't work for when building another object type.
        # Ideally there should be a LazyInterpolation type that allows for the interpolation to be done on access.
        # if self._auto_interp: # we interpolate on access
        # if INTERPOLABLE in self._per_item_tags.get(index, tuple()):
        # element = self._interpolate(element)
        # if self._inplace_interp:
        # self._data[index] = element
        # self._per_item_tags[index].remove(INTERPOLABLE)


    def __setitem__(self, key, value):
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

    @classmethod
    def create(cls, data: Union[Dict, List, None] = None):
        if isinstance(data, dict):
            return Mapping(data)
        elif isinstance(data, list):
            return Sequence(data)
        else:
            raise ValueError("Input must be either a dict or a list")

    @classmethod
    def _convert(cls, value):
        if isinstance(value, dict):
            return Mapping(value)
        elif isinstance(value, list):
            return Sequence(value)
        return value


class Mapping(Dracontainer, MutableMapping[K, V], Generic[K, V]):
    def __init__(self, data: Optional[Dict[K, V]] = None):
        super().__init__()
        self._data: Dict[K, V] = {}
        if data:
            for key, value in data.items():
                self[key] = Dracontainer._convert(value)

    def __getitem__(self, key):
        element = self._data[key]
        return element

    def __setitem__(self, key, value):
        self._data[key] = Dracontainer._convert(value)

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


    @classmethod
    def fromkeys(cls, iterable, value=None):
        return cls({key: Dracontainer._convert(value) for key in iterable})


class Sequence(Dracontainer, MutableSequence[V]):
    def __init__(self, data: Optional[List[V]] = None):
        super().__init__()
        self._data: List[V] = []
        if data:
            for item in data:
                self.append(Dracontainer._convert(item))

    def __setitem__(self, index, value):
        self._data[index] = Dracontainer._convert(value)

    def __delitem__(self, index):
        del self._data[index]
        if index in self._per_item_metadata:
            del self._per_item_metadata[index]

    def __getitem__(self, index):
        element = self._data[index]
        return element

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
        self._data.insert(index, Dracontainer._convert(value))

    def append(self, value):
        self._data.append(Dracontainer._convert(value))

    def __add__(self, other: 'Sequence[V]'):
        new_data = deepcopy(self._data)
        new_data.extend(other)
        return Sequence(new_data)




def create_dracontainer(
    data: Union[Dict, List],
) -> Union[Mapping, Sequence]:
    return Dracontainer.create(data)
