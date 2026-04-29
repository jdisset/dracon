# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""Typed Pydantic-friendly wrapper for lazy interpolation values.

Parallel to Resolvable[T]: same generic-typing shape, different trigger.
- Resolvable[T] -> explicit .resolve(context) (subtree, user-orchestrated)
- Lazy[T]       -> resolves on attribute access from LazyDraconModel
                   (single ${...} interpolation)

Wraps the existing untyped LazyInterpolable so Pydantic field annotations
can express "T but possibly still a ${...}" without losing type narrowing.
"""

from typing import Any, Generic, Type, TypeVar, get_args

from pydantic_core import core_schema

from dracon.lazy import LazyInterpolable

T = TypeVar('T')


class Lazy(Generic[T]):
    __slots__ = ('_lazy',)

    def __init__(self, lazy: LazyInterpolable):
        self._lazy = lazy

    @classmethod
    def __get_pydantic_core_schema__(cls, source: Type[Any], handler) -> core_schema.CoreSchema:
        # accept either an existing Lazy wrapper, a raw LazyInterpolable (the natural
        # draconstructor output for ${...} fields), or a literal T value. wrap raw
        # LazyInterpolable into a Lazy so __getattribute__ can detect and resolve later.
        args = get_args(source)
        inner_schema = handler(args[0]) if args else core_schema.any_schema()

        def coerce(value: Any) -> Any:
            if isinstance(value, cls):
                return value
            if isinstance(value, LazyInterpolable):
                return cls(value)
            # not lazy: defer to inner T schema validation
            return value

        return core_schema.no_info_before_validator_function(
            coerce,
            core_schema.union_schema([
                core_schema.is_instance_schema(cls),
                inner_schema,
            ]),
        )

    def resolve(self, context=None) -> T:
        return self._lazy.resolve(context_override=context)

    def dracon_dump_to_node(self, representer):
        # delegate to the wrapped LazyInterpolable so the original ${...}
        # round-trips through the standard representer pipeline
        return representer.represent_data(self._lazy)

    def __repr__(self):
        return f"Lazy({self._lazy!r})"
