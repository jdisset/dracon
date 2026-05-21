# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset
"""Step 04: unified CLI flag discovery via `InterfaceSpec.params`.

The unified walker `collect_cli_params(comp_res, loader)` is the single
ingest point: YAML-side directives plus every flag-bearing symbol in
the loader's table contribute through one path.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel

from dracon import DraconLoader, auto_symbol
from dracon.cli_discovery import (
    _CLI_FLAG_KINDS,
    collect_cli_params,
    discover_cli_directives,
)
from dracon.cli_param import Arg
from dracon.symbols import ParamSpec, SymbolKind


def _write(tmp_path: Path, name: str, content: str) -> str:
    p = tmp_path / name
    p.write_text(textwrap.dedent(content).lstrip())
    return f"file:{p.as_posix()}"


def test_cli_flag_kinds_filter():
    assert SymbolKind.TYPE in _CLI_FLAG_KINDS
    assert SymbolKind.CALLABLE in _CLI_FLAG_KINDS
    assert SymbolKind.TEMPLATE in _CLI_FLAG_KINDS
    assert SymbolKind.PIPE in _CLI_FLAG_KINDS
    assert SymbolKind.VALUE not in _CLI_FLAG_KINDS
    assert SymbolKind.DEFERRED not in _CLI_FLAG_KINDS


def test_paramspec_carries_cli_metadata():
    p = ParamSpec(name='port', required=False, default=8080, cli_short='-p', docs='bind port')
    assert p.cli_short == '-p'
    assert p.cli_hidden is False


def test_yaml_require_still_works(tmp_path):
    src = _write(tmp_path, "x.yaml", """
        !require port:
          help: bind port
          short: -p
        used: ${port}
    """)
    params = discover_cli_directives([src], seed_context={"port": 1})
    assert any(p.real_name == 'port' and p.short == '-p' for p in params)


def test_registered_callable_surfaces_flags():
    def serve(port: int = 8080, host: str = "localhost"):
        """run the server."""
        return port, host

    loader = DraconLoader(enable_interpolation=True)
    loader.context['serve'] = serve
    comp = loader.compose_config_from_str("x: 1")
    out = collect_cli_params(comp, loader)
    by_name = {p.real_name: p for p in out}
    assert {'port', 'host'} <= set(by_name)
    assert by_name['port'].default == 8080
    assert by_name['port'].arg_type is int


def test_value_symbols_excluded():
    loader = DraconLoader(enable_interpolation=True)
    loader.context['some_str'] = "hello"
    loader.context['some_int'] = 42
    comp = loader.compose_config_from_str("x: 1")
    out = collect_cli_params(comp, loader)
    names = {p.real_name for p in out}
    assert 'some_str' not in names
    assert 'some_int' not in names


def test_live_lazy_excluded_from_cli():
    src = """!live component:
  color: ${component.kind}
"""
    loader = DraconLoader(enable_interpolation=True)
    comp = loader.compose_config_from_str(src)
    out = collect_cli_params(comp, loader)
    assert all(p.real_name != 'component' for p in out)


def test_model_arg_round_trips_through_paramspec():
    class Config(BaseModel):
        port: Annotated[int, Arg(short='p', help='server port')] = 8080
        host: Annotated[str, Arg(help='server host')] = 'localhost'

    sym = auto_symbol(Config)
    iface = sym.interface()
    by_name = {p.name: p for p in iface.params}
    assert by_name['port'].cli_short == 'p'
    assert by_name['port'].docs == 'server port'
    assert by_name['host'].docs == 'server host'


def test_model_type_in_loader_surfaces_arg_flags():
    class Config(BaseModel):
        port: Annotated[int, Arg(short='p', help='server port')] = 8080

    loader = DraconLoader(enable_interpolation=True)
    loader.context['Config'] = Config
    comp = loader.compose_config_from_str("x: 1")
    out = collect_cli_params(comp, loader)
    by_name = {p.real_name: p for p in out}
    assert 'port' in by_name
    assert by_name['port'].short == 'p'
    assert by_name['port'].help == 'server port'


def test_yaml_wins_over_symbol_table_on_collision(tmp_path):
    """A `!set_default` and a registered callable both declaring `port`
    dedupe last-wins; YAML directives land after the symbol-table walk,
    so the YAML record wins.
    """
    src = _write(tmp_path, "x.yaml", """
        !set_default port:
          default: 9090
          help: yaml override
    """)
    def serve(port: int = 8080):
        return port

    def factory(**kw):
        L = DraconLoader(**kw)
        L.context['serve'] = serve
        return L

    params = discover_cli_directives([src], seed_context={}, loader_factory=factory)
    port_params = [p for p in params if p.real_name == 'port']
    assert len(port_params) == 1
    assert port_params[0].help == 'yaml override'
    assert port_params[0].default == 9090
