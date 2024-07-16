from typing import Dict, Generic, TypeVar, Any
from copy import deepcopy
from collections.abc import MutableMapping
from collections import UserDict

K = TypeVar('K')
V = TypeVar('V')

class Dracontainer(MutableMapping[K, V], Generic[K, V]):
    def __init__(self, *args, **kwargs):
        self._data: Dict[K, V] = {}
        self._metadata = None
        self._per_item_metadata: Dict[K, Any] = {}
        self.update(dict(*args, **kwargs))

    def set_metadata(self, metadata):
        self._metadata = metadata

    def get_metadata(self):
        return self._metadata

    def __getattr__(self, key):
        if key in self._data:
            return self._data[key]
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{key}'")

    def __setattr__(self, key, value):
        if key.startswith('_'):
            super().__setattr__(key, value)
        else:
            self._data[key] = value

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        self._data[key] = value

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

    def __deepcopy__(self, memo):
        newcontainer = self.__class__()
        memo[id(self)] = newcontainer
        for key, value in self.items():
            newcontainer[key] = deepcopy(value, memo)
        newcontainer._metadata = deepcopy(self._metadata, memo)
        newcontainer._per_item_metadata = deepcopy(self._per_item_metadata, memo)
        return newcontainer



    @classmethod
    def fromkeys(cls, iterable, value=None):
        return cls({key: value for key in iterable})
