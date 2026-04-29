# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""Unified CLI parameter record.

`CliParam` is the single record describing a CLI flag/argument, regardless
of whether it was declared on a Pydantic model (`Annotated[T, CliParam(...)]`)
or in YAML (`!require name: { help: ..., short: ... }`).

`Arg` and `CliDirective` are factory aliases preserved for back-compat.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional, Type

from dracon.symbols import MISSING

ParamSource = Literal["model", "yaml"]
ParamTarget = Literal["model", "context"]
DeclKind = Literal["require", "set_default"]


@dataclass(frozen=True, slots=True)
class CliParam:
    """SSOT for one CLI parameter, model-side or YAML-side."""

    # identity
    real_name: Optional[str] = None
    source: ParamSource = "model"
    target: ParamTarget = "model"

    # display
    short: Optional[str] = None
    long: Optional[str] = None
    help: Optional[str] = None
    hidden: bool = False
    auto_dash_alias: Optional[bool] = None

    # type & default
    arg_type: Optional[Type[Any]] = None
    default: Any = field(default_factory=lambda: MISSING)
    default_str: Optional[str] = None

    # behavior (model-side surface; yaml-sourced records leave these defaulted)
    action: Optional[Callable[[Any, Any], Any]] = None
    positional: bool = False
    subcommand: bool = False
    resolvable: bool = False
    is_file: bool = False
    is_flag: Optional[bool] = None
    raw: bool = False

    # yaml-side provenance (require vs set_default + source position)
    kind: Optional[DeclKind] = None
    source_context: Any = None

    @property
    def name(self) -> Optional[str]:
        # alias for yaml-style callers that read `.name`
        return self.real_name

    @property
    def python_type(self) -> Optional[Type[Any]]:
        # alias for legacy yaml-side callers
        return self.arg_type


def Arg(**kwargs: Any) -> CliParam:
    """Model-side factory: builds a `CliParam(source='model')`."""
    kwargs.setdefault("source", "model")
    kwargs.setdefault("target", "model")
    return CliParam(**kwargs)


def CliDirective(
    name: str,
    kind: DeclKind,
    *,
    help: Optional[str] = None,
    short: Optional[str] = None,
    default: Any = None,
    python_type: Optional[Type[Any]] = None,
    hidden: bool = False,
    source_context: Any = None,
) -> CliParam:
    """YAML-side factory: builds a `CliParam(source='yaml', target='context')`.

    `python_type` maps onto the unified `arg_type` field; `default=None` is
    encoded as `MISSING` for `require` records (they have no default by
    definition) and kept as `None` for explicit nulls on `set_default`."""
    encoded_default = default if (kind == "set_default" or default is not None) else MISSING
    return CliParam(
        real_name=name,
        source="yaml",
        target="context",
        kind=kind,
        help=help,
        short=short,
        default=encoded_default,
        arg_type=python_type,
        hidden=hidden,
        source_context=source_context,
    )
