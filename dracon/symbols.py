# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""Core typed symbol model for the open vocabulary runtime."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, TypeVar, runtime_checkable

T = TypeVar("T")

_MISSING = object()
MISSING = _MISSING


class SymbolKind(str, Enum):
    VALUE = "value"
    TYPE = "type"
    CALLABLE = "callable"
    TEMPLATE = "template"
    PIPE = "pipe"
    DEFERRED = "deferred"


@dataclass(frozen=True)
class ParamSpec:
    name: str
    required: bool
    default: Any = field(default_factory=lambda: _MISSING)
    docs: str | None = None


@dataclass(frozen=True)
class ContractSpec:
    kind: str
    name: str
    message: str | None = None


@dataclass(frozen=True)
class SymbolSourceInfo:
    file_path: str | None = None
    line: int | None = None
    column: int | None = None


@dataclass(frozen=True)
class InterfaceSpec:
    kind: SymbolKind
    name: str | None
    params: tuple[ParamSpec, ...] = ()
    contracts: tuple[ContractSpec, ...] = ()
    returns_mapping: bool | None = None
    source: SymbolSourceInfo | None = None
    docs: str | None = None


@runtime_checkable
class Symbol(Protocol[T]):
    def interface(self) -> InterfaceSpec: ...
    def bind(self, **kwargs: Any) -> Symbol[Any]: ...
    def invoke(self, **kwargs: Any) -> T: ...
    def materialize(self) -> Any: ...
    def represented_type(self) -> type | None: ...


# ── concrete symbols ─────────────────────────────────────────────────────────


class ValueSymbol:
    """Wraps a plain value as a Symbol."""
    __slots__ = ('_value', '_name', '_source')

    def __init__(self, value: Any, *, name: str | None = None, source: SymbolSourceInfo | None = None):
        self._value = value
        self._name = name
        self._source = source

    def interface(self) -> InterfaceSpec:
        return InterfaceSpec(kind=SymbolKind.VALUE, name=self._name, source=self._source)

    def bind(self, **kwargs: Any) -> Symbol[Any]:
        return self

    def invoke(self, **kwargs: Any) -> Any:
        return self._value

    def materialize(self) -> Any:
        return self._value

    def represented_type(self) -> type | None:
        return self._value if isinstance(self._value, type) else None


class CallableSymbol:
    """Wraps a Python callable (or type) as a Symbol."""
    __slots__ = ('_callable', '_name', '_source', '_cached_interface')

    def __init__(self, obj: Any, *, name: str | None = None, source: SymbolSourceInfo | None = None):
        self._callable = obj
        self._name = name
        self._source = source
        self._cached_interface: InterfaceSpec | None = None

    def interface(self) -> InterfaceSpec:
        if self._cached_interface is not None:
            return self._cached_interface
        kind = SymbolKind.TYPE if isinstance(self._callable, type) else SymbolKind.CALLABLE
        params = _params_from_callable(self._callable)
        self._cached_interface = InterfaceSpec(
            kind=kind, name=self._name, params=params, source=self._source,
        )
        return self._cached_interface

    def bind(self, **kwargs: Any) -> Symbol[Any]:
        return BoundSymbol(self, **kwargs)

    def invoke(self, **kwargs: Any) -> Any:
        return self._callable(**kwargs)

    def materialize(self) -> Any:
        return self._callable

    def represented_type(self) -> type | None:
        return self._callable if isinstance(self._callable, type) else None


class BoundSymbol:
    """A symbol with pre-filled kwargs. Binding a bound symbol merges kwargs."""
    __slots__ = ('_inner', '_kwargs')

    def __repr__(self) -> str:
        name = self._inner.interface().name or '?'
        return f"BoundSymbol({name!r}, kwargs={list(self._kwargs)})"

    def __init__(self, inner: Symbol[Any], **kwargs: Any):
        if isinstance(inner, BoundSymbol):
            self._inner = inner._inner
            self._kwargs = {**inner._kwargs, **kwargs}
        else:
            self._inner = inner
            self._kwargs = dict(kwargs)

    def interface(self) -> InterfaceSpec:
        base = self._inner.interface()
        bound_names = frozenset(self._kwargs)
        remaining = tuple(p for p in base.params if p.name not in bound_names)
        return InterfaceSpec(
            kind=base.kind, name=base.name, params=remaining,
            contracts=base.contracts, returns_mapping=base.returns_mapping,
            source=base.source, docs=base.docs,
        )

    def bind(self, **kwargs: Any) -> Symbol[Any]:
        return BoundSymbol(self, **kwargs)

    def invoke(self, **kwargs: Any) -> Any:
        merged = {**self._kwargs, **kwargs}
        return self._inner.invoke(**merged)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        merged = {**self._kwargs, **kwargs}
        inner = self._inner.materialize()
        return inner(*args, **merged)

    def materialize(self) -> Any:
        if self._kwargs:
            return self  # bound symbol with kwargs is the materialized form
        return self._inner.materialize()

    def represented_type(self) -> type | None:
        return None  # bound symbols carry kwargs, not type identity

    def dracon_dump_to_node(self, representer: Any) -> Any:
        inner_iface = self._inner.interface()
        tag = f'!fn:{inner_iface.name}' if inner_iface.name else '!fn'
        if self._kwargs:
            return representer.represent_mapping(tag, self._kwargs)
        return representer.represent_scalar(tag, '')


# ── helpers ──────────────────────────────────────────────────────────────────

def _params_from_callable(obj: Any) -> tuple[ParamSpec, ...]:
    """Extract ParamSpec tuple from a callable's signature."""
    try:
        sig = inspect.signature(obj)
    except (ValueError, TypeError):
        return ()
    params = []
    for name, p in sig.parameters.items():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        if p.default is p.empty:
            params.append(ParamSpec(name=name, required=True))
        else:
            params.append(ParamSpec(name=name, required=False, default=p.default))
    return tuple(params)


def auto_symbol(value: Any, *, name: str | None = None, source: SymbolSourceInfo | None = None) -> Symbol[Any]:
    """Create the appropriate Symbol subclass for a value.

    DraconCallable, DraconPartial, DraconPipe, DeferredNode instances
    implement Symbol and are returned as-is. Types/classes are wrapped
    in CallableSymbol (even if they have protocol methods, since calling
    .materialize() on the class itself rather than an instance would fail).
    Plain callables get wrapped in CallableSymbol.
    Everything else becomes ValueSymbol.
    """
    # types/classes always go through CallableSymbol, even if the class
    # structurally matches the Symbol protocol (its methods are unbound)
    if isinstance(value, type):
        return CallableSymbol(value, name=name, source=source)
    # instances that already satisfy the protocol (DraconCallable, DraconPartial, DraconPipe, DeferredNode, etc.)
    if isinstance(value, (ValueSymbol, CallableSymbol, BoundSymbol)):
        return value
    if (hasattr(value, 'interface') and hasattr(value, 'bind')
        and hasattr(value, 'invoke') and hasattr(value, 'materialize')
        and hasattr(value, 'represented_type')):
        return value
    if callable(value):
        return CallableSymbol(value, name=name, source=source)
    return ValueSymbol(value, name=name, source=source)
