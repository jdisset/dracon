# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""Help renderer groups YAML-declared flags by source file.

When more than _GROUPED_HELP_THRESHOLD yaml-declared flags are discovered,
they get their own subsection per source file ("Options from <basename>:")
below the model-side "Options:" panel. Below the threshold the help stays
flat so small layered surfaces don't get visually noisy.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import pytest
from pydantic import BaseModel

from dracon import Arg, dracon_program, make_program


def _strip_ansi(text: str) -> str:
    import re
    return re.sub(r'\x1b\[[0-9;]*m', '', text)


@pytest.fixture
def model_cli():
    @dracon_program(name="myapp")
    class CLI(BaseModel):
        env: Annotated[str, Arg(short="e", help="environment name")] = "dev"
        workers: Annotated[int, Arg(help="worker count")] = 4
    return CLI


def _write(tmp: Path, name: str, body: str) -> Path:
    p = tmp / name
    p.write_text(body)
    return p


def _run_help(prog, _capfd_unused, *argv):
    """Capture help output via the rich console module singleton — capfd
    misses it because dracon prints through `commandline.console`, not
    through the live sys.stdout."""
    from io import StringIO
    from dracon.commandline import console
    buf = StringIO()
    old_file = console.file
    console.file = buf
    try:
        with pytest.raises(SystemExit):
            prog.parse_args(list(argv) + ["--help"])
    finally:
        console.file = old_file
    return _strip_ansi(buf.getvalue())


# ── grouped layout (above threshold) ────────────────────────────────────────


def test_yaml_flags_split_per_file_when_above_threshold(model_cli, capfd, tmp_path):
    """Three or more yaml-declared flags from two files → two subsections."""
    analytics = _write(tmp_path, "analytics.yaml", (
        "!require api_key:\n"
        "  help: \"API key\"\n"
        "!set_default:int batch_size:\n"
        "  default: 32\n"
        "  help: \"upload batch size\"\n"
    ))
    db = _write(tmp_path, "db.yaml", (
        "!set_default db_host:\n"
        "  default: localhost\n"
        "  help: \"db host\"\n"
        "!set_default:int db_port:\n"
        "  default: 5432\n"
        "  help: \"db port\"\n"
    ))

    prog = make_program(model_cli)
    out = _run_help(prog, capfd, f"+{analytics}", f"+{db}")

    # model-side options panel comes first
    assert "Options:" in out
    # each layered file gets its own subsection
    assert "Options from analytics.yaml:" in out
    assert "Options from db.yaml:" in out

    # model flags appear under the unqualified panel
    options_pos = out.index("Options:")
    analytics_pos = out.index("Options from analytics.yaml:")
    db_pos = out.index("Options from db.yaml:")
    assert options_pos < analytics_pos < db_pos

    # yaml-declared flags appear in the right groups
    analytics_block = out[analytics_pos:db_pos]
    db_block = out[db_pos:]
    assert "--api-key" in analytics_block
    assert "--batch-size" in analytics_block
    assert "--db-host" in db_block
    assert "--db-port" in db_block
    # cross-checks: flags should NOT leak into the wrong group
    assert "--db-host" not in analytics_block
    assert "--api-key" not in db_block
    # model-side flags stay above the yaml subsections
    model_block = out[options_pos:analytics_pos]
    assert "--env" in model_block or "-e" in model_block
    assert "--workers" in model_block


def test_help_text_renders_in_grouped_layout(model_cli, capfd, tmp_path):
    """The body keys (help, default) survive into the grouped subsection."""
    f = _write(tmp_path, "extras.yaml", (
        "!require api_key:\n"
        "  help: \"the secret key\"\n"
        "!set_default:int batch:\n"
        "  default: 42\n"
        "  help: \"batch count\"\n"
        "!set_default name:\n"
        "  default: friend\n"
        "  help: \"who to greet\"\n"
    ))
    prog = make_program(model_cli)
    out = _run_help(prog, capfd, f"+{f}")

    assert "Options from extras.yaml:" in out
    assert "the secret key" in out
    assert "batch count" in out
    assert "who to greet" in out


# ── flat layout (below threshold) ───────────────────────────────────────────


def test_single_yaml_flag_stays_flat(model_cli, capfd, tmp_path):
    """One yaml flag → no per-file panel; all flags share one Options panel."""
    f = _write(tmp_path, "tiny.yaml", (
        "!require api_key:\n"
        "  help: \"API key\"\n"
    ))
    prog = make_program(model_cli)
    out = _run_help(prog, capfd, f"+{f}")

    assert "Options:" in out
    assert "Options from " not in out  # no per-file split
    # all flags reachable in the same panel
    assert "--api-key" in out
    assert "--env" in out or "-e" in out
    assert "--workers" in out


def test_two_yaml_flags_stays_flat(model_cli, capfd, tmp_path):
    """At threshold → still flat (cleaner for small layered surfaces)."""
    f = _write(tmp_path, "two.yaml", (
        "!require api_key:\n"
        "  help: \"API key\"\n"
        "!set_default:int batch:\n"
        "  default: 1\n"
        "  help: \"batch\"\n"
    ))
    prog = make_program(model_cli)
    out = _run_help(prog, capfd, f"+{f}")

    assert "Options:" in out
    assert "Options from " not in out
    assert "--api-key" in out
    assert "--batch" in out


# ── pure model CLI (no layered configs) ─────────────────────────────────────


def test_pure_model_cli_unchanged(model_cli, capfd):
    """No layered configs → behavior is identical to before the refactor:
    one Options panel, no subsections."""
    prog = make_program(model_cli)
    out = _run_help(prog, capfd)
    assert "Options:" in out
    assert "Options from " not in out
    assert "--env" in out or "-e" in out
    assert "--workers" in out
