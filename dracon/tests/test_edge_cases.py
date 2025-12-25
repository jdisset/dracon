from dracon import DraconLoader, resolve_all_lazy


def test_edge_cases():
    loader = DraconLoader(enable_interpolation=True)
    config = loader.load('pkg:dracon:tests/configs/edge_cases.yaml')

    print(f"Config: {config}")
    resolve_all_lazy(config)

    assert config["dotted.keys"]["nested.value"] == "simple_value"
    assert config["dotted.keys"]["another.dotted.key"] == "another_value"

    assert config.value == "not_an_internal_value"
    assert config.context == "not_an_internal_context"
    assert config.tag == "not_an_internal_tag"
    assert config.anchor == "not_an_internal_anchor"

    assert config.each_with_dots["item.1"] == "value_1"
    assert config.each_with_dots["item.2"] == "value_2"
    assert config.each_with_dots["item.3"] == "value_3"
    assert config.each_with_dots["nested.item.1"] == "nested_value_1"
    assert config.each_with_dots["nested.item.2"] == "nested_value_2"
    assert config.each_with_dots["nested.item.3"] == "nested_value_3"

    assert config.nested.level1["dotted.key"] == "deep_value"
    assert config.nested.array[0]["key.with.dots"] == "array_value1"
    assert config.nested.array[1]["key.with.dots"] == "array_value2"

    assert config["interpolated.keys.dynamic"].value == "interpolated_value"

    # Test nested dict key interpolation in !each loops
    # This regression test ensures that keys in nested mappings within !each loops
    # are properly evaluated, not left as literal interpolation strings
    nested_keys_result = config.each_with_nested_keys
    assert "top_first" in nested_keys_result, f"Expected 'top_first' key, got: {nested_keys_result.keys()}"
    assert "top_second" in nested_keys_result, f"Expected 'top_second' key, got: {nested_keys_result.keys()}"

    # Verify nested keys are resolved (not literal ${...} strings)
    first_dict = nested_keys_result["top_first"]
    first_keys = list(first_dict.keys())
    assert "mykey_first" in first_keys, f"Expected 'mykey_first' key in nested dict, got: {first_keys}"
    assert "other_first" in first_keys, f"Expected 'other_first' key in nested dict, got: {first_keys}"
    # Verify no unresolved interpolation strings in keys
    assert not any("${" in str(k) for k in first_keys), f"Found unresolved interpolation in keys: {first_keys}"

    second_dict = nested_keys_result["top_second"]
    second_keys = list(second_dict.keys())
    assert "mykey_second" in second_keys, f"Expected 'mykey_second' key in nested dict, got: {second_keys}"
    assert "other_second" in second_keys, f"Expected 'other_second' key in nested dict, got: {second_keys}"
    # Verify values are also resolved
    assert first_dict["mykey_first"] == 100
    assert second_dict["mykey_second"] == 200

    # assert config.reference_test.simple_ref == "simple_value"
    # assert config.reference_test.nested_ref == "deep_value"

    # assert config["base.with.dots"].key1 == "base_value1"
    # assert config["base.with.dots"].key2 == "override_value2"
    # assert config["base.with.dots"]["nested.key"] == "override_nested"

    # deferred_node = config["deferred.node"]
    # print(f"Deferred type: {type(deferred_node)}")
    # constructed = deferred_node.construct()
    # print(f"Constructed: {constructed}")
    # assert constructed["dotted.key"] == "deferred_value"
    # assert constructed.reference == "simple_value"

    # assert config.complex["first.level"]["inner.value"] == "complex_inner_value"
    # assert config.complex["first.level"].reference == "complex_inner_value"
