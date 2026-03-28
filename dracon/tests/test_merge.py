from dracon.merge import merged, MergeKey, MergeMode, MergePriority
from dracon.utils import ShallowDict
import pytest
from dracon import DraconLoader
import dracon as dr
from dracon.nodes import DraconMappingNode, DraconScalarNode


def test_basic_merge():
    d1 = {"a": 1, "b": 2}
    d2 = {"b": 3, "c": 4}
    # Default key uses {+>} - existing wins
    mk = MergeKey(raw="<<")  # Equivalent to {+>} implicitly
    result = merged(d1, d2, mk)
    assert result == {"a": 1, "b": 2, "c": 4}


def test_merge_with_new_priority():
    d1 = {"a": 1, "b": 2}
    d2 = {"b": 3, "c": 4}
    # Use {+<} - new wins
    mk = MergeKey(raw="<<{+<}")
    result = merged(d1, d2, mk)
    assert result == {"a": 1, "b": 3, "c": 4}


def test_merge_with_new_priority_alternate_syntax():
    d1 = {"a": 1, "b": 2}
    d2 = {"b": 3, "c": 4}
    # Use {<+} - new wins (order inside {} shouldn't matter)
    mk = MergeKey(raw="<<{<+}")
    result = merged(d1, d2, mk)
    assert result == {"a": 1, "b": 3, "c": 4}


def test_merge_nested_dicts():
    d1 = {"a": 1, "b": {"x": 10, "y": 20}}
    d2 = {"b": {"y": 30, "z": 40}, "c": 5}
    # Use {+>} - existing wins (default-like)
    mk = MergeKey(raw="<<{+>}")
    result = merged(d1, d2, mk)
    assert result == {"a": 1, "b": {"x": 10, "y": 20, "z": 40}, "c": 5}


def test_merge_nested_dicts_new_wins():
    d1 = {"a": 1, "b": {"x": 10, "y": 20}}
    d2 = {"b": {"y": 30, "z": 40}, "c": 5}
    # Use {+<} - new wins
    mk = MergeKey(raw="<<{+<}")
    result = merged(d1, d2, mk)
    # 'y' should be 30 from d2
    assert result == {"a": 1, "b": {"x": 10, "y": 30, "z": 40}, "c": 5}


def test_merge_replace_mode():
    d1 = {"a": 1, "b": {"x": 10, "y": 20}}
    d2 = {"b": {"z": 30}, "c": 5}
    # Use {~>} - replace mode, existing wins
    mk = MergeKey(raw="<<{~>}")
    result = merged(d1, d2, mk)
    # 'b' from d1 replaces 'b' from d2 entirely
    assert result == {"a": 1, "b": {"x": 10, "y": 20}, "c": 5}


def test_merge_lists_append_mode():
    d1 = {"a": [1, 2], "b": 3}
    d2 = {"a": [3, 4], "c": 5}
    # Use [+] - append mode, existing first (default priority for list append)
    mk = MergeKey(raw="<<[+]")  # Implicitly [+>]
    result = merged(d1, d2, mk)
    assert result == {"a": [1, 2, 3, 4], "b": 3, "c": 5}


def test_merge_lists_replace_mode():
    d1 = {"a": [1, 2], "b": 3}
    d2 = {"a": [3, 4], "c": 5}
    # Use [~] - replace mode, existing wins (default priority for list replace)
    mk = MergeKey(raw="<<[~]")  # Implicitly [~>]
    result = merged(d1, d2, mk)
    assert result == {"a": [1, 2], "b": 3, "c": 5}


def test_merge_lists_with_priority():
    d1 = {"a": [1, 2], "b": 3}
    d2 = {"a": [3, 4], "c": 5}
    # Use [~<] - replace mode, new wins
    mk = MergeKey(raw="<<[~<]")
    result = merged(d1, d2, mk)
    assert result == {"a": [3, 4], "b": 3, "c": 5}


def test_merge_mixed_types():
    d1 = {"a": [1, 2], "b": {"x": 10}}
    d2 = {"a": 3, "b": [4, 5]}
    # Use {+<}[+] - dict: new wins append, list: existing wins append
    mk = MergeKey(raw="<<{+<}[+>]")  # Explicit list priority >
    result = merged(d1, d2, mk)
    # 'a': d2 (3) wins over d1 ([1,2])
    # 'b': d2 ([4,5]) wins over d1 ({x:10})
    assert result == {"a": 3, "b": [4, 5]}


def test_merge_with_none_values():
    d1 = {"a": 1, "b": None}
    d2 = {"b": 2, "c": None}
    # Use {+>} - existing wins
    mk = MergeKey(raw="<<{+>}")
    result = merged(d1, d2, mk)
    assert result == {"a": 1, "b": None, "c": None}  # Existing None wins over 2


def test_merge_empty_dicts():
    d1 = {}
    d2 = {"a": 1}
    mk = MergeKey(raw="<<{+>}")
    result = merged(d1, d2, mk)
    assert result == {"a": 1}


def test_merge_identical_dicts():
    d1 = {"a": 1, "b": 2}
    d2 = {"a": 1, "b": 2}
    mk = MergeKey(raw="<<{+>}")
    result = merged(d1, d2, mk)
    assert result == {"a": 1, "b": 2}


def test_merge_nested_lists():
    d1 = {"a": [1, [2, 3]], "b": 4}
    d2 = {"a": [5, [6, 7]], "c": 8}
    # Use [+] - append mode, existing first
    mk = MergeKey(raw="<<[+>]")  # Explicit list priority >
    result = merged(d1, d2, mk)
    assert result == {"a": [1, [2, 3], 5, [6, 7]], "b": 4, "c": 8}


def test_merge_nested_dicts_with_lists():
    d1 = {"a": {"x": [1, 2]}, "b": 3}
    d2 = {"a": {"x": [3, 4], "y": 5}, "c": 6}
    # Use {+<}[+>] - dict: new wins append, list: existing wins append
    mk = MergeKey(raw="<<{+<}[+>]")
    result = merged(d1, d2, mk)
    # 'a': merged recursively, new wins for 'y', list 'x' appended existing first
    assert result == {"a": {"x": [1, 2, 3, 4], "y": 5}, "b": 3, "c": 6}


def test_merge_commandline_sequence_direct():
    """Test the exact merge sequence from commandline.py directly."""
    include_result = {
        "environment": "local",
        "log_level": "DEBUG",
        "workers": 2,
        "database": {
            "host": "db.local",
            "username": "local_user",
            "password": "local_password",
            "port": 5432,
        },
        "output_path": "/data/local_output/${base_output_path}",
    }
    cli_overrides = {"environment": "dev", "workers": '4', "database": {"port": '5433'}}
    mk = MergeKey(raw="<<{<+}")  # Equivalent merge key used in commandline.py's generated YAML
    final_result = merged(include_result, cli_overrides, mk)

    assert final_result["environment"] == "dev"  # CLI override should win
    assert final_result["workers"] == '4'  # CLI override should win (comes as string)
    assert final_result["database"]["host"] == "db.local"  # From include
    assert final_result["database"]["port"] == '5433'  # CLI override should win (comes as string)
    assert final_result["database"]["username"] == "local_user"  # From include
    assert final_result["log_level"] == "DEBUG"  # From include (not overridden)
    assert final_result["output_path"] == "/data/local_output/${base_output_path}"  # From include


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


# Add necessary fixtures if not already present in the file
@pytest.fixture(scope="module")
def merge_order_files(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("merge_order_configs")

    base_data = """
    value: base
    level1:
      nested: base_nested
    """
    (tmp_path / "base.yaml").write_text(base_data)

    override1_data = """
    value: override1
    level1:
      nested: override1_nested
    new_key1: val1
    """
    (tmp_path / "override1.yaml").write_text(override1_data)

    override2_data = """
    value: override2 # This should win
    level1:
      nested: override2_nested # This should win
    new_key2: val2
    """
    (tmp_path / "override2.yaml").write_text(override2_data)

    # YAML demonstrating sequential merge attempts at the same level
    # We use slightly different merge keys just to make them distinct map keys
    # The merge key itself dictates the merge strategy ({<+} -> new wins)
    main_yaml = f"""
    <<{{<+}}base: !include file:{tmp_path / "base.yaml"}
    <<{{<+}}ov1: !include file:{tmp_path / "override1.yaml"}
    <<{{<+}}ov2: !include file:{tmp_path / "override2.yaml"}
    final_key: final_value
    """
    (tmp_path / "main_merge_order.yaml").write_text(main_yaml)

    return tmp_path


def test_sequential_merge_order_at_same_level(merge_order_files):
    """
    Verify that multiple merge keys at the same level are processed
    in their order of appearance in the YAML file.
    """
    config = dr.load(merge_order_files / "main_merge_order.yaml", raw_dict=True)

    # Expected result: base merged, then ov1 merged onto it, then ov2 merged onto that.
    # Since the merge key is {<+} (new wins), the latest definition wins.
    expected = {
        "value": "override2",  # From override2 (last merge)
        "level1": {
            "nested": "override2_nested"  # From override2 (last merge)
        },
        "new_key1": "val1",  # From override1
        "new_key2": "val2",  # From override2
        "final_key": "final_value",  # Original key in main map
    }

    assert config == expected


# Test with a different merge priority ({>+} -> existing wins)
def test_sequential_merge_order_existing_wins(merge_order_files):
    """
    Verify merge order with existing wins priority.
    """
    # Modify the main YAML to use {>+} merge key (existing wins)
    main_yaml_existing_wins = f"""
    <<{{>+}}base: !include file:{merge_order_files / "base.yaml"}
    <<{{>+}}ov1: !include file:{merge_order_files / "override1.yaml"}
    <<{{>+}}ov2: !include file:{merge_order_files / "override2.yaml"}
    final_key: final_value
    """
    main_file_existing = merge_order_files / "main_merge_order_existing.yaml"
    main_file_existing.write_text(main_yaml_existing_wins)

    config = dr.load(main_file_existing, raw_dict=True)

    # Expected result: base merged, then ov1 merged (base wins conflicts),
    # then ov2 merged (result of base+ov1 wins conflicts).
    expected = {
        "value": "base",  # From base (first merge)
        "level1": {
            "nested": "base_nested"  # From base (first merge)
        },
        "new_key1": "val1",  # From override1
        "new_key2": "val2",  # From override2
        "final_key": "final_value",  # Original key in main map
    }
    assert config == expected


# ── bare duplicate merge keys ──────────────────────────────────────────────


@pytest.fixture(scope="module")
def bare_merge_files(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("bare_merge")
    (tmp / "base.yaml").write_text("value: base\nlevel1:\n  nested: base_nested\n")
    (tmp / "override1.yaml").write_text("value: override1\nlevel1:\n  nested: override1_nested\nnew_key1: val1\n")
    (tmp / "override2.yaml").write_text("value: override2\nlevel1:\n  nested: override2_nested\nnew_key2: val2\n")
    return tmp


def test_bare_duplicate_merge_keys(bare_merge_files):
    """Two bare <<{<+}: keys (identical key strings) should both be processed."""
    p = bare_merge_files
    main = p / "main.yaml"
    main.write_text(
        f"<<{{<+}}: !include file:{p / 'base.yaml'}\n"
        f"<<{{<+}}: !include file:{p / 'override1.yaml'}\n"
        f"final: done\n"
    )
    config = dr.load(main, raw_dict=True)
    assert config == {
        "value": "override1",
        "level1": {"nested": "override1_nested"},
        "new_key1": "val1",
        "final": "done",
    }


def test_bare_duplicate_merge_keys_default(bare_merge_files):
    """Two bare <<: keys with default merge semantics (existing wins)."""
    p = bare_merge_files
    main = p / "main_default.yaml"
    main.write_text(
        f"<<: !include file:{p / 'base.yaml'}\n"
        f"<<: !include file:{p / 'override1.yaml'}\n"
        f"final: done\n"
    )
    config = dr.load(main, raw_dict=True)
    # default is {+>} (existing wins), so base values are kept for conflicts
    assert config == {
        "value": "base",
        "level1": {"nested": "base_nested"},
        "new_key1": "val1",
        "final": "done",
    }


def test_bare_duplicate_merge_keys_ordering(bare_merge_files):
    """Three bare <<{<+}: keys -- last one wins on conflicts."""
    p = bare_merge_files
    main = p / "main_three.yaml"
    main.write_text(
        f"<<{{<+}}: !include file:{p / 'base.yaml'}\n"
        f"<<{{<+}}: !include file:{p / 'override1.yaml'}\n"
        f"<<{{<+}}: !include file:{p / 'override2.yaml'}\n"
        f"final: done\n"
    )
    config = dr.load(main, raw_dict=True)
    assert config == {
        "value": "override2",
        "level1": {"nested": "override2_nested"},
        "new_key1": "val1",
        "new_key2": "val2",
        "final": "done",
    }


def test_mixed_bare_and_suffixed_merge_keys(bare_merge_files):
    """Bare <<{<+}: and suffixed <<{<+}extra: coexist in the same mapping."""
    p = bare_merge_files
    main = p / "main_mixed.yaml"
    main.write_text(
        f"<<{{<+}}: !include file:{p / 'base.yaml'}\n"
        f"<<{{<+}}: !include file:{p / 'override1.yaml'}\n"
        f"<<{{<+}}extra: !include file:{p / 'override2.yaml'}\n"
        f"final: done\n"
    )
    config = dr.load(main, raw_dict=True)
    assert config == {
        "value": "override2",
        "level1": {"nested": "override2_nested"},
        "new_key1": "val1",
        "new_key2": "val2",
        "final": "done",
    }
