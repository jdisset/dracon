import pytest
from pydantic import ValidationError
from dracon.merge import MergeKey, MergeMode, MergePriority


def test_merge_key_initialization():
    mk = MergeKey(raw="<<{+<}")
    assert mk.dict_mode == MergeMode.APPEND
    assert mk.dict_priority == MergePriority.NEW
    assert mk.list_mode == MergeMode.REPLACE
    assert mk.list_priority == MergePriority.EXISTING


def test_merge_key_is_merge_key():
    assert MergeKey.is_merge_key("<<{+<}")
    assert MergeKey.is_merge_key("<<[+]{<}")
    assert not MergeKey.is_merge_key("normal_key")


def test_merge_key_dict_mode_and_priority():
    mk = MergeKey(raw="<<{+<}")
    assert mk.dict_mode == MergeMode.APPEND
    assert mk.dict_priority == MergePriority.NEW

    mk = MergeKey(raw="<<{~>}")
    assert mk.dict_mode == MergeMode.REPLACE
    assert mk.dict_priority == MergePriority.EXISTING


def test_merge_key_list_mode_and_priority():
    mk = MergeKey(raw="<<[+<]")
    assert mk.list_mode == MergeMode.APPEND
    assert mk.list_priority == MergePriority.NEW

    mk = MergeKey(raw="<<[~>]")
    assert mk.list_mode == MergeMode.REPLACE
    assert mk.list_priority == MergePriority.EXISTING


def test_merge_key_depth():
    mk = MergeKey(raw="<<{+2<}")
    assert mk.dict_depth == 2
    assert mk.list_depth is None

    mk = MergeKey(raw="<<[+3]{+2<}")
    assert mk.dict_depth == 2
    assert mk.list_depth == 3


def test_merge_key_combined_options():
    mk = MergeKey(raw="<<[+<]{~>}")
    assert mk.dict_mode == MergeMode.REPLACE
    assert mk.dict_priority == MergePriority.EXISTING
    assert mk.list_mode == MergeMode.APPEND
    assert mk.list_priority == MergePriority.NEW


def test_merge_key_invalid_combinations():
    with pytest.raises(ValidationError):
        MergeKey(raw="<<{+~}")

    with pytest.raises(ValidationError):
        MergeKey(raw="<<{<>}")


@pytest.mark.parametrize(
    "raw,expected_dict_mode,expected_dict_priority,expected_list_mode,expected_list_priority",
    [
        ("<<{+<}", MergeMode.APPEND, MergePriority.NEW, MergeMode.REPLACE, MergePriority.EXISTING),
        (
            "<<[~]{>}",
            MergeMode.APPEND,
            MergePriority.EXISTING,
            MergeMode.REPLACE,
            MergePriority.EXISTING,
        ),
        (
            "<<[+]{~<}",
            MergeMode.REPLACE,
            MergePriority.NEW,
            MergeMode.APPEND,
            MergePriority.EXISTING,
        ),
        ("<<", MergeMode.APPEND, MergePriority.EXISTING, MergeMode.REPLACE, MergePriority.EXISTING),
    ],
)

def test_merge_key_various_combinations(
    raw, expected_dict_mode, expected_dict_priority, expected_list_mode, expected_list_priority
):
    mk = MergeKey(raw=raw)
    assert mk.dict_mode == expected_dict_mode
    assert mk.dict_priority == expected_dict_priority
    assert mk.list_mode == expected_list_mode
    assert mk.list_priority == expected_list_priority


def test_merge_key_empty_options():
    mk = MergeKey(raw="<<")
    assert mk.dict_mode == MergeMode.APPEND
    assert mk.dict_priority == MergePriority.EXISTING
    assert mk.list_mode == MergeMode.REPLACE
    assert mk.list_priority == MergePriority.EXISTING


def test_merge_key_only_dict_options():
    mk = MergeKey(raw="<<{+<}")
    assert mk.dict_mode == MergeMode.APPEND
    assert mk.dict_priority == MergePriority.NEW
    assert mk.list_mode == MergeMode.REPLACE
    assert mk.list_priority == MergePriority.EXISTING


def test_merge_key_only_list_options():
    mk = MergeKey(raw="<<[~>]")
    assert mk.dict_mode == MergeMode.APPEND
    assert mk.dict_priority == MergePriority.EXISTING
    assert mk.list_mode == MergeMode.REPLACE
    assert mk.list_priority == MergePriority.EXISTING


def test_merge_key_multiple_depth_specifications():
    mk = MergeKey(raw="<<[+2]{+3<}")
    assert mk.dict_depth == 3
    assert mk.list_depth == 2


def test_merge_key_ignore_invalid_depth():
    mk = MergeKey(raw="<<{+invalid<}")
    assert mk.dict_depth is None
    assert mk.dict_mode == MergeMode.APPEND
    assert mk.dict_priority == MergePriority.NEW
