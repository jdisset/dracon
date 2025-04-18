from dracon.merge import merged, MergeKey, MergeMode, MergePriority
from dracon.utils import ShallowDict


def test_basic_merge():
    d1 = {"a": 1, "b": 2}
    d2 = {"b": 3, "c": 4}
    mk = MergeKey(raw="<<{>}")
    result = merged(d1, d2, mk)
    assert result == {"a": 1, "b": 2, "c": 4}


def test_merge_with_new_priority():
    d1 = {"a": 1, "b": 2}
    d2 = {"b": 3, "c": 4}
    mk = MergeKey(raw="<<{<}")
    result = merged(d1, d2, mk)
    assert result == {"a": 1, "b": 3, "c": 4}


def test_merge_nested_dicts():
    d1 = {"a": 1, "b": {"x": 10, "y": 20}}
    d2 = {"b": {"y": 30, "z": 40}, "c": 5}
    mk = MergeKey(raw="<<{+>}")
    result = merged(d1, d2, mk)
    assert result == {"a": 1, "b": {"x": 10, "y": 20, "z": 40}, "c": 5}


def test_merge_replace_mode():
    d1 = {"a": 1, "b": {"x": 10, "y": 20}}
    d2 = {"b": {"z": 30}, "c": 5}
    mk = MergeKey(raw="<<{~>}")
    result = merged(d1, d2, mk)
    assert result == {"a": 1, "b": {"x": 10, "y": 20}, "c": 5}


def test_merge_lists_append_mode():
    d1 = {"a": [1, 2], "b": 3}
    d2 = {"a": [3, 4], "c": 5}
    mk = MergeKey(raw="<<[+]{>}")
    result = merged(d1, d2, mk)
    assert result == {"a": [1, 2, 3, 4], "b": 3, "c": 5}


def test_merge_lists_replace_mode():
    d1 = {"a": [1, 2], "b": 3}
    d2 = {"a": [3, 4], "c": 5}
    mk = MergeKey(raw="<<[~]{>}")
    result = merged(d1, d2, mk)
    assert result == {"a": [1, 2], "b": 3, "c": 5}


def test_merge_lists_with_priority():
    d1 = {"a": [1, 2], "b": 3}
    d2 = {"a": [3, 4], "c": 5}
    mk = MergeKey(raw="<<[~<]{>}")
    result = merged(d1, d2, mk)
    assert result == {"a": [3, 4], "b": 3, "c": 5}


def test_merge_mixed_types():
    d1 = {"a": [1, 2], "b": {"x": 10}}
    d2 = {"a": 3, "b": [4, 5]}
    mk = MergeKey(raw="<<[+]{+<}")
    result = merged(d1, d2, mk)
    assert result == {"a": 3, "b": [4, 5]}


def test_merge_with_none_values():
    d1 = {"a": 1, "b": None}
    d2 = {"b": 2, "c": None}
    mk = MergeKey(raw="<<{>}")
    result = merged(d1, d2, mk)
    assert result == {"a": 1, "b": None, "c": None}


def test_merge_empty_dicts():
    d1 = {}
    d2 = {"a": 1}
    mk = MergeKey(raw="<<{>}")
    result = merged(d1, d2, mk)
    assert result == {"a": 1}


def test_merge_identical_dicts():
    d1 = {"a": 1, "b": 2}
    d2 = {"a": 1, "b": 2}
    mk = MergeKey(raw="<<{>}")
    result = merged(d1, d2, mk)
    assert result == {"a": 1, "b": 2}


def test_merge_nested_lists():
    d1 = {"a": [1, [2, 3]], "b": 4}
    d2 = {"a": [5, [6, 7]], "c": 8}
    mk = MergeKey(raw="<<[+]{>}")
    result = merged(d1, d2, mk)
    assert result == {"a": [1, [2, 3], 5, [6, 7]], "b": 4, "c": 8}


def test_merge_nested_dicts_with_lists():
    d1 = {"a": {"x": [1, 2]}, "b": 3}
    d2 = {"a": {"x": [3, 4], "y": 5}, "c": 6}
    mk = MergeKey(raw="<<[+]{+<}")
    result = merged(d1, d2, mk)
    assert result == {"a": {"x": [1, 2, 3, 4], "y": 5}, "b": 3, "c": 6}


def test_context_merge_with_large_objects():
    large_data1 = [i for i in range(100000)]
    large_data2 = [i for i in range(100000, 200000)]

    context1 = ShallowDict({"data1": large_data1, "common_key": "value1"})
    context2 = ShallowDict({"data2": large_data2, "common_key": "value2"})

    merged_context_existing = merged(context1, context2, MergeKey(raw="{+>}"))
    merged_context_new = merged(context1, context2, MergeKey(raw="{+<}"))

    # large objects are preserved as references, not copies
    assert merged_context_existing["data1"] is large_data1
    assert merged_context_existing["data2"] is large_data2
    assert merged_context_new["data1"] is large_data1
    assert merged_context_new["data2"] is large_data2

    # merge priority works correctly
    assert merged_context_existing["common_key"] == "value1"  # Existing preserved
    assert merged_context_new["common_key"] == "value2"  # New took priority
