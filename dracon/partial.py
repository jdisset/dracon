# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""Partial-kind factory for the unified CallableSymbol.

`DraconPartial` is preserved as a factory alias that returns a `CallableSymbol`
of kind 'partial'. The actual partial strategy lives in `dracon.symbols`.
"""

from __future__ import annotations

from dracon.symbols import CallableSymbol


def DraconPartial(func_path: str, func, kwargs: dict) -> CallableSymbol:
    """Factory: build a partial-kind CallableSymbol. Preserved for back-compat."""
    return CallableSymbol.from_partial(func_path, func, kwargs)
