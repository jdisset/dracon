"""Tests for the unified `CliParam` record.

Both `Arg` (model-side) and `CliDirective` (YAML-side) build the same
record. The factories are back-compat shims; the SSOT is `CliParam`.
"""

from __future__ import annotations

import pytest

from dracon import Arg, CliDirective
from dracon.cli_param import CliParam
from dracon.symbols import MISSING


def test_cliparam_is_frozen_slotted_dataclass():
    p = CliParam(real_name="x")
    with pytest.raises(Exception):
        p.real_name = "y"  # frozen
    # slots: no __dict__
    assert not hasattr(p, "__dict__")


def test_arg_factory_builds_model_sourced_param():
    a = Arg(real_name="port", short="p", help="bind port")
    assert isinstance(a, CliParam)
    assert a.source == "model"
    assert a.target == "model"
    assert a.short == "p"
    assert a.help == "bind port"


def test_arg_factory_preserves_subcommand_flag():
    a = Arg(subcommand=True, positional=True)
    assert a.source == "model"
    assert a.subcommand is True
    assert a.positional is True


def test_clidirective_factory_builds_yaml_sourced_param():
    d = CliDirective(name="port", kind="require", help="bind port", short="-p")
    assert isinstance(d, CliParam)
    assert d.source == "yaml"
    assert d.target == "context"
    assert d.real_name == "port"
    assert d.kind == "require"
    assert d.help == "bind port"
    assert d.short == "-p"


def test_clidirective_name_alias():
    """legacy `.name` attribute still maps to real_name."""
    d = CliDirective(name="port", kind="require")
    assert d.name == "port"


def test_clidirective_python_type_alias():
    """legacy `.python_type` attribute still maps to arg_type."""
    d = CliDirective(name="limit", kind="set_default", python_type=int, default=10)
    assert d.python_type is int
    assert d.arg_type is int


def test_require_default_is_missing():
    """!require has no default → encoded as MISSING."""
    d = CliDirective(name="port", kind="require")
    assert d.default is MISSING


def test_set_default_default_preserved():
    d = CliDirective(name="port", kind="set_default", default=8080)
    assert d.default == 8080


def test_set_default_none_default_preserved():
    """explicit None on set_default stays None (it is a real value)."""
    d = CliDirective(name="x", kind="set_default", default=None)
    assert d.default is None


def test_arg_and_clidirective_share_record_type():
    """SSOT: both factories build the same dataclass."""
    a = Arg(real_name="port")
    d = CliDirective(name="port", kind="require")
    assert type(a) is type(d) is CliParam


def test_arg_alias_exported_from_dracon():
    import dracon
    assert dracon.Arg is Arg


def test_clidirective_alias_exported_from_dracon():
    import dracon
    assert dracon.CliDirective is CliDirective
