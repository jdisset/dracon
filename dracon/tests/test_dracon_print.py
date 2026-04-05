"""Tests for dracon-print CLI tool (now in dracon.cli)."""
import json
import sys
from pathlib import Path

import pytest

from dracon.cli import DraconPrint, parse_argv

CONFIGS = Path(__file__).parent / "configs"


# ── core logic tests ─────────────────────────────────────────────────────────


class TestCompose:
    """Default compose mode (no -c)."""

    def test_single_file(self):
        dp = DraconPrint(config_files=[str(CONFIGS / "simple.yaml")])
        out = dp.run()
        assert "root:" in out
        assert "a: 3" in out

    def test_multi_file_layering(self):
        dp = DraconPrint(
            config_files=[str(CONFIGS / "simple.yaml"), str(CONFIGS / "override.yaml")],
        )
        out = dp.run()
        # override.yaml merges into simple.yaml; both should contribute
        assert "default_settings:" in out

    def test_edge_cases_file(self):
        dp = DraconPrint(config_files=[str(CONFIGS / "edge_cases.yaml")])
        out = dp.run()
        assert "dotted.keys:" in out
        assert "each_with_dots:" in out


class TestConstruct:
    """Construct mode (-c)."""

    def test_simple_construct(self):
        dp = DraconPrint(config_files=[str(CONFIGS / "simple.yaml")], construct=True)
        out = dp.run()
        assert "root:" in out or '"root"' in out

    def test_construct_multi_file(self):
        dp = DraconPrint(
            config_files=[str(CONFIGS / "simple.yaml"), str(CONFIGS / "override.yaml")],
            construct=True,
        )
        out = dp.run()
        assert out  # should produce non-empty output


class TestResolve:
    """Resolve mode (-r)."""

    def test_resolve_implies_construct(self):
        """resolve flag should auto-enable construct so it works on real objects."""
        dp = DraconPrint(config_files=[str(CONFIGS / "simple.yaml")], resolve=True)
        # resolve=True should set construct=True
        assert dp.construct is True
        out = dp.run()
        assert out

    def test_permissive_resolve(self):
        """Permissive mode leaves unresolvable ${...} as strings."""
        dp = DraconPrint(
            config_files=[str(CONFIGS / "interpolation.yaml")],
            resolve=True,
            permissive=True,
        )
        out = dp.run()
        assert out


class TestSelect:
    """Subtree selection (--select)."""

    def test_select_key(self):
        dp = DraconPrint(
            config_files=[str(CONFIGS / "simple.yaml")],
            construct=True,
            select="root",
        )
        out = dp.run()
        # should contain root's children, not the top-level 'root:' key
        assert "a:" in out or '"a"' in out
        # should NOT contain sibling keys
        assert "param2" not in out

    def test_select_nested(self):
        dp = DraconPrint(
            config_files=[str(CONFIGS / "simple.yaml")],
            construct=True,
            select="root.inner",
        )
        out = dp.run()
        assert "c:" in out or '"c"' in out

    def test_select_bad_path(self):
        dp = DraconPrint(
            config_files=[str(CONFIGS / "simple.yaml")],
            construct=True,
            select="nonexistent.path",
        )
        with pytest.raises(SystemExit):
            dp.run()


class TestJsonOutput:
    """JSON output (-j)."""

    def test_json_valid(self):
        dp = DraconPrint(
            config_files=[str(CONFIGS / "simple.yaml")],
            json_output=True,
        )
        out = dp.run()
        data = json.loads(out)
        assert isinstance(data, dict)
        assert "root" in data

    def test_json_implies_construct(self):
        dp = DraconPrint(config_files=[str(CONFIGS / "simple.yaml")], json_output=True)
        assert dp.construct is True

    def test_json_nested_values(self):
        dp = DraconPrint(
            config_files=[str(CONFIGS / "simple.yaml")],
            json_output=True,
        )
        out = dp.run()
        data = json.loads(out)
        assert data["root"]["a"] == 3
        assert data["root"]["inner"]["c"] == 5


class TestContextVars:
    """Context variable injection."""

    def test_context_available_in_interpolation(self):
        """Context variables should be available to ${...} expressions."""
        dp = DraconPrint(
            config_files=[str(CONFIGS / "simple.yaml")],
            construct=True,
            context={"some_var": 42},
        )
        out = dp.run()
        assert out  # should not error


class TestShowVars:
    """--show-vars flag."""

    def test_show_vars_does_not_corrupt_stdout(self, capsys):
        """Vars table goes to stderr, config to stdout."""
        dp = DraconPrint(
            config_files=[str(CONFIGS / "edge_cases.yaml")],
            show_vars=True,
        )
        out = dp.run()
        # main output should still be valid YAML
        assert "dotted.keys:" in out


class TestStrOutput:
    """--str-output flag."""

    def test_str_output(self):
        dp = DraconPrint(
            config_files=[str(CONFIGS / "simple.yaml")],
            str_output=True,
        )
        out = dp.run()
        assert out  # should be a non-empty string representation


class TestErrors:
    """Error handling."""

    def test_missing_file(self):
        dp = DraconPrint(config_files=["nonexistent_file_12345.yaml"])
        with pytest.raises(SystemExit):
            dp.run()


# ── argv parsing tests ───────────────────────────────────────────────────────


class TestParseArgv:
    """Test CLI argument parsing."""

    def test_positional_file(self):
        dp = parse_argv(["config.yaml"])
        assert dp.config_files == ["config.yaml"]

    def test_multi_positional(self):
        dp = parse_argv(["base.yaml", "override.yaml"])
        assert dp.config_files == ["base.yaml", "override.yaml"]

    def test_plus_file(self):
        dp = parse_argv(["+config.yaml"])
        assert dp.config_files == ["config.yaml"]

    def test_mixed_plus_and_positional(self):
        dp = parse_argv(["+base.yaml", "override.yaml"])
        assert dp.config_files == ["base.yaml", "override.yaml"]

    def test_construct_short(self):
        dp = parse_argv(["-c", "f.yaml"])
        assert dp.construct is True

    def test_construct_long(self):
        dp = parse_argv(["--construct", "f.yaml"])
        assert dp.construct is True

    def test_resolve_short(self):
        dp = parse_argv(["-r", "f.yaml"])
        assert dp.resolve is True
        assert dp.construct is True  # implied

    def test_permissive_short(self):
        dp = parse_argv(["-p", "f.yaml"])
        assert dp.permissive is True

    def test_json_short(self):
        dp = parse_argv(["-j", "f.yaml"])
        assert dp.json_output is True
        assert dp.construct is True  # implied

    def test_select_short(self):
        dp = parse_argv(["-s", "database", "f.yaml"])
        assert dp.select == "database"

    def test_select_long(self):
        dp = parse_argv(["--select", "db.host", "f.yaml"])
        assert dp.select == "db.host"

    def test_select_long_equals(self):
        dp = parse_argv(["--select=db.host", "f.yaml"])
        assert dp.select == "db.host"

    def test_combined_short_flags(self):
        dp = parse_argv(["-cr", "f.yaml"])
        assert dp.construct is True
        assert dp.resolve is True

    def test_combined_short_flags_with_option(self):
        """e.g. -crs database => construct, resolve, select=database"""
        dp = parse_argv(["-crs", "database", "f.yaml"])
        assert dp.construct is True
        assert dp.resolve is True
        assert dp.select == "database"

    def test_context_var_space(self):
        dp = parse_argv(["++runname", "test", "f.yaml"])
        assert dp.context == {"runname": "test"}

    def test_context_var_equals(self):
        dp = parse_argv(["++runname=test", "f.yaml"])
        assert dp.context == {"runname": "test"}

    def test_context_var_yaml_parsed(self):
        """Numeric values should be parsed as YAML (int, not string)."""
        dp = parse_argv(["++count=5", "f.yaml"])
        assert dp.context["count"] == 5

    def test_define_context(self):
        dp = parse_argv(["--define.runname", "test", "f.yaml"])
        assert dp.context == {"runname": "test"}

    def test_legacy_file_flag(self):
        dp = parse_argv(["-f", "config.yaml"])
        assert dp.config_files == ["config.yaml"]

    def test_legacy_file_long(self):
        dp = parse_argv(["--file", "config.yaml"])
        assert dp.config_files == ["config.yaml"]

    def test_verbose_flag(self):
        dp = parse_argv(["-v", "f.yaml"])
        assert dp.verbose is True

    def test_show_vars_flag(self):
        dp = parse_argv(["--show-vars", "f.yaml"])
        assert dp.show_vars is True

    def test_str_output_flag(self):
        dp = parse_argv(["--str-output", "f.yaml"])
        assert dp.str_output is True

    def test_no_files_exits(self):
        with pytest.raises(SystemExit):
            parse_argv([])

    def test_no_files_only_flags_exits(self):
        with pytest.raises(SystemExit):
            parse_argv(["-c", "-r"])

    def test_help_exits(self):
        with pytest.raises(SystemExit):
            parse_argv(["--help"])

    def test_version_exits(self):
        with pytest.raises(SystemExit):
            parse_argv(["--version"])

    def test_unknown_flag_exits(self):
        with pytest.raises(SystemExit):
            parse_argv(["--nonexistent", "f.yaml"])

    def test_flags_anywhere(self):
        """Flags can appear before or after config files."""
        dp = parse_argv(["base.yaml", "-c", "override.yaml", "-r"])
        assert dp.config_files == ["base.yaml", "override.yaml"]
        assert dp.construct is True
        assert dp.resolve is True

    def test_full_combo(self):
        """Realistic complex invocation."""
        dp = parse_argv([
            "+base.yaml", "+prod.yaml", "++runname=exp1",
            "-cr", "--select", "database", "--json",
        ])
        assert dp.config_files == ["base.yaml", "prod.yaml"]
        assert dp.context == {"runname": "exp1"}
        assert dp.construct is True
        assert dp.resolve is True
        assert dp.select == "database"
        assert dp.json_output is True
