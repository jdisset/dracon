# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""SymbolTable: the runtime representation of the open vocabulary."""

from __future__ import annotations

from collections.abc import MutableMapping, Iterator, Iterable
from dataclasses import dataclass
from typing import Any

from dracon.diagnostics import DraconError
from dracon.symbols import (
    Symbol,
    SymbolKind,
    SymbolSourceInfo,
    InterfaceSpec,
    ValueSymbol,
    auto_symbol,
    MISSING,
)


class CanonicalCollisionError(DraconError):
    """Two canonical symbol entries claim the same Python type."""


@dataclass(frozen=True)
class SymbolEntry:
    name: str
    symbol: Symbol[Any]
    exported: bool = True
    source: SymbolSourceInfo | None = None
    docs: str | None = None
    canonical: bool = True  # False = consume-only alias, invisible to identify()


class SymbolTable(MutableMapping):
    """Named scope of symbols, compatible with Mapping[str, Any].

    __getitem__ returns the materialized value (symbol.materialize()),
    so interpolation code can use this as an eval namespace directly.

    For symbol-level access, use lookup_symbol() / lookup_entry().
    """

    __slots__ = (
        '_entries', '_soft_keys', '_parent',
        '_accessed_keys', '_defined_var_keys', '_suspend_tracking',
        '_identify_cache',
    )
    __dracon_no_merge__ = True

    def __init__(self, parent: SymbolTable | None = None):
        self._entries: dict[str, SymbolEntry] = {}
        self._soft_keys: set[str] = set()
        self._parent: SymbolTable | None = parent
        self._accessed_keys: set[str] | None = None
        self._defined_var_keys: set[str] | None = None
        self._suspend_tracking: bool = False
        self._identify_cache: dict[type, str] | None = None

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
        """Convenience: wrap raw value in ValueSymbol and define.

        Inserts are always non-canonical: this path is used by composition
        propagation and captured-globals sweep. Explicit vocabulary
        registration goes through define(SymbolEntry(...)).
        """
        sym = auto_symbol(value, name=key)
        self._insert_with_collision_check(
            SymbolEntry(name=key, symbol=sym, canonical=False)
        )
        self._soft_keys.discard(key)

    def __delitem__(self, key: str) -> None:
        try:
            del self._entries[key]
        except KeyError:
            if self._parent is not None and key in self._parent:
                raise KeyError(f"cannot delete inherited key '{key}'")
            raise
        self._soft_keys.discard(key)
        self._identify_cache = None

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
        self._insert_with_collision_check(entry)
        self._soft_keys.discard(entry.name)

    def set_default(self, entry: SymbolEntry) -> None:
        if entry.name in self._entries or (self._parent is not None and entry.name in self._parent):
            return
        self._insert_with_collision_check(entry)
        self._soft_keys.add(entry.name)

    def _insert_with_collision_check(self, entry: SymbolEntry) -> None:
        """Shared entry point: verify no canonical collision, then insert."""
        if entry.canonical:
            rep_type = entry.symbol.represented_type()
            if rep_type is not None:
                existing = self._canonical_type_cache().get(rep_type)
                if existing is not None and existing != entry.name:
                    raise CanonicalCollisionError(
                        f"type {rep_type.__name__} already registered as "
                        f"'{existing}', cannot also register as '{entry.name}'"
                    )
        self._entries[entry.name] = entry
        self._identify_cache = None

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

    # ── reverse lookup: value -> canonical name ──────────────────────────

    def identify(self, value: Any) -> str | None:
        """Return the canonical dump name for value, or None.

        Walks type(value).__mro__ in order against the canonical map; the
        first class whose canonical entry matches wins. Falls through to
        the parent chain if no local match is found. Non-canonical entries
        (aliases, captured globals) are invisible to this lookup.
        """
        if value is None:
            return None
        mro = type(value).__mro__
        cache = self._canonical_type_cache()
        for cls in mro:
            name = cache.get(cls)
            if name is not None:
                return name
        if self._parent is not None:
            return self._parent.identify(value)
        return None

    def _canonical_type_cache(self) -> dict[type, str]:
        """Lazy {type -> canonical name} map over local entries."""
        if self._identify_cache is None:
            cache: dict[type, str] = {}
            for name, entry in self._entries.items():
                if not entry.canonical:
                    continue
                rep_type = entry.symbol.represented_type()
                if rep_type is not None:
                    cache[rep_type] = name
            self._identify_cache = cache
        return self._identify_cache

    # ── query API (used by __scope__ in interpolation) ───────────────────

    def names(self, kind: SymbolKind | None = None) -> list[str]:
        """Symbol names, optionally filtered by kind."""
        result = []
        for name in self:
            if kind is None:
                result.append(name)
            else:
                sym = self.lookup_symbol(name)
                if sym is not None and sym.interface().kind == kind:
                    result.append(name)
        return result

    def has(self, name: str) -> bool:
        return name in self

    def interface(self, name: str) -> InterfaceSpec | None:
        """Full interface for a symbol, or None if not found."""
        sym = self.lookup_symbol(name)
        if sym is None:
            return None
        return sym.interface()

    def kinds(self) -> dict[str, SymbolKind]:
        """Name-to-kind mapping for all symbols."""
        result = {}
        for name in self:
            sym = self.lookup_symbol(name)
            if sym is not None:
                result[name] = sym.interface().kind
        return result

    def exported(self) -> SymbolTable:
        """Sub-table containing only exported entries."""
        tbl = SymbolTable()
        for entry in self.exported_entries():
            tbl._entries[entry.name] = entry
        return tbl

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
        tbl._identify_cache = None  # rebuild lazily on the clone
        return tbl

    def copy(self) -> SymbolTable:
        return self._clone(parent=self._parent)

    def clear(self) -> None:
        self._entries.clear()
        self._soft_keys.clear()
        self._identify_cache = None

    def __copy__(self) -> SymbolTable:
        return self.copy()

    def __deepcopy__(self, memo: Any) -> SymbolTable:
        return self.copy()

    # ── rendering API ────────────────────────────────────────────────────

    def describe(self, name: str | None = None) -> str:
        """Human-readable description. Single symbol or full table."""
        if name is not None:
            return _describe_one(self, name)
        return _describe_all(self)

    def to_json(self, kind: SymbolKind | None = None) -> dict:
        """Structured dict for JSON serialization. Optionally filter by kind."""
        return _to_json_dict(self, kind)

    def __repr__(self) -> str:
        n = len(self._entries)
        parent = f", parent={len(self._parent._entries)}entries" if self._parent else ""
        return f"SymbolTable({n} entries{parent})"


# ── rendering helpers ────────────────────────────────────────────────────────

# internal names to hide from catalog/symbols output
_INTERNAL_NAMES = frozenset({
    '__DRACON', '__scope__', 'construct',
    'getenv', 'getcwd', 'listdir', 'join', 'basename', 'dirname',
    'expanduser', 'isfile', 'isdir', 'Path', 'now',
    'DIR', 'FILE', 'FILE_PATH', 'FILE_STEM', 'FILE_EXT',
    'FILE_LOAD_TIME', 'FILE_LOAD_TIME_UNIX', 'FILE_LOAD_TIME_UNIX_MS', 'FILE_SIZE',
})


def _is_user_symbol(name: str) -> bool:
    """True if name is not an internal/builtin symbol."""
    return name not in _INTERNAL_NAMES and not name.startswith('__')


def _param_sig(iface: InterfaceSpec) -> str:
    """Build a short parameter signature string."""
    parts = []
    for p in iface.params:
        if p.required:
            parts.append(p.name)
        elif p.default is not MISSING:
            parts.append(f"{p.name}={p.default!r}")
        else:
            parts.append(f"{p.name}=...")
    return ", ".join(parts)


def _source_str(iface: InterfaceSpec) -> str:
    """Format source location as file:line or empty string."""
    if iface.source and iface.source.file_path:
        import os
        base = os.path.basename(iface.source.file_path)
        if iface.source.line:
            return f"{base}:{iface.source.line}"
        return base
    return ""


def _describe_one(table: SymbolTable, name: str) -> str:
    """Describe a single symbol."""
    sym = table.lookup_symbol(name)
    if sym is None:
        return ""
    iface = sym.interface()
    kind = iface.kind.value
    sig = _param_sig(iface)
    source = _source_str(iface)
    if sig:
        label = f"!{name}({sig})" if kind in ("template", "type") else f"{name}({sig})"
    else:
        label = f"!{name}" if kind in ("template", "type") else name
    return f"{label:<40} {kind:<12} {source}".rstrip()


def _describe_all(table: SymbolTable) -> str:
    """Human-readable text listing of all user symbols."""
    lines = []
    for name in sorted(table):
        if not _is_user_symbol(name):
            continue
        line = _describe_one(table, name)
        if line:
            lines.append(line)
    return "\n".join(lines)


def _json_safe(val: Any) -> Any:
    """Make a value JSON-serializable."""
    if val is MISSING:
        return None
    if isinstance(val, (str, int, float, bool, type(None))):
        return val
    return str(val)


def _symbol_to_json_entry(sym, iface) -> dict[str, Any]:
    """Build a JSON-safe dict for a single symbol's interface."""
    entry_data: dict[str, Any] = {"kind": iface.kind.value}
    if iface.params:
        entry_data["params"] = [
            {
                "name": p.name,
                "required": p.required,
                **({"default": _json_safe(p.default)} if p.default is not MISSING else {}),
            }
            for p in iface.params
        ]
    else:
        entry_data["params"] = []
    if iface.contracts:
        entry_data["contracts"] = [
            {"kind": c.kind, "name": c.name, **({"message": c.message} if c.message else {})}
            for c in iface.contracts
        ]
    if iface.source and iface.source.file_path:
        src: dict[str, Any] = {"file": iface.source.file_path}
        if iface.source.line:
            src["line"] = iface.source.line
        entry_data["source"] = src
    if iface.docs:
        entry_data["docs"] = iface.docs
    return entry_data


def _to_json_dict(table: SymbolTable, kind: SymbolKind | None = None) -> dict:
    """Structured dict of symbols for JSON serialization."""
    data = {}
    for name in sorted(table):
        if not _is_user_symbol(name):
            continue
        sym = table.lookup_symbol(name)
        if sym is None:
            continue
        iface = sym.interface()
        if kind is not None and iface.kind != kind:
            continue
        data[name] = _symbol_to_json_entry(sym, iface)
    return data
