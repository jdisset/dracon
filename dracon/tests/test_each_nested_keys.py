"""Tests for nested dictionary key evaluation in !each loops.

This test module verifies that dictionary keys inside !each loop templates
are properly evaluated during composition, not left as literal interpolation
strings.

Regression tests for: https://github.com/jeanplot/issues/XXX
"""

import pytest
from dracon import loads, resolve_all_lazy


def test_each_nested_mapping_keys_are_evaluated():
    """Keys in nested mappings within !each should be interpolated."""
    yaml = """
!define prefix: my
!define items: [a, b, c]

result:
  !each(item) "${items}":
    outer_${item}:
      ${prefix}_${item}: value_${item}
"""
    config = loads(yaml, raw_dict=True)
    resolve_all_lazy(config)

    # Verify outer keys are evaluated
    assert "outer_a" in config["result"]
    assert "outer_b" in config["result"]
    assert "outer_c" in config["result"]

    # Verify nested keys are evaluated (not literal ${...} strings)
    assert "my_a" in config["result"]["outer_a"]
    assert "my_b" in config["result"]["outer_b"]
    assert "my_c" in config["result"]["outer_c"]

    # Verify no unresolved interpolation strings in keys
    for outer_key, inner_dict in config["result"].items():
        assert not outer_key.startswith("${"), f"Unresolved outer key: {outer_key}"
        for inner_key in inner_dict.keys():
            assert not str(inner_key).startswith("${"), f"Unresolved inner key: {inner_key}"


def test_each_deeply_nested_mapping_keys():
    """Keys at multiple nesting levels should all be evaluated."""
    yaml = """
!define items: [x, y]

result:
  !each(i) "${items}":
    level1_${i}:
      level2_${i}:
        level3_${i}: deep_value_${i}
"""
    config = loads(yaml, raw_dict=True)
    resolve_all_lazy(config)

    # Check all levels
    assert "level1_x" in config["result"]
    assert "level2_x" in config["result"]["level1_x"]
    assert "level3_x" in config["result"]["level1_x"]["level2_x"]
    assert config["result"]["level1_x"]["level2_x"]["level3_x"] == "deep_value_x"

    assert "level1_y" in config["result"]
    assert "level2_y" in config["result"]["level1_y"]
    assert "level3_y" in config["result"]["level1_y"]["level2_y"]


def test_each_with_dict_items_nested_keys():
    """Nested keys using dict.items() loop variable should be evaluated."""
    yaml = """
!define colors:
  red: {hex: "#ff0000", light: "#ffcccc"}
  blue: {hex: "#0000ff", light: "#ccccff"}

styles:
  !each(c) "${colors.items()}":
    style_${c[0]}:
      ${c[1]['hex']}: ${c[1]['light']}
"""
    config = loads(yaml, raw_dict=True)
    resolve_all_lazy(config)

    # Verify outer keys
    assert "style_red" in config["styles"]
    assert "style_blue" in config["styles"]

    # Verify nested keys are the hex values, not interpolation strings
    red_style = config["styles"]["style_red"]
    assert "#ff0000" in red_style, f"Expected '#ff0000' key, got: {list(red_style.keys())}"
    assert red_style["#ff0000"] == "#ffcccc"

    blue_style = config["styles"]["style_blue"]
    assert "#0000ff" in blue_style, f"Expected '#0000ff' key, got: {list(blue_style.keys())}"


def test_each_nested_keys_no_literal_interpolation_strings():
    """Ensure no keys contain literal '${' after evaluation."""
    yaml = """
!define base: prefix
!define items:
  - {name: first, id: 1}
  - {name: second, id: 2}

result:
  !each(item) "${items}":
    ${base}_${item['name']}:
      id_${item['id']}: ${item['name']}
      ${item['name']}_key: ${item['id']}
"""
    config = loads(yaml, raw_dict=True)
    resolve_all_lazy(config)

    def check_no_interpolation_in_keys(d, path=""):
        """Recursively check that no keys contain '${' """
        if isinstance(d, dict):
            for key, value in d.items():
                key_str = str(key)
                assert "${" not in key_str, (
                    f"Found unresolved interpolation in key at {path}: {key_str}"
                )
                check_no_interpolation_in_keys(value, f"{path}.{key}")
        elif isinstance(d, list):
            for i, item in enumerate(d):
                check_no_interpolation_in_keys(item, f"{path}[{i}]")

    check_no_interpolation_in_keys(config)

    # Also verify expected structure
    assert "prefix_first" in config["result"]
    assert "prefix_second" in config["result"]
    assert "id_1" in config["result"]["prefix_first"]
    assert "first_key" in config["result"]["prefix_first"]


def test_each_nested_keys_with_complex_expressions():
    """Nested keys with complex expressions should be evaluated."""
    yaml = """
!define multiplier: 10
!define items: [1, 2, 3]

result:
  !each(n) "${items}":
    item_${n}:
      computed_${n * multiplier}: ${n * multiplier}
      str_${str(n).zfill(3)}: padded
"""
    config = loads(yaml, raw_dict=True)
    resolve_all_lazy(config)

    # Verify computed keys
    assert "computed_10" in config["result"]["item_1"]
    assert "computed_20" in config["result"]["item_2"]
    assert "computed_30" in config["result"]["item_3"]

    # Verify string manipulation in keys
    assert "str_001" in config["result"]["item_1"]
    assert "str_002" in config["result"]["item_2"]
    assert "str_003" in config["result"]["item_3"]


def test_each_nested_sequence_with_mapping_keys():
    """Nested sequences containing mappings should have their keys evaluated."""
    yaml = """
!define items: [a, b]

result:
  !each(item) "${items}":
    group_${item}:
      - ${item}_first: 1
      - ${item}_second: 2
"""
    config = loads(yaml, raw_dict=True)
    resolve_all_lazy(config)

    # Verify the list contains dicts with evaluated keys
    group_a = config["result"]["group_a"]
    assert isinstance(group_a, list)
    assert len(group_a) == 2
    assert "a_first" in group_a[0]
    assert "a_second" in group_a[1]

    group_b = config["result"]["group_b"]
    assert "b_first" in group_b[0]
    assert "b_second" in group_b[1]


def test_each_preserves_non_interpolated_keys():
    """Static keys should be preserved alongside interpolated keys."""
    yaml = """
!define items: [x]

result:
  !each(i) "${items}":
    dynamic_${i}:
      static_key: static_value
      ${i}_dynamic: dynamic_value
"""
    config = loads(yaml, raw_dict=True)
    resolve_all_lazy(config)

    inner = config["result"]["dynamic_x"]
    assert "static_key" in inner
    assert "x_dynamic" in inner
    assert inner["static_key"] == "static_value"
    assert inner["x_dynamic"] == "dynamic_value"


def test_each_nested_keys_with_context_variable():
    """Nested keys should have access to outer context variables."""
    yaml = """
!define global_prefix: G
!define items: [1, 2]

result:
  !each(n) "${items}":
    ${global_prefix}_${n}:
      ${global_prefix}_inner_${n}: value
"""
    config = loads(yaml, raw_dict=True)
    resolve_all_lazy(config)

    assert "G_1" in config["result"]
    assert "G_2" in config["result"]
    assert "G_inner_1" in config["result"]["G_1"]
    assert "G_inner_2" in config["result"]["G_2"]
