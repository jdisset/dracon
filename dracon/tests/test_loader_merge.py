import pytest
from dracon import load


@pytest.fixture(scope="module")
def config_files(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("configs")
    base_content = """
a: 1
b:
  x: 10
l: [1, 2]
common: base_common
"""
    override_content = """
a: 2 # override
b:
  y: 20 # add
l: [3, 4] # replace
common: override_common
"""
    append_content = """
l: [5, 6] # append
b:
  x: 100 # override existing in base
  z: 30 # add
"""

    base_file = tmp_path / "merge_base.yaml"
    override_file = tmp_path / "merge_override.yaml"
    append_file = tmp_path / "merge_append.yaml"

    base_file.write_text(base_content)
    override_file.write_text(override_content)
    append_file.write_text(append_content)

    return {
        "base": base_file,
        "override": override_file,
        "append": append_file,
    }


def test_load_single_file(config_files):
    config = load(config_files["base"], raw_dict=True)
    assert config == {"a": 1, "b": {"x": 10}, "l": [1, 2], "common": "base_common"}


def test_load_multiple_default_merge(config_files):
    # Default merge: <<{<+}[<~] (Dict: New wins, recursive append; List: New wins, replace)
    config = load([config_files["base"], config_files["override"]], raw_dict=True)
    expected = {
        "a": 2,  # override wins
        "b": {"x": 10, "y": 20},  # recursive append
        "l": [3, 4],  # override wins (list replace)
        "common": "override_common",  # override wins
    }
    assert config == expected


def test_load_multiple_default_merge_reverse(config_files):
    # Default merge: <<{<+}[<~] (Dict: New wins, recursive append; List: New wins, replace)
    # Order matters for priority
    config = load([config_files["override"], config_files["base"]], raw_dict=True)
    expected = {
        "a": 1,  # base wins (it's the "new" one in the merge)
        "b": {"y": 20, "x": 10},  # recursive append
        "l": [1, 2],  # base wins (list replace)
        "common": "base_common",  # base wins
    }
    assert config == expected


def test_load_multiple_custom_merge_dict_existing_wins(config_files):
    # Custom merge: <<{>+}[<~] (Dict: Existing wins, recursive append; List: New wins, replace)
    config = load(
        [config_files["base"], config_files["override"]], merge_key="<<{>+}[<~]", raw_dict=True
    )
    expected = {
        "a": 1,  # base wins
        "b": {"x": 10, "y": 20},  # recursive append (values merged)
        "l": [3, 4],  # override wins (list replace)
        "common": "base_common",  # base wins
    }
    assert config == expected


def test_load_multiple_custom_merge_list_append(config_files):
    # Custom merge: <<{<+}[+>] (Dict: New wins, recursive append; List: Existing wins, append)
    config = load(
        [config_files["base"], config_files["override"]], merge_key="<<{<+}[+>]", raw_dict=True
    )
    expected = {
        "a": 2,  # override wins
        "b": {"x": 10, "y": 20},  # recursive append
        "l": [1, 2, 3, 4],  # append override to base
        "common": "override_common",  # override wins
    }
    assert config == expected


def test_load_three_files(config_files):
    # base, then override, then append
    # Default merge: <<{<+}[<~]
    config = load(
        [config_files["base"], config_files["override"], config_files["append"]], raw_dict=True
    )
    # Step 1: base + override -> {'a': 2, 'b': {'x': 10, 'y': 20}, 'l': [3, 4], 'common': 'override_common'}
    # Step 2: result + append
    expected = {
        "a": 2,  # from override (not in append)
        "b": {
            "x": 100,
            "y": 20,
            "z": 30,
        },  # merged: override y=20, append adds z=30, append overrides x=100
        "l": [5, 6],  # append wins (list replace)
        "common": "override_common",  # from override (not in append)
    }
    assert config == expected


def test_load_non_mapping_base(tmp_path):
    list_file = tmp_path / "list.yaml"
    list_file.write_text("- item1\n- item2")
    dict_file = tmp_path / "dict.yaml"
    dict_file.write_text("a: 1")

    # load list first, then dict. Should replace.
    config = load([list_file, dict_file], raw_dict=True)
    assert config == {"a": 1}

    # Load dict first, then list. Should replace.
    config = load([dict_file, list_file], raw_dict=True)
    assert config == ["item1", "item2"]
