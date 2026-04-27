# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""DraconPartial: serializable partial application of a Python callable, created by !fn:path.

Implements the Symbol protocol: interface() / bind() / invoke() / materialize().
"""

from __future__ import annotations


class DraconPartial:
    """Partial application of a Python callable with pre-filled kwargs.

    Created by !fn:dotted.path { kwargs } syntax. Unlike DraconCallable (which
    wraps a YAML template), this wraps an actual Python function with stored
    kwargs that get merged at call time.

    Implements the Symbol protocol.
    """

    __slots__ = ('_func_path', '_func', '_kwargs', '_cached_interface')

    def __init__(self, func_path: str, func, kwargs: dict):
        self._func_path = func_path
        self._func = func
        self._kwargs = kwargs
        self._cached_interface = None

    # ── Symbol protocol ──────────────────────────────────────────────────

    def interface(self):
        if self._cached_interface is not None:
            return self._cached_interface
        from dracon.symbols import (
            InterfaceSpec, SymbolKind, _params_from_callable,
            _return_annotation_from_callable,
        )
        all_params = _params_from_callable(self._func)
        bound_names = frozenset(self._kwargs)
        remaining = tuple(p for p in all_params if p.name not in bound_names)
        ret_anno, ret_name = _return_annotation_from_callable(self._func)
        self._cached_interface = InterfaceSpec(
            kind=SymbolKind.CALLABLE, name=self._func_path, params=remaining,
            return_annotation=ret_anno, return_annotation_name=ret_name,
        )
        return self._cached_interface

    def bind(self, **kwargs):
        from dracon.symbols import BoundSymbol
        return BoundSymbol(self, **kwargs)

    def invoke(self, **kwargs):
        merged = {**self._kwargs, **kwargs}
        return self._func(**merged)

    def materialize(self):
        return self

    def represented_type(self):
        return self._func if isinstance(self._func, type) else None

    # ── existing API ─────────────────────────────────────────────────────

    def __call__(self, *args, **runtime_kwargs):
        merged = {**self._kwargs, **runtime_kwargs}
        return self._func(*args, **merged)

    def dracon_dump_to_node(self, representer):
        tag = f'!fn:{self._func_path}'
        if self._kwargs:
            return representer.represent_mapping(tag, self._kwargs)
        return representer.represent_scalar(tag, '')

    def __reduce__(self):
        return (_reconstruct_partial, (self._func_path, self._kwargs))

    def __repr__(self):
        return f"DraconPartial({self._func_path!r}, kwargs={list(self._kwargs)})"

    def __deepcopy__(self, memo):
        from dracon.utils import deepcopy
        clone = DraconPartial.__new__(DraconPartial)
        memo[id(self)] = clone
        clone._func_path = self._func_path
        clone._func = self._func
        clone._kwargs = deepcopy(self._kwargs, memo)
        clone._cached_interface = self._cached_interface
        return clone


def _reconstruct_partial(func_path, kwargs):
    """Pickle reconstruction: re-imports the function from its dotted path."""
    from typing import Any
    from dracon.draconstructor import resolve_type
    if '.' not in func_path:
        raise ValueError(
            f"cannot unpickle DraconPartial with context-only name '{func_path}' "
            f"-- function must be importable via dotted path"
        )
    func = resolve_type(f'!{func_path}')
    if func is Any:
        raise ValueError(f"cannot unpickle DraconPartial: '{func_path}' is not importable")
    return DraconPartial(func_path, func, kwargs)
