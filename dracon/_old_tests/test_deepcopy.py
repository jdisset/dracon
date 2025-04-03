import pytest
from dataclasses import dataclass
from types import ModuleType, FunctionType
import sys
import marshal

# Import the _deepcopy function and its helpers
# Assuming they're in a file called deepcopy_utils.py
from dracon.utils import _deepcopy, dict_like, list_like


# Test Classes and Fixtures
@dataclass
class SimpleDataClass:
    x: int
    y: str


class CustomDeepCopy:
    def __init__(self, value):
        self.value = value

    def __deepcopy__(self, memo):
        return CustomDeepCopy(self.value * 2)


class CircularReference:
    def __init__(self):
        self.ref = None


class UncopiableObject:
    def __init__(self):
        self._module = sys

    def __deepcopy__(self, memo):
        raise NotImplementedError("Cannot deep copy this object")


@pytest.fixture
def circular_ref():
    obj1 = CircularReference()
    obj2 = CircularReference()
    obj1.ref = obj2
    obj2.ref = obj1
    return obj1


# Basic Type Tests
def test_simple_types():
    """Test copying of basic Python types."""
    assert _deepcopy(42) == 42
    assert _deepcopy(3.14) == 3.14
    assert _deepcopy("hello") == "hello"
    assert _deepcopy(True) == True
    assert _deepcopy(None) is None
    assert _deepcopy(complex(1, 2)) == complex(1, 2)


def test_marshalable_types():
    """Test if marshalable types are handled correctly."""
    data = {
        'list': [1, 2, 3],
        'tuple': (4, 5, 6),
        'dict': {'a': 1, 'b': 2},
        'set': {7, 8, 9},
        'frozenset': frozenset([10, 11, 12]),
    }

    copied = _deepcopy(data)
    assert copied == data
    assert copied is not data
    assert all(list(copied[k]) is not data[k] for k in data)


def test_nested_structures():
    """Test copying of nested data structures."""
    original = {'a': [1, 2, {'b': (3, 4, [5, 6])}], 'c': {7, 8, frozenset([9, 10])}}

    copied = _deepcopy(original)
    assert copied == original
    assert copied is not original
    assert copied['a'] is not original['a']
    assert copied['a'][2] is not original['a'][2]
    assert copied['a'][2]['b'] is not original['a'][2]['b']

    original['a'][2]['b'] = (0, 0, [0, 0])
    assert copied['a'][2]['b'] == (3, 4, [5, 6])


# Custom Object Tests
def test_dataclass_copy():
    """Test copying of dataclasses."""
    original = SimpleDataClass(x=1, y="test")
    copied = _deepcopy(original)

    assert copied == original
    assert copied is not original
    assert copied.x == 1
    assert copied.y == "test"


def test_custom_deepcopy_method():
    """Test that objects with __deepcopy__ are handled correctly."""
    original = CustomDeepCopy(5)
    copied = _deepcopy(original)

    assert copied is not original
    assert copied.value == 10  # Value should be doubled as per __deepcopy__ implementation


def test_circular_references(circular_ref):
    """Test handling of circular references."""
    copied = _deepcopy(circular_ref)

    assert copied is not circular_ref
    assert copied.ref is not circular_ref.ref
    assert copied.ref.ref is copied  # Circular reference should be preserved


# Edge Cases and Special Types
def test_module_type():
    """Test that ModuleType objects are returned as-is."""
    module = sys
    assert _deepcopy(module) is module


def test_function_type():
    """Test that function objects are returned as-is."""

    def test_func():
        pass

    assert _deepcopy(test_func) is test_func


def test_type_objects():
    """Test that type objects are returned as-is."""
    assert _deepcopy(str) is str
    assert _deepcopy(int) is int


# Performance Tests
def test_large_structure_performance():
    """Test performance with large data structures."""
    large_dict = {i: list(range(100)) for i in range(1000)}

    import time

    start_time = time.time()
    copied = _deepcopy(large_dict)
    end_time = time.time()

    assert copied == large_dict
    assert end_time - start_time < 1.0  # Should complete within 1 second


# Memory Tests
def test_memory_usage():
    """Test memory usage doesn't grow with repeated copies."""
    import psutil
    import os

    process = psutil.Process(os.getpid())
    initial_memory = process.memory_info().rss

    # Perform multiple copies
    data = {'a': [1] * 1000}
    for _ in range(1000):
        copied = _deepcopy(data)

    final_memory = process.memory_info().rss
    memory_increase = final_memory - initial_memory

    # Memory increase should be reasonable (less than 10MB)
    assert memory_increase < 10 * 1024 * 1024


if __name__ == '__main__':
    pytest.main([__file__])
