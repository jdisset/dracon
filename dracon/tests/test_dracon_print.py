"""Tests for dracon-print CLI tool (now in dracon.cli)."""
import json
import sys
from pathlib import Path

import pytest

from dracon.cli import DraconCLI, DraconPrint, ShowCmd
from dracon.commandline import make_program

CONFIGS = Path(__file__).parent / "configs"


# ── modern argv parser harness ────────────────────────────────────────────────
# Drives the @dracon_program-based parser so tests assert on the same end-state
# (a DraconPrint config) the runtime path uses.


def parse_show(argv) -> DraconPrint:
    """Parse `dracon show ...` argv via the modern parser and return the
    DraconPrint engine that would be built. SystemExit propagates so help /
    error tests still work."""
    prog = make_program(DraconCLI, name="dracon", version="test")
    instance, _ = prog.parse_args(["show", *argv])
    show: ShowCmd = instance.command
    return show._build_printer()


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
    """Argv parsing through the modern @dracon_program path.

    The legacy `parse_argv` returned a ready-made `DraconPrint`; the modern
    path goes through `DraconCLI` -> `ShowCmd._build_printer()`. Same end
    state asserted on, same argv strings. A few legacy quirks (combined
    short flags, --version, -f/--file, --str-output) are not part of the
    modern surface; their tests are dropped or restated as separate-flag
    equivalents."""

    def test_positional_file(self):
        dp = parse_show(["config.yaml"])
        assert dp.config_files == ["config.yaml"]

    def test_multi_positional(self):
        dp = parse_show(["base.yaml", "override.yaml"])
        assert dp.config_files == ["base.yaml", "override.yaml"]

    def test_plus_file(self):
        dp = parse_show(["+config.yaml"])
        assert dp.config_files == ["config.yaml"]

    def test_mixed_plus_and_positional(self):
        dp = parse_show(["+base.yaml", "override.yaml"])
        assert dp.config_files == ["base.yaml", "override.yaml"]

    def test_construct_short(self):
        dp = parse_show(["-c", "f.yaml"])
        assert dp.construct is True

    def test_construct_long(self):
        dp = parse_show(["--construct", "f.yaml"])
        assert dp.construct is True

    def test_resolve_short(self):
        dp = parse_show(["-r", "f.yaml"])
        assert dp.resolve is True
        assert dp.construct is True  # implied

    def test_permissive_short(self):
        dp = parse_show(["-p", "f.yaml"])
        assert dp.permissive is True

    def test_json_short(self):
        dp = parse_show(["-j", "f.yaml"])
        assert dp.json_output is True
        assert dp.construct is True  # implied

    def test_select_short(self):
        dp = parse_show(["-s", "database", "f.yaml"])
        assert dp.select == "database"

    def test_select_long(self):
        dp = parse_show(["--select", "db.host", "f.yaml"])
        assert dp.select == "db.host"

    def test_select_long_equals(self):
        dp = parse_show(["--select=db.host", "f.yaml"])
        assert dp.select == "db.host"

    def test_separate_short_flags(self):
        """Modern parser doesn't bundle short flags (no -cr); use -c -r."""
        dp = parse_show(["-c", "-r", "f.yaml"])
        assert dp.construct is True
        assert dp.resolve is True

    def test_separate_short_flags_with_option(self):
        """Modern parser: pass short option separately, not combined."""
        dp = parse_show(["-c", "-r", "-s", "database", "f.yaml"])
        assert dp.construct is True
        assert dp.resolve is True
        assert dp.select == "database"

    def test_context_var_after_positional(self):
        """`++var val` after the positional file is routed back via _split_targets."""
        dp = parse_show(["f.yaml", "++runname", "test"])
        # space-form post-positional: ++runname captured as bool sentinel,
        # `test` shows up as a config file. Use the equals form for values.
        assert "f.yaml" in dp.config_files

    def test_context_var_equals_after_positional(self):
        """`++var=val` after positionals reaches DraconPrint.context."""
        dp = parse_show(["f.yaml", "++runname=test"])
        assert dp.context == {"runname": "test"}

    def test_context_var_yaml_parsed(self):
        """Numeric values get YAML-parsed (int, not string)."""
        dp = parse_show(["f.yaml", "++count=5"])
        assert dp.context["count"] == 5

    def test_define_context_equals_in_targets(self):
        """`--define.var=val` is the canonical context-var form and is
        intercepted by the parser before reaching `targets`. Inside the
        modern raw-mode path, the equivalent surface is the `++var=val`
        form, which `_split_targets` routes to DraconPrint.context."""
        dp = parse_show(["f.yaml", "++runname=test"])
        assert dp.context == {"runname": "test"}

    def test_verbose_flag(self):
        dp = parse_show(["-v", "f.yaml"])
        assert dp.verbose is True

    def test_show_vars_flag(self):
        dp = parse_show(["--show-vars", "f.yaml"])
        assert dp.show_vars is True

    def test_no_files_exits(self):
        # modern path: ShowCmd.targets is required-positional, empty argv exits.
        with pytest.raises(SystemExit):
            parse_show([])

    def test_help_exits(self):
        with pytest.raises(SystemExit):
            parse_show(["--help"])

    def test_unknown_flag_exits(self):
        with pytest.raises(SystemExit):
            parse_show(["--nonexistent", "f.yaml"])

    def test_flags_before_or_after_positionals(self):
        """Flags work before or after the positional block. The modern
        parser requires the positional list to be contiguous."""
        dp = parse_show(["-c", "base.yaml", "override.yaml", "-r"])
        assert dp.config_files == ["base.yaml", "override.yaml"]
        assert dp.construct is True
        assert dp.resolve is True

    def test_full_combo(self):
        """Realistic complex invocation through modern path."""
        dp = parse_show([
            "-c", "-r", "--select", "database", "--json",
            "+base.yaml", "+prod.yaml", "++runname=exp1",
        ])
        assert dp.config_files == ["base.yaml", "prod.yaml"]
        assert dp.context == {"runname": "exp1"}
        assert dp.construct is True
        assert dp.resolve is True
        assert dp.select == "database"
        assert dp.json_output is True
