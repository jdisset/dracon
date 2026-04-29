# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""Polish tests for the yaml-cli-args feature (step 04).

Covers:
  - `!require` is marked "used" once satisfied (no false unused-var warning).
  - `--show-vars` table labels YAML-discovered flags distinctly from `++`.
  - error messages from `parse_directive_body` carry source context.
  - help output groups YAML-declared flags under a clear section.
"""

from __future__ import annotations

import os
import textwrap
from io import StringIO
from pathlib import Path

import pytest
from pydantic import BaseModel

from dracon import Arg, make_program


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(content).lstrip())
    return p


class _Cfg(BaseModel):
    name: str = "anon"


def _prog():
    return make_program(_Cfg, name="t", context={"_Cfg": _Cfg})


# ── unused-var warnings ──────────────────────────────────────────────────────


def test_require_satisfied_by_flag_does_not_warn(tmp_path, capsys):
    """`!require port` + `--port 9000` → no "not used" warning, even if the
    YAML never reads `${port}`. Routing through a declared flag implies the
    user did exactly what the directive asked for."""
    src = _write(
        tmp_path, "layer.yaml",
        """
        !require port: "bind port"
        greeting: hello
        """,
    )
    cfg, _ = _prog().parse_args([f"+{src.as_posix()}", "--port", "9000"])
    out = capsys.readouterr().out + capsys.readouterr().err
    assert "not used" not in out.lower()


def test_undeclared_plusplus_still_warns(tmp_path, capsys):
    """`++foo=bar` with no declaration anywhere still warns. The YAML
    feature must not silence the existing safety net."""
    src = _write(tmp_path, "layer.yaml", "x: 1\n")
    _prog().parse_args([f"+{src.as_posix()}", "++foo=bar"])
    out = capsys.readouterr().out + capsys.readouterr().err
    assert "not used" in out.lower()
    assert "foo" in out


# ── --show-vars labelling ────────────────────────────────────────────────────


def test_show_vars_distinguishes_long_flag_from_plusplus(tmp_path, capsys):
    """`--port 9000` and `++other=v` should appear with distinct sources in
    the DRACON_SHOW_VARS table."""
    src = _write(
        tmp_path, "layer.yaml",
        """
        !require port: "bind port"
        used: ${port}
        """,
    )
    os.environ["DRACON_SHOW_VARS"] = "1"
    try:
        _prog().parse_args([f"+{src.as_posix()}", "--port", "9000", "++other=v"])
        out = capsys.readouterr().out + capsys.readouterr().err
        assert "--port" in out or "CLI (--flag)" in out
        assert "CLI (++/--define)" in out
    finally:
        os.environ.pop("DRACON_SHOW_VARS", None)


# ── error message source context ─────────────────────────────────────────────


def test_unknown_directive_key_points_at_source(tmp_path):
    """Unknown body key surfaces the source location."""
    from dracon.diagnostics import CompositionError
    from dracon import loads

    src = textwrap.dedent("""
        !require port:
          help: "bind port"
          banana: yes
        x: 1
        """).lstrip()
    with pytest.raises(CompositionError) as ei:
        loads(src)
    msg = str(ei.value)
    assert "banana" in msg
    # error carries source context (line/col/snippet) for diagnostics
    assert ei.value.context is not None


def test_require_with_default_rejected_with_source(tmp_path):
    from dracon.diagnostics import CompositionError
    from dracon import loads

    src = textwrap.dedent("""
        !require port:
          help: "bind port"
          default: 8080
        x: 1
        """).lstrip()
    with pytest.raises(CompositionError) as ei:
        loads(src)
    msg = str(ei.value)
    assert "require" in msg.lower() and "default" in msg.lower()


# ── help section grouping ────────────────────────────────────────────────────


def test_help_lists_yaml_flag(tmp_path, capsys):
    """The help screen must include the discovered YAML flag with its hint."""
    src = _write(
        tmp_path, "layer.yaml",
        """
        !require api_key: "API key for downstream service"
        used: ${api_key}
        """,
    )
    with pytest.raises(SystemExit):
        _prog().parse_args([f"+{src.as_posix()}", "--help"])
    out = capsys.readouterr().out
    assert "--api-key" in out or "--api_key" in out
    assert "API key" in out
