"""Regression tests for list_like / dict_like.

The cache is keyed by `type(obj)`. Without the class-object guard,
`list_like(str)` would walk str's class-level descriptors, see callable
`__getitem__`/`__iter__`/`__len__`/`__add__`, and write
`_list_like_cache[type] = True`. Every later `list_like(<any-class>)`
call would then return True from cache, and downstream code that does
`list(obj)` over the result would explode with
`TypeError: 'type' object is not iterable`.

Class objects are never data containers regardless of metaclass
descriptors; the guard short-circuits before the cache lookup.
"""

from __future__ import annotations

from collections.abc import MutableMapping

import pytest

from dracon.utils import (
    _dict_like_cache,
    _list_like_cache,
    dict_like,
    list_like,
)


@pytest.fixture(autouse=True)
def _clear_caches():
    _list_like_cache.clear()
    _dict_like_cache.clear()
    yield
    _list_like_cache.clear()
    _dict_like_cache.clear()


@pytest.mark.parametrize("cls", [str, bytes, int, float, bool, list, tuple, dict, set, frozenset, type, object])
def test_class_object_is_never_list_like(cls):
    assert list_like(cls) is False


@pytest.mark.parametrize("cls", [str, bytes, int, float, bool, list, tuple, dict, set, frozenset, type, object])
def test_class_object_is_never_dict_like(cls):
    assert dict_like(cls) is False


def test_str_class_does_not_poison_cache_for_other_classes():
    """The exact poisoning path: list_like(str) seeds the cache; later list_like(<any class>) must not see True."""
    list_like(str)

    class Other:
        pass

    assert list_like(Other) is False
    assert list_like(int) is False
    assert list_like(dict) is False


def test_dict_class_does_not_poison_dict_like_cache():
    dict_like(dict)

    class Other:
        pass

    assert dict_like(Other) is False
    assert dict_like(str) is False


def test_list_like_still_true_for_real_lists_after_class_lookup():
    list_like(str)
    assert list_like([1, 2, 3]) is True
    assert list_like((1, 2)) is True


def test_dict_like_still_true_for_real_dicts_after_class_lookup():
    dict_like(dict)
    assert dict_like({"a": 1}) is True


def test_list_like_rejects_strings_bytes_dicts():
    assert list_like("abc") is False
    assert list_like(b"abc") is False
    assert list_like({"a": 1}) is False


def test_dict_like_accepts_mutable_mapping_subclass():
    class MyDict(MutableMapping):
        def __init__(self):
            self._d: dict = {}

        def __getitem__(self, k):
            return self._d[k]

        def __setitem__(self, k, v):
            self._d[k] = v

        def __delitem__(self, k):
            del self._d[k]

        def __iter__(self):
            return iter(self._d)

        def __len__(self):
            return len(self._d)

    assert dict_like(MyDict()) is True
    assert dict_like(MyDict) is False


def test_iterating_after_listlike_check_does_not_typeerror_on_class():
    """The original symptom: list(<class>) raises TypeError.

    Code that trusts list_like as a permission-to-iterate gate must never see True for a class.
    """

    def safe_walk(obj):
        if list_like(obj):
            return list(obj)
        return None

    assert safe_walk(str) is None
    assert safe_walk(int) is None
    assert safe_walk([1, 2]) == [1, 2]
