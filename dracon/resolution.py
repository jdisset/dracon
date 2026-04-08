# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""Resolution helpers that operate on a SymbolTable, not a loader reference.

This breaks the loader <-> draconstructor circular dependency by design:
resolution depends on the table, not on the loader.
"""

from __future__ import annotations

from typing import Any

from dracon.symbols import Symbol, SymbolKind
from dracon.symbol_table import SymbolTable


def resolve_symbol(table: SymbolTable, name: str) -> Symbol[Any] | None:
    """Look up a symbol by name in the table."""
    return table.lookup_symbol(name)


def resolve_tag_target(table: SymbolTable, tag_name: str) -> Any | None:
    """Resolve a tag name to its materialized value from the table.

    Used during construction to resolve !TagName to the callable/type
    it references in the symbol table.
    """
    return table.get(tag_name)


def is_type_symbol(table: SymbolTable, name: str) -> bool:
    """Check if a name resolves to a type in the table."""
    sym = table.lookup_symbol(name)
    if sym is None:
        return False
    return sym.interface().kind == SymbolKind.TYPE


def is_callable_symbol(table: SymbolTable, name: str) -> bool:
    """Check if a name resolves to a callable (non-type) in the table."""
    sym = table.lookup_symbol(name)
    if sym is None:
        return False
    kind = sym.interface().kind
    return kind in (SymbolKind.CALLABLE, SymbolKind.TEMPLATE, SymbolKind.PIPE, SymbolKind.DEFERRED)
