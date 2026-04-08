# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""SymbolTable: the runtime representation of the open vocabulary."""

from __future__ import annotations

from collections.abc import MutableMapping, Iterator, Iterable
from dataclasses import dataclass
from typing import Any

from dracon.symbols import (
    Symbol,
    SymbolSourceInfo,
    ValueSymbol,
    auto_symbol,
)


@dataclass(frozen=True)
class SymbolEntry:
    name: str
    symbol: Symbol[Any]
    exported: bool = True
    source: SymbolSourceInfo | None = None
    docs: str | None = None


class SymbolTable(MutableMapping):
    """Named scope of symbols, compatible with Mapping[str, Any].

    __getitem__ returns the materialized value (symbol.materialize()),
    so interpolation code can use this as an eval namespace directly.

    For symbol-level access, use lookup_symbol() / lookup_entry().
    """

    __slots__ = ('_entries', '_soft_keys', '_parent', '_accessed_keys', '_defined_var_keys', '_suspend_tracking')

    def __init__(self, parent: SymbolTable | None = None):
        self._entries: dict[str, SymbolEntry] = {}
        self._soft_keys: set[str] = set()
        self._parent: SymbolTable | None = parent
        self._accessed_keys: set[str] | None = None
        self._defined_var_keys: set[str] | None = None
        self._suspend_tracking: bool = False

    # ── access tracking (for CLI unused-var warnings) ────────────────────

    def enable_tracking(self, defined_var_keys: set[str], shared_accessed: set[str] | None = None) -> None:
        self._defined_var_keys = set(defined_var_keys)
        self._accessed_keys = shared_accessed if shared_accessed is not None else set()

    def get_unused_defined_vars(self) -> set[str]:
        if self._defined_var_keys is None or self._accessed_keys is None:
            return set()
        return self._defined_var_keys - self._accessed_keys

    # ── Mapping protocol (materialized view) ─────────────────────────────

    def __getitem__(self, key: str) -> Any:
        entry = self._entries.get(key)
        if entry is not None:
            if self._accessed_keys is not None and not self._suspend_tracking:
                self._accessed_keys.add(key)
            return entry.symbol.materialize()
        if self._parent is not None:
            return self._parent[key]
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def __setitem__(self, key: str, value: Any) -> None:
        """Convenience: wrap raw value in ValueSymbol and define."""
        sym = auto_symbol(value, name=key)
        self._entries[key] = SymbolEntry(name=key, symbol=sym)
        self._soft_keys.discard(key)

    def __delitem__(self, key: str) -> None:
        try:
            del self._entries[key]
        except KeyError:
            if self._parent is not None and key in self._parent:
                raise KeyError(f"cannot delete inherited key '{key}'")
            raise
        self._soft_keys.discard(key)

    def __contains__(self, key: object) -> bool:
        if key in self._entries:
            return True
        if self._parent is not None:
            return key in self._parent
        return False

    def __iter__(self) -> Iterator[str]:
        seen = set(self._entries)
        yield from self._entries
        if self._parent is not None:
            for k in self._parent:
                if k not in seen:
                    yield k

    def items(self):
        """Iterate key-value pairs without triggering access tracking."""
        self._suspend_tracking = True
        try:
            return list(super().items())
        finally:
            self._suspend_tracking = False

    def values(self):
        """Iterate values without triggering access tracking."""
        self._suspend_tracking = True
        try:
            return list(super().values())
        finally:
            self._suspend_tracking = False

    def __len__(self) -> int:
        if self._parent is None:
            return len(self._entries)
        parent_unique = sum(1 for k in self._parent if k not in self._entries)
        return len(self._entries) + parent_unique

    # ── symbol-level API ─────────────────────────────────────────────────

    def define(self, entry: SymbolEntry, *, overwrite: bool = True) -> None:
        if not overwrite and entry.name in self._entries:
            return
        self._entries[entry.name] = entry
        self._soft_keys.discard(entry.name)

    def set_default(self, entry: SymbolEntry) -> None:
        if entry.name in self._entries or (self._parent is not None and entry.name in self._parent):
            return
        self._entries[entry.name] = entry
        self._soft_keys.add(entry.name)

    def is_soft(self, key: str) -> bool:
        return key in self._soft_keys

    def lookup_symbol(self, name: str) -> Symbol[Any] | None:
        entry = self._entries.get(name)
        if entry is not None:
            return entry.symbol
        if self._parent is not None:
            return self._parent.lookup_symbol(name)
        return None

    def lookup_entry(self, name: str) -> SymbolEntry | None:
        entry = self._entries.get(name)
        if entry is not None:
            return entry
        if self._parent is not None:
            return self._parent.lookup_entry(name)
        return None

    def exported_entries(self) -> Iterable[SymbolEntry]:
        for entry in self._entries.values():
            if entry.exported:
                yield entry

    def overlay(self, parent: SymbolTable) -> SymbolTable:
        """Return a new SymbolTable with self as local and parent as fallback."""
        return self._clone(parent=parent)

    # ── MutableMapping extras for backwards compat ───────────────────────

    def _clone(self, parent: SymbolTable | None = None) -> SymbolTable:
        tbl = SymbolTable(parent=parent)
        tbl._entries = dict(self._entries)
        tbl._soft_keys = set(self._soft_keys)
        # share tracking state (like TrackedContext) so accesses in copies propagate back
        tbl._accessed_keys = self._accessed_keys
        tbl._defined_var_keys = self._defined_var_keys
        tbl._suspend_tracking = False
        return tbl

    def copy(self) -> SymbolTable:
        return self._clone(parent=self._parent)

    def clear(self) -> None:
        self._entries.clear()
        self._soft_keys.clear()

    def __copy__(self) -> SymbolTable:
        return self.copy()

    def __deepcopy__(self, memo: Any) -> SymbolTable:
        return self.copy()

    def __repr__(self) -> str:
        n = len(self._entries)
        parent = f", parent={len(self._parent._entries)}entries" if self._parent else ""
        return f"SymbolTable({n} entries{parent})"
