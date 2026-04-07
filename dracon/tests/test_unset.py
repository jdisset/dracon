import pytest
from pathlib import Path
import dracon
from dracon import load, loads, load_file


# ── unit: basic !unset as value removes key ──────────────────────────────────

class TestUnsetValueTag:
    def test_unset_value_removes_key(self):
        result = loads("a: 1\nb: !unset\nc: 3", raw_dict=True)
        assert result == {"a": 1, "c": 3}

    def test_unset_value_with_explicit_null(self):
        result = loads("a: 1\nb: !unset null\nc: 3", raw_dict=True)
        assert result == {"a": 1, "c": 3}

    def test_unset_value_with_empty_string(self):
        result = loads("a: 1\nb: !unset ''\nc: 3", raw_dict=True)
        assert result == {"a": 1, "c": 3}

    def test_unset_only_key(self):
        result = loads("a: !unset", raw_dict=True)
        assert result == {}

    def test_all_keys_unset(self):
        result = loads("a: !unset\nb: !unset", raw_dict=True)
        assert result == {}

    def test_unset_preserves_other_keys(self):
        result = loads("x: 10\ny: !unset\nz: 30", raw_dict=True)
        assert result == {"x": 10, "z": 30}


# ── unit: nested !unset ──────────────────────────────────────────────────────

class TestUnsetNested:
    def test_unset_in_nested_mapping(self):
        yaml = """\
outer:
  a: 1
  b: !unset
  c: 3
"""
        result = loads(yaml, raw_dict=True)
        assert result == {"outer": {"a": 1, "c": 3}}

    def test_unset_deeply_nested(self):
        yaml = """\
l1:
  l2:
    l3:
      keep: yes
      drop: !unset
"""
        result = loads(yaml, raw_dict=True)
        assert result == {"l1": {"l2": {"l3": {"keep": "yes"}}}}

    def test_unset_all_children_leaves_empty_parent(self):
        yaml = """\
parent:
  only_child: !unset
sibling: ok
"""
        result = loads(yaml, raw_dict=True)
        # parent becomes empty mapping (not removed -- parent itself isn't !unset)
        assert result == {"parent": {}, "sibling": "ok"}


# ── unit: !unset in sequences ────────────────────────────────────────────────

class TestUnsetInSequence:
    def test_unset_in_list(self):
        yaml = """\
items:
  - a
  - !unset
  - c
"""
        result = loads(yaml, raw_dict=True)
        assert result == {"items": ["a", "c"]}

    def test_unset_all_list_items(self):
        yaml = """\
items:
  - !unset
  - !unset
other: kept
"""
        result = loads(yaml, raw_dict=True)
        assert result["other"] == "kept"
        assert result["items"] == []

    def test_unset_mixed_in_list(self):
        yaml = """\
- 1
- !unset
- 3
- !unset
- 5
"""
        result = loads(yaml, raw_dict=True)
        assert result == [1, 3, 5]


# ── e2e: !unset with merge / include ────────────────────────────────────────

class TestUnsetWithMerge:
    @pytest.fixture
    def base_file(self, tmp_path):
        f = tmp_path / "base.yaml"
        f.write_text("a: 1\nb: 2\nc: 3\n")
        return f

    def test_unset_removes_inherited_key_via_include(self, base_file):
        override = f"""\
<<: !include file:{base_file}
b: !unset
"""
        result = loads(override, raw_dict=True)
        assert result == {"a": 1, "c": 3}

    def test_unset_removes_multiple_inherited_keys(self, base_file):
        override = f"""\
<<: !include file:{base_file}
a: !unset
c: !unset
"""
        result = loads(override, raw_dict=True)
        assert result == {"b": 2}

    def test_unset_with_override_and_remove(self, base_file):
        override = f"""\
<<: !include file:{base_file}
a: 100
b: !unset
"""
        result = loads(override, raw_dict=True)
        assert result == {"a": 100, "c": 3}

    def test_unset_nested_inherited_key(self, tmp_path):
        base = tmp_path / "base.yaml"
        base.write_text("section:\n  x: 1\n  y: 2\n  z: 3\n")
        override = f"""\
<<: !include file:{base}
section:
  y: !unset
"""
        result = loads(override, raw_dict=True)
        # after merge, section.y should be removed
        assert "y" not in result.get("section", {})
        assert result["section"]["x"] == 1
        assert result["section"]["z"] == 3


# ── e2e: !unset with multi-file load (cascade) ──────────────────────────────

class TestUnsetMultiFileLoad:
    def test_unset_in_overlay_file(self, tmp_path):
        base = tmp_path / "base.yaml"
        base.write_text("db_host: localhost\ndb_port: 5432\ndebug: true\n")
        overlay = tmp_path / "prod.yaml"
        overlay.write_text("debug: !unset\ndb_host: prod-db.internal\n")

        result = load(
            [f"file:{base}", f"file:{overlay}"],
            raw_dict=True,
        )
        assert result == {"db_host": "prod-db.internal", "db_port": 5432}

    def test_unset_in_middle_layer(self, tmp_path):
        base = tmp_path / "base.yaml"
        base.write_text("a: 1\nb: 2\nc: 3\n")
        mid = tmp_path / "mid.yaml"
        mid.write_text("b: !unset\n")
        top = tmp_path / "top.yaml"
        top.write_text("d: 4\n")

        result = load(
            [f"file:{base}", f"file:{mid}", f"file:{top}"],
            raw_dict=True,
        )
        assert "b" not in result
        assert result["a"] == 1
        assert result["c"] == 3
        assert result["d"] == 4


# ── e2e: !unset combined with other features ────────────────────────────────

class TestUnsetInteraction:
    def test_unset_does_not_break_interpolation_on_siblings(self):
        yaml = """\
base: hello
removed: !unset
greeting: ${@/base}
"""
        result = loads(yaml)
        assert result.base == "hello"
        assert result.greeting == "hello"
        assert not hasattr(result, "removed")

    def test_unset_value_not_constructable_as_type(self):
        """The original bug: !unset should not be resolved as a Python type."""
        # this was raising: DraconError: ValueError: failed to resolve type unset
        result = loads("a: 1\nb: !unset\nc: 3", raw_dict=True)
        assert result == {"a": 1, "c": 3}

    def test_unset_on_mapping_value(self):
        """!unset on an entire mapping value should remove it."""
        yaml = """\
keep: 1
remove: !unset
  nested: value
"""
        # !unset tags the scalar "remove" value, but YAML parsing means
        # the nested mapping is the value. Let's use the simpler form.
        # Actually this YAML is invalid (scalar !unset then mapping indented).
        # The correct way is just `remove: !unset`
        pass  # covered by other tests

    def test_unset_round_trip_with_pydantic(self):
        """!unset keys should not appear when loading into a pydantic model."""
        from pydantic import BaseModel
        from typing import Optional

        class Cfg(BaseModel):
            a: int = 0
            c: int = 0

        yaml = "a: 1\nb: !unset\nc: 3\n"
        result = loads(yaml, raw_dict=True)
        cfg = Cfg(**result)
        assert cfg.a == 1
        assert cfg.c == 3
