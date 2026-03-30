import pytest
from pathlib import Path
from dracon.loader import DraconLoader
from dracon.include import compose_from_include_str


# ── find_cascade_files ──────────────────────────────────────────────────────

class TestFindCascadeFiles:
    def test_single_file_at_root(self, tmp_path):
        from dracon.loaders.cascade import find_cascade_files
        (tmp_path / "config.yaml").write_text("a: 1")
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        result = find_cascade_files("config.yaml", start_dir=deep)
        assert len(result) == 1
        assert result[0] == (tmp_path / "config.yaml").resolve()

    def test_multiple_levels_root_first_order(self, tmp_path):
        from dracon.loaders.cascade import find_cascade_files
        # 3 levels
        (tmp_path / "cfg.yaml").write_text("level: root")
        mid = tmp_path / "a"
        mid.mkdir()
        (mid / "cfg.yaml").write_text("level: mid")
        deep = mid / "b"
        deep.mkdir()
        (deep / "cfg.yaml").write_text("level: deep")
        start = deep / "child"
        start.mkdir()

        result = find_cascade_files("cfg.yaml", start_dir=start)
        assert len(result) == 3
        # root first, closest last
        assert result[0] == (tmp_path / "cfg.yaml").resolve()
        assert result[1] == (mid / "cfg.yaml").resolve()
        assert result[2] == (deep / "cfg.yaml").resolve()

    def test_extension_probing(self, tmp_path):
        """config (no ext) should match config.yaml via with_possible_ext"""
        from dracon.loaders.cascade import find_cascade_files
        (tmp_path / "config.yaml").write_text("a: 1")
        result = find_cascade_files("config", start_dir=tmp_path)
        assert len(result) == 1

    def test_none_found_returns_empty(self, tmp_path):
        from dracon.loaders.cascade import find_cascade_files
        result = find_cascade_files("nonexistent.yaml", start_dir=tmp_path)
        assert result == []

    def test_absolute_path_raises(self):
        from dracon.loaders.cascade import find_cascade_files
        with pytest.raises(ValueError, match="absolute"):
            find_cascade_files("/etc/config.yaml")

    def test_custom_start_dir(self, tmp_path):
        from dracon.loaders.cascade import find_cascade_files
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "x.yaml").write_text("a: 1")
        # start from sub, should find it
        result = find_cascade_files("x.yaml", start_dir=sub)
        assert len(result) >= 1
        assert result[-1] == (sub / "x.yaml").resolve()

    def test_only_one_match_per_level(self, tmp_path):
        """with_possible_ext may match multiple variants at the same level;
        only the first match should be recorded per directory."""
        from dracon.loaders.cascade import find_cascade_files
        (tmp_path / "cfg.yaml").write_text("a: 1")
        (tmp_path / "cfg.yml").write_text("b: 2")  # also matches
        result = find_cascade_files("cfg", start_dir=tmp_path)
        # should only return 1 file for this level (first match)
        assert len(result) == 1


# ── _parse_cascade_path ─────────────────────────────────────────────────────

class TestParseCascadePath:
    def test_plain_path(self):
        from dracon.loaders.cascade import _parse_cascade_path
        mk, path = _parse_cascade_path("config.yaml")
        assert path == "config.yaml"
        assert mk == "<<{<+}[<~]"

    def test_full_merge_key(self):
        from dracon.loaders.cascade import _parse_cascade_path
        mk, path = _parse_cascade_path("{>+}[<~]:config.yaml")
        assert path == "config.yaml"
        assert mk == "<<{>+}[<~]"

    def test_dict_only_merge_key(self):
        from dracon.loaders.cascade import _parse_cascade_path
        mk, path = _parse_cascade_path("{<+}:config.yaml")
        assert path == "config.yaml"
        assert mk == "<<{<+}"

    def test_list_only_merge_key(self):
        from dracon.loaders.cascade import _parse_cascade_path
        mk, path = _parse_cascade_path("[<+]:config.yaml")
        assert path == "config.yaml"
        assert mk == "<<[<+]"

    def test_path_with_subdirectory(self):
        from dracon.loaders.cascade import _parse_cascade_path
        mk, path = _parse_cascade_path("{<~}[<~]:sub/config.yaml")
        assert path == "sub/config.yaml"
        assert mk == "<<{<~}[<~]"


# ── read_cascade integration ────────────────────────────────────────────────

class TestReadCascade:
    def test_merges_root_first_closest_wins(self, tmp_path, monkeypatch):
        """Root defines base values; closer files override them."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "app.yaml").write_text("a: 1\nb: base")
        sub = tmp_path / "project"
        sub.mkdir()
        (sub / "app.yaml").write_text("a: 99")
        monkeypatch.chdir(sub)

        loader = DraconLoader(enable_interpolation=True)
        comp = compose_from_include_str(loader, "cascade:app.yaml")
        config = loader.load_composition_result(comp)
        assert config["a"] == 99   # closest wins
        assert config["b"] == "base"  # inherited from root

    def test_single_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "only.yaml").write_text("x: 42")

        loader = DraconLoader(enable_interpolation=True)
        comp = compose_from_include_str(loader, "cascade:only.yaml")
        config = loader.load_composition_result(comp)
        assert config["x"] == 42

    def test_no_files_raises(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        loader = DraconLoader(enable_interpolation=True)
        with pytest.raises(FileNotFoundError):
            compose_from_include_str(loader, "cascade:nope.yaml")

    def test_with_custom_merge_key(self, tmp_path, monkeypatch):
        """Using existing-wins merge key: root value should persist."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "cfg.yaml").write_text("a: root_val")
        sub = tmp_path / "child"
        sub.mkdir()
        (sub / "cfg.yaml").write_text("a: child_val")
        monkeypatch.chdir(sub)

        loader = DraconLoader(enable_interpolation=True)
        # {>+} = existing (root) wins for dicts
        comp = compose_from_include_str(loader, "cascade:{>+}[>~]:cfg.yaml")
        config = loader.load_composition_result(comp)
        assert config["a"] == "root_val"

    def test_context_from_closest_file(self, tmp_path, monkeypatch):
        """Returned context DIR should point to the closest file's directory."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "c.yaml").write_text("x: 1")
        sub = tmp_path / "deep"
        sub.mkdir()
        (sub / "c.yaml").write_text("x: 2")
        monkeypatch.chdir(sub)

        loader = DraconLoader(enable_interpolation=True)
        comp = compose_from_include_str(loader, "cascade:c.yaml")
        # DIR in loader context should be the closest file's parent
        assert loader.context.get("DIR") == sub.resolve().as_posix()

    def test_three_levels(self, tmp_path, monkeypatch):
        """Three levels of cascade: root -> mid -> leaf."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "s.yaml").write_text("a: 1\nb: 2\nc: 3")
        mid = tmp_path / "m"
        mid.mkdir()
        (mid / "s.yaml").write_text("b: 20")
        leaf = mid / "l"
        leaf.mkdir()
        (leaf / "s.yaml").write_text("c: 300")
        monkeypatch.chdir(leaf)

        loader = DraconLoader(enable_interpolation=True)
        comp = compose_from_include_str(loader, "cascade:s.yaml")
        config = loader.load_composition_result(comp)
        assert config["a"] == 1    # from root
        assert config["b"] == 20   # from mid
        assert config["c"] == 300  # from leaf


# ── !include "cascade:..." in YAML files ────────────────────────────────────

class TestIncludeCascadeInYaml:
    def test_include_cascade_in_file(self, tmp_path, monkeypatch):
        """A YAML file using !include cascade: should resolve the cascade."""
        monkeypatch.chdir(tmp_path)
        # cascade target files
        (tmp_path / "defaults.yaml").write_text("theme: dark\nfontsize: 12")
        sub = tmp_path / "project"
        sub.mkdir()
        (sub / "defaults.yaml").write_text("fontsize: 16")

        # main config that includes cascade
        main = sub / "main.yaml"
        main.write_text('settings: !include "cascade:defaults.yaml"')
        monkeypatch.chdir(sub)

        loader = DraconLoader(enable_interpolation=True)
        comp = loader.compose(str(main))
        config = loader.load_composition_result(comp)
        assert config["settings"]["theme"] == "dark"
        assert config["settings"]["fontsize"] == 16

    def test_include_cascade_optional_no_files(self, tmp_path, monkeypatch):
        """!include? cascade: should not raise when no files found."""
        monkeypatch.chdir(tmp_path)
        main = tmp_path / "main.yaml"
        main.write_text(
            'base: 1\noverrides: !include? "cascade:nonexistent.yaml"'
        )

        loader = DraconLoader(enable_interpolation=True)
        comp = loader.compose(str(main))
        config = loader.load_composition_result(comp)
        assert config["base"] == 1

    def test_include_cascade_with_keypath(self, tmp_path, monkeypatch):
        """cascade with @keypath should extract a subtree from merged result."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "app.yaml").write_text("db:\n  host: localhost\n  port: 5432")
        sub = tmp_path / "proj"
        sub.mkdir()
        (sub / "app.yaml").write_text("db:\n  port: 3306")

        main = sub / "main.yaml"
        main.write_text('database: !include "cascade:app.yaml@db"')
        monkeypatch.chdir(sub)

        loader = DraconLoader(enable_interpolation=True)
        comp = loader.compose(str(main))
        config = loader.load_composition_result(comp)
        assert config["database"]["host"] == "localhost"
        assert config["database"]["port"] == 3306

    def test_cascade_files_with_nested_includes(self, tmp_path, monkeypatch):
        """Cascaded files that themselves use !include should work."""
        monkeypatch.chdir(tmp_path)
        # a shared snippet
        (tmp_path / "snippet.yaml").write_text("shared: yes")
        # root cascade file includes the snippet
        (tmp_path / "cfg.yaml").write_text(
            'base: 1\nsnippet: !include "file:${DIR}/snippet.yaml"'
        )
        sub = tmp_path / "child"
        sub.mkdir()
        (sub / "cfg.yaml").write_text("base: 2")
        monkeypatch.chdir(sub)

        loader = DraconLoader(enable_interpolation=True)
        comp = compose_from_include_str(loader, "cascade:cfg.yaml")
        config = loader.load_composition_result(comp)
        assert config["base"] == 2
        assert config["snippet"]["shared"] == "yes"

    def test_cascade_with_list_append_merge_key(self, tmp_path, monkeypatch):
        """Cascade with list-append merge key should concatenate lists."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "plugins.yaml").write_text("plugins:\n  - core\n  - base")
        sub = tmp_path / "proj"
        sub.mkdir()
        (sub / "plugins.yaml").write_text("plugins:\n  - extra")
        monkeypatch.chdir(sub)

        loader = DraconLoader(enable_interpolation=True)
        # [+>] = existing wins, append lists (existing items first, then new)
        comp = compose_from_include_str(loader, "cascade:{<+}[+>]:plugins.yaml")
        config = loader.load_composition_result(comp)
        assert config["plugins"] == ["core", "base", "extra"]
