# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset

"""Round-trip-stable references to live Python types and singletons.

Loader-level dial that emits `!Type module.qualname` for class objects and
`!Ref name` for explicitly pinned singletons on dump, and resolves them back
to the same Python identity on load via a trust-configured resolver chain.
"""

from __future__ import annotations

import builtins
import importlib
from typing import Any, Callable, Iterable

from dracon.diagnostics import DraconError


class UnknownTypeError(DraconError):
    """A `!Type` tag could not be resolved by the loader's type_resolver."""


def dotted_path(cls: type) -> str:
    """Stable import path for a class. Builtins emit bare qualnames."""
    mod = getattr(cls, '__module__', None) or 'builtins'
    qual = getattr(cls, '__qualname__', None) or cls.__name__
    return qual if mod in ('builtins', '__builtin__') else f"{mod}.{qual}"


def import_resolver(dotted: str) -> type:
    """Importlib-backed resolver: split, import, getattr through qualname parts."""
    if '.' in dotted:
        mod_name, qual = dotted.rsplit('.', 1)
        try:
            mod = importlib.import_module(mod_name)
        except ImportError as e:
            raise UnknownTypeError(f"cannot import module '{mod_name}' for type '{dotted}'") from e
    else:
        mod, qual = builtins, dotted
    try:
        return getattr(mod, qual)
    except AttributeError as e:
        raise UnknownTypeError(f"module '{getattr(mod, '__name__', mod)}' has no '{qual}'") from e


class TypeResolver:
    """Factory methods for common resolver strategies."""

    @staticmethod
    def allowlist(names: Iterable[str]) -> Callable[[str], type]:
        allowed = frozenset(names)
        def resolve(dotted: str) -> type:
            if dotted not in allowed:
                raise UnknownTypeError(f"type '{dotted}' is not in the allowlist")
            return import_resolver(dotted)
        return resolve

    @staticmethod
    def table(table: dict[str, type]) -> Callable[[str], type]:
        def resolve(dotted: str) -> type:
            try:
                return table[dotted]
            except KeyError:
                raise UnknownTypeError(f"type '{dotted}' is not in the resolver table") from None
        return resolve
