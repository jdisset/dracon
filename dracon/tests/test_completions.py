"""Tests for dracon completions subcommand and --_complete protocol."""
import os
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import BaseModel
from typing import Annotated

from dracon import Arg, Subcommand, dracon_program, subcommand

CONFIGS = Path(__file__).parent / "configs"


def _run_complete(prog_cls, comp_line, comp_point=None):
    """Run --_complete on a dracon_program class, return candidate lines."""
    if comp_point is None:
        comp_point = len(comp_line)
    env = {"COMP_LINE": comp_line, "COMP_POINT": str(comp_point)}
    buf = StringIO()
    with patch.dict(os.environ, env):
        with patch('sys.stdout', buf):
            with pytest.raises(SystemExit):
                prog_cls.cli(argv=["--_complete"])
    return buf.getvalue().strip().splitlines()


# ── shell script emission tests ──────────────────────────────────────────────


class TestCompletionsScripts:
    """dracon completions bash/zsh/fish emit valid shell scripts."""

    def _run_completions(self, argv):
        from dracon.cli import DraconCLI
        with patch('sys.exit'):
            return DraconCLI.cli(argv=["completions"] + argv)

    def test_bash_script(self, capsys):
        self._run_completions(["bash"])
        out = capsys.readouterr().out
        assert "_dracon_complete" in out
        assert "complete " in out
        assert "COMP_LINE" in out

    def test_zsh_script(self, capsys):
        self._run_completions(["zsh"])
        out = capsys.readouterr().out
        assert "_dracon_complete" in out
        assert "compdef" in out or "compadd" in out

    def test_fish_script(self, capsys):
        self._run_completions(["fish"])
        out = capsys.readouterr().out
        assert "complete " in out
        assert "COMP_LINE" in out


# ── install tests ────────────────────────────────────────────────────────────


class TestCompletionsInstall:
    """dracon completions install writes eval line to shell rc file."""

    def test_install_bash(self, tmp_path):
        rc = tmp_path / ".bashrc"
        rc.write_text("# existing content\n")
        with patch.dict(os.environ, {"SHELL": "/bin/bash", "HOME": str(tmp_path)}):
            from dracon.cli import DraconCLI
            with patch('sys.exit'):
                DraconCLI.cli(argv=["completions", "install"])
        content = rc.read_text()
        assert 'completions.bash' in content
        # cache file should be written
        assert (tmp_path / ".dracon" / "completions.bash").exists()

    def test_install_zsh(self, tmp_path):
        rc = tmp_path / ".zshrc"
        rc.write_text("# existing\n")
        with patch.dict(os.environ, {"SHELL": "/bin/zsh", "HOME": str(tmp_path)}):
            from dracon.cli import DraconCLI
            with patch('sys.exit'):
                DraconCLI.cli(argv=["completions", "install"])
        content = rc.read_text()
        assert 'completions.zsh' in content
        assert (tmp_path / ".dracon" / "completions.zsh").exists()

    def test_install_idempotent(self, tmp_path):
        rc = tmp_path / ".bashrc"
        rc.write_text('source ~/.dracon/completions.bash\n')
        with patch.dict(os.environ, {"SHELL": "/bin/bash", "HOME": str(tmp_path)}):
            from dracon.cli import DraconCLI
            with patch('sys.exit'):
                DraconCLI.cli(argv=["completions", "install"])
        content = rc.read_text()
        assert content.count('completions.bash') == 1


# ── --_complete protocol tests ───────────────────────────────────────────────


@subcommand("sub1")
class Sub1(BaseModel):
    """First subcommand."""
    name: Annotated[str, Arg(positional=True, help="a name")] = "default"


@subcommand("sub2")
class Sub2(BaseModel):
    """Second subcommand."""
    count: Annotated[int, Arg(help="how many")] = 1


@dracon_program(name="testprog")
class ProgModel(BaseModel):
    command: Subcommand(Sub1, Sub2)
    verbose: Annotated[bool, Arg(short="v", help="verbose")] = False


class TestCompleteProtocol:
    """--_complete flag triggers completion output."""

    def test_complete_subcommands(self):
        candidates = _run_complete(ProgModel, "testprog ")
        assert "sub1" in candidates
        assert "sub2" in candidates

    def test_complete_subcommand_prefix(self):
        candidates = _run_complete(ProgModel, "testprog s")
        assert "sub1" in candidates
        assert "sub2" in candidates

    def test_complete_flags(self):
        candidates = _run_complete(ProgModel, "testprog --")
        assert "--verbose" in candidates

    def test_complete_subcmd_flags(self):
        candidates = _run_complete(ProgModel, "testprog sub2 --")
        assert "--count" in candidates

    def test_complete_file_prefix(self):
        """+ prefix should trigger yaml file completion."""
        candidates = _run_complete(ProgModel, f"testprog +{CONFIGS}/simpl")
        yaml_matches = [c for c in candidates if c.endswith(".yaml")]
        assert any("simple.yaml" in c for c in yaml_matches)


# ── dynamic completions via __dracon_complete__ ──────────────────────────────


@dracon_program(name="dynprog")
class DynProg(BaseModel):
    target: Annotated[str, Arg(positional=True, help="target")] = ""

    @staticmethod
    def __dracon_complete__(prefix: str, tokens: list[str]) -> list[str]:
        return [x for x in ["alpha", "beta", "gamma"] if x.startswith(prefix)]


class TestDynamicCompletions:

    def test_dynamic_completions(self):
        candidates = _run_complete(DynProg, "dynprog a")
        assert "alpha" in candidates

    def test_dynamic_completions_all(self):
        candidates = _run_complete(DynProg, "dynprog ")
        assert "alpha" in candidates
        assert "beta" in candidates
        assert "gamma" in candidates
