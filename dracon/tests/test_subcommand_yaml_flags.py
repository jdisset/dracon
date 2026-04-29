# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""YAML-declared CLI flags must reach argparse on subcommand programs.

Bug: see ``bugs/cli-yaml-flags-lost-with-subcommands.md``. Discovery
returns directives correctly but ``_parse_with_subcommands`` skips the
``_discover_yaml_args`` pre-pass, so the flags never get registered.
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Annotated

import pytest
from pydantic import BaseModel

from dracon import Arg, Subcommand, dracon_program, make_program, subcommand


@subcommand("run")
class RunCmd(BaseModel):
    quiet: bool = False


@dracon_program(name="sub")
class SubCLI(BaseModel):
    extra: str = ""
    # `result` is the observable witness; the layer writes ${greeting} x ${count}
    # into it. Names `greeting` / `count` are NOT model fields (they live in
    # context only), so the yaml-declared flags don't collide with model-side Args.
    result: str = ""
    command: Subcommand(RunCmd)  # type: ignore[valid-type]


@pytest.fixture
def extras_yaml(tmp_path: Path) -> Path:
    p = tmp_path / "extras.yaml"
    p.write_text(
        "!set_default greeting:\n"
        "  default: \"hello\"\n"
        "  help: \"what to print\"\n"
        "  short: -g\n"
        "!set_default count:\n"
        "  default: 1\n"
        "  help: \"how many times\"\n"
        "  short: -n\n"
        "result: \"${greeting} x ${count}\"\n"
    )
    return p


def _capture_help(prog, *argv) -> str:
    """Grab help output from dracon's rich console (capfd misses it)."""
    import re
    from dracon.commandline import console
    buf = StringIO()
    old_file = console.file
    console.file = buf
    try:
        with pytest.raises(SystemExit):
            prog.parse_args(list(argv))
    finally:
        console.file = old_file
    return re.sub(r'\x1b\[[0-9;]*m', '', buf.getvalue())


# ── flags accept --name value form on subcommand programs ────────────────


class TestSubcommandLongFlag:
    """Layer placed BEFORE the subcommand → root-scoped, value flows to model."""

    def test_long_flag_accepted_before_subcommand(self, extras_yaml):
        prog = make_program(SubCLI)
        cfg, _ = prog.parse_args(
            [f"+file:{extras_yaml}", "--greeting", "hi", "--count", "3", "run"]
        )
        assert cfg.result == "hi x 3"

    def test_long_flag_default_when_not_set(self, extras_yaml):
        prog = make_program(SubCLI)
        cfg, _ = prog.parse_args(
            [f"+file:{extras_yaml}", "--greeting", "hi", "run"]
        )
        assert cfg.result == "hi x 1"  # count defaults from !set_default

    def test_long_flag_with_equals(self, extras_yaml):
        prog = make_program(SubCLI)
        cfg, _ = prog.parse_args(
            [f"+file:{extras_yaml}", "--greeting=hello", "run"]
        )
        assert cfg.result == "hello x 1"

    def test_long_flag_after_subcommand_does_not_error(self, extras_yaml):
        """Layer AFTER the subcommand → subcmd-scoped config, but its
        yaml-declared flags must still be accepted at the root level
        (the bug was 'unknown argument --greeting' here)."""
        prog = make_program(SubCLI)
        # parses without raising
        cfg, _ = prog.parse_args(
            ["run", f"+file:{extras_yaml}", "--greeting", "hi"]
        )
        # cfg exists; the registration bug would have raised before reaching here


class TestSubcommandShortFlag:
    def test_short_flag_accepted(self, extras_yaml):
        prog = make_program(SubCLI)
        cfg, _ = prog.parse_args(
            [f"+file:{extras_yaml}", "-g", "hi", "-n", "3", "run"]
        )
        assert cfg.result == "hi x 3"

    def test_short_flag_after_subcommand_does_not_error(self, extras_yaml):
        prog = make_program(SubCLI)
        # the registration bug would raise 'unknown argument -g'
        prog.parse_args(["run", f"+file:{extras_yaml}", "-g", "hi"])


class TestSubcommandHelpListsYamlFlags:
    def test_help_shows_yaml_declared_flag(self, extras_yaml):
        """`run --help` for a subcommand program must list yaml-declared flags."""
        prog = make_program(SubCLI)
        out = _capture_help(prog, "run", f"+file:{extras_yaml}", "--help")
        assert "--greeting" in out, f"--greeting missing from help:\n{out}"
        assert "--count" in out, f"--count missing from help:\n{out}"
        assert "what to print" in out
        assert "how many times" in out


# ── ++name=value still works (regression guard) ───────────────────────────


class TestSubcommandContextEscapeStillWorks:
    """The pre-existing `++name=value` escape must keep working — that's how
    users worked around the bug. After the fix it should still be a valid
    alternative path."""

    def test_double_plus_still_works(self, extras_yaml):
        prog = make_program(SubCLI)
        # using ++ form before the subcommand routes the layer to root scope
        cfg, _ = prog.parse_args(
            [f"+file:{extras_yaml}", "++greeting=hi", "++count=2", "run"]
        )
        assert cfg.result == "hi x 2"

    def test_double_plus_after_subcommand_does_not_error(self, extras_yaml):
        """++name=value is the pre-fix workaround; must keep working when the
        layer is placed after the subcommand."""
        prog = make_program(SubCLI)
        prog.parse_args(["run", f"+file:{extras_yaml}", "++greeting=hi"])


# ── flat program (regression guard, not the bug) ──────────────────────────


@dracon_program(name="flat")
class FlatCLI(BaseModel):
    extra: str = ""
    result: str = ""


class TestFlatProgramStillWorks:
    """Flat programs must keep working — this is the unbroken baseline."""

    def test_flat_long_flag(self, extras_yaml):
        prog = make_program(FlatCLI)
        cfg, _ = prog.parse_args(
            [f"+file:{extras_yaml}", "--greeting", "yo", "--count", "5"]
        )
        assert cfg.result == "yo x 5"

    def test_flat_help_shows_yaml_flags(self, extras_yaml):
        prog = make_program(FlatCLI)
        out = _capture_help(prog, f"+file:{extras_yaml}", "--help")
        assert "--greeting" in out
        assert "--count" in out
