# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset
"""`@dracon_program` / `make_program` must expose mapping-valued context
vars to interpolation expressions with the same dot-access semantics as
the library `load()` path. The CLI loader previously hard-coded
`base_dict_type=dict`, which silently turned `${cfg.resolution}` into a
`'dict' object has no attribute 'resolution'` error in CLI YAML even
though the same YAML worked under `dracon.load`.
"""
import textwrap
from pathlib import Path

import pytest
from pydantic import BaseModel

import dracon
from dracon import make_program


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(content).lstrip())
    return p


class _CLI(BaseModel):
    bracket: int = 0
    dot: int = 0


def test_dot_access_on_mapping_context_var(tmp_path: Path):
    cfg = _write(tmp_path, "config.yaml", """
        !set_default cfg:
          resolution: 14
          scale: 40
        bracket: ${cfg['resolution']}
        dot:     ${cfg.resolution}
    """)
    prog = make_program(_CLI, name="prog")
    result, _ = prog.parse_args([f"+{cfg.as_posix()}"])
    assert result is not None, "expected CLI to parse YAML successfully"
    assert result.bracket == 14
    assert result.dot == 14


def test_library_and_cli_paths_agree(tmp_path: Path):
    cfg = _write(tmp_path, "config.yaml", """
        !set_default cfg:
          resolution: 14
        dot: ${cfg.resolution}
    """)
    lib = dracon.load(cfg.as_posix())
    assert lib["dot"] == 14
    prog = make_program(_CLI, name="prog")
    result, _ = prog.parse_args([f"+{cfg.as_posix()}"])
    assert result is not None
    assert result.dot == lib["dot"]


def test_dot_access_on_nested_mapping(tmp_path: Path):
    cfg = _write(tmp_path, "config.yaml", """
        !set_default arrows:
          shaft:
            length: 7
        dot: ${arrows.shaft.length}
    """)
    prog = make_program(_CLI, name="prog")
    result, _ = prog.parse_args([f"+{cfg.as_posix()}"])
    assert result is not None
    assert result.dot == 7
