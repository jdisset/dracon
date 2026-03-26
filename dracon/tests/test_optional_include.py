"""Tests for !include? optional include and isfile/isdir in include contexts."""
import pytest
from dracon.loader import DraconLoader
from dracon.include import compose_from_include_str
from dracon.diagnostics import DraconError


def test_optional_include_missing_file(tmp_path):
    """!include? with a missing file should silently drop the key."""
    yaml_content = f"""
    base_val: 1
    optional: !include? file:{tmp_path}/nonexistent.yaml
    """
    loader = DraconLoader(enable_interpolation=True)
    config = loader.loads(yaml_content)
    assert config.base_val == 1
    assert not hasattr(config, 'optional')


def test_optional_include_existing_file(tmp_path):
    """!include? with an existing file should work like !include."""
    override = tmp_path / "override.yaml"
    override.write_text("value: 42\n")
    yaml_content = f"""
    result: !include? file:{override}
    """
    loader = DraconLoader(enable_interpolation=True)
    config = loader.loads(yaml_content)
    assert config.result.value == 42


def test_optional_include_merge_missing(tmp_path):
    """<<: !include? with a missing file should be a no-op merge."""
    yaml_content = f"""
    base: 1
    extra: 2
    <<: !include? file:{tmp_path}/nonexistent.yaml
    """
    loader = DraconLoader(enable_interpolation=True)
    config = loader.loads(yaml_content)
    assert config.base == 1
    assert config.extra == 2


def test_optional_include_merge_existing(tmp_path):
    """<<: !include? with an existing file should merge normally."""
    override = tmp_path / "override.yaml"
    override.write_text("merged_key: hello\n")
    yaml_content = f"""
    base: 1
    <<: !include? file:{override}
    """
    loader = DraconLoader(enable_interpolation=True)
    config = loader.loads(yaml_content)
    assert config.base == 1
    assert config.merged_key == "hello"


def test_mandatory_include_still_errors(tmp_path):
    """!include (without ?) should still raise on missing file."""
    yaml_content = f"""
    val: !include file:{tmp_path}/nonexistent.yaml
    """
    loader = DraconLoader(enable_interpolation=True)
    with pytest.raises((FileNotFoundError, DraconError)):
        loader.loads(yaml_content)


def test_optional_include_nested(tmp_path):
    """!include? deep in a nested structure should work."""
    yaml_content = f"""
    top:
      nested:
        deep: !include? file:{tmp_path}/nonexistent.yaml
        keep: yes
    """
    loader = DraconLoader(enable_interpolation=True)
    config = loader.loads(yaml_content)
    assert config.top.nested.keep == "yes"
    assert not hasattr(config.top.nested, 'deep')


def test_optional_include_with_interpolated_path(tmp_path):
    """!include? with an interpolated path that resolves to nonexistent."""
    yaml_content = f"""
    !define dataset: "missing_dataset"
    !define model: "missing_model"
    result: !include? file:{tmp_path}/${{dataset}}_${{model}}.yaml
    fallback: default
    """
    loader = DraconLoader(enable_interpolation=True)
    config = loader.loads(yaml_content)
    assert not hasattr(config, 'result')
    assert config.fallback == "default"


def test_optional_include_multiple(tmp_path):
    """Multiple !include? — some exist, some don't."""
    exists = tmp_path / "exists.yaml"
    exists.write_text("val: found\n")
    yaml_content = f"""
    a: !include? file:{exists}
    b: !include? file:{tmp_path}/missing.yaml
    c: kept
    """
    loader = DraconLoader(enable_interpolation=True)
    config = loader.loads(yaml_content)
    assert config.a.val == "found"
    assert not hasattr(config, 'b')
    assert config.c == "kept"
