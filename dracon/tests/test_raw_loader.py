"""Tests for the raw: and rawpkg: include loaders."""

import pytest
from pathlib import Path
from dracon import load


def test_raw_loader_returns_string_not_yaml(tmp_path):
    """raw: loader must not parse file content as YAML."""
    md = tmp_path / "focus.md"
    md.write_text("# Header\nkey: value\n- item\n| pipe")

    config_file = tmp_path / "config.yaml"
    config_file.write_text(f"content: !include raw:{md}")

    result = load(str(config_file), raw_dict=True)
    assert result["content"] == "# Header\nkey: value\n- item\n| pipe"


def test_raw_loader_preserves_colons_and_hashes(tmp_path):
    """Colons and hashes in markdown must not be parsed as YAML keys/comments."""
    md = tmp_path / "prompt.md"
    md.write_text("## Research Tools — USE THESE:\n- BioMCP: primary tool\n# not a yaml key")

    config_file = tmp_path / "config.yaml"
    config_file.write_text(f"prompt: !include raw:{md}")

    result = load(str(config_file), raw_dict=True)
    assert "BioMCP: primary tool" in result["prompt"]
    assert "# not a yaml key" in result["prompt"]


def test_raw_loader_missing_file_raises(tmp_path):
    """raw: loader raises FileNotFoundError for missing files."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(f"x: !include raw:{tmp_path}/nonexistent.md")

    with pytest.raises(Exception):  # FileNotFoundError wraps into dracon error
        load(str(config_file), raw_dict=True)


def test_raw_loader_multiline_preserved(tmp_path):
    """Newlines in loaded text must be preserved exactly."""
    content = "line1\nline2\nline3\n"
    md = tmp_path / "text.md"
    md.write_text(content)

    config_file = tmp_path / "config.yaml"
    config_file.write_text(f"text: !include raw:{md}")

    result = load(str(config_file), raw_dict=True)
    assert result["text"] == content


def test_rawpkg_loader_reads_package_file(tmp_path):
    """rawpkg: loader must read a real package file without YAML parsing."""
    # Use dracon's own test config as the target — it contains YAML structure
    config_file = tmp_path / "config.yaml"
    config_file.write_text("value: !include rawpkg:dracon:tests/configs/simple.yaml")

    result = load(str(config_file), raw_dict=True)
    # The file content should be a string (not parsed dict)
    assert isinstance(result["value"], str)
    # And it should contain YAML-like content
    assert ":" in result["value"]
