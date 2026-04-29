# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

from __future__ import annotations

from enum import Enum
from typing import Any, TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field
from ruamel.yaml.nodes import Node

from dracon.composer import CompositionResult
from dracon.merge import cached_merge_key
from dracon.utils import SoftPriorityDict

if TYPE_CHECKING:
    from dracon.loader import DraconLoader

_EXPORTS_SCOPES = frozenset({"exports", "prev"})


class LayerScope(str, Enum):
    ISOLATED = "isolated"
    EXPORTS = "exports"
    EXPORTS_AND_PREV = "prev"

    @property
    def receives_exports(self) -> bool:
        return self.value in _EXPORTS_SCOPES


class LayerSpec(BaseModel):
    """One unit of composition input pushed onto a CompositionStack.

    `metadata` is opaque to dracon: it survives push/replace/fork/snapshot/
    restore unchanged so downstream packages (UIs, daemons, audit systems)
    can attach provenance, authorship, or routing tags without inventing a
    parallel side-table.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    source: str | Node | CompositionResult
    context: dict[str, Any] = Field(default_factory=dict)
    merge_key: str = "<<{<+}[<~]"
    scope: LayerScope = LayerScope.ISOLATED
    label: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CompositionStackSnapshot(BaseModel):
    """Opaque structural copy of a stack's layer list and caches.

    Returned by `CompositionStack.snapshot()`; consumed by
    `CompositionStack.restore()`. Layer objects and CompositionResult
    objects are kept by reference — restore is a structural rewind, not
    a deep copy of node trees.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)
    layers: tuple[LayerSpec, ...]
    cache: tuple[CompositionResult, ...]
    contributions: tuple[CompositionResult, ...] = ()


class LayerInfo(BaseModel):
    """Inspection record for a single layer.

    `prefix` is the composed stack just below this layer (None for index 0).
    `contribution` is the layer's own composed CompositionResult before
    merging into the prefix. `composed` is the stack including this layer.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)
    index: int
    label: str | None
    metadata: dict[str, Any]
    layer: LayerSpec
    prefix: CompositionResult | None
    contribution: CompositionResult
    composed: CompositionResult


class StackTransaction:
    """Snapshot/restore handle returned by CompositionStack.transaction().

    Use as a context manager: leaving without `commit()` restores the stack
    to the snapshot taken at entry; leaving after `commit()` keeps the
    mutations. Exceptions propagate unchanged. Nested transactions each
    take their own snapshot, so an inner rollback does not affect outer
    state.
    """

    __slots__ = ("_stack", "_snapshot", "_committed", "_active")

    def __init__(self, stack: CompositionStack):
        self._stack = stack
        self._snapshot: CompositionStackSnapshot | None = None
        self._committed = False
        self._active = False

    def __enter__(self) -> StackTransaction:
        if self._active:
            raise RuntimeError("StackTransaction already entered")
        self._snapshot = self._stack.snapshot()
        self._active = True
        return self

    def commit(self) -> None:
        self._committed = True

    def __exit__(self, exc_type, exc, tb) -> bool:
        if not self._active:
            return False
        self._active = False
        if not self._committed:
            assert self._snapshot is not None
            self._stack.restore(self._snapshot)
        return False  # never swallow exceptions


def exported_context_from(comp: CompositionResult) -> dict[str, Any]:
    """Extract defined_vars from a CompositionResult, preserving soft/hard priority."""
    ctx = SoftPriorityDict(comp.defined_vars)
    for k in comp.default_vars:
        if k in ctx:
            ctx.mark_soft(k)
    return ctx


class CompositionStack:
    __slots__ = ("_loader", "_layers", "_cache", "_contributions")

    def __init__(self, loader: DraconLoader, layers: list[LayerSpec] | None = None):
        self._loader = loader
        self._layers: list[LayerSpec] = layers or []
        self._cache: list[CompositionResult] = []
        # parallel to _cache: pre-merge composition of each layer; lets
        # layer_info() avoid recomposing a layer that the main pass
        # already produced.
        self._contributions: list[CompositionResult] = []

    # -- mutations --

    def push(self, layer: str | LayerSpec, **ctx) -> int:
        if isinstance(layer, str):
            layer = LayerSpec(source=layer, context=ctx)
        elif ctx:
            layer = layer.model_copy(update={"context": {**layer.context, **ctx}})
        self._layers.append(layer)
        return len(self._layers) - 1

    def pop(self, index: int = -1) -> LayerSpec:
        if index < 0:
            index = len(self._layers) + index
        layer = self._layers.pop(index)
        self._cache = self._cache[:index]
        self._contributions = self._contributions[:index]
        return layer

    def replace(self, index: int, layer: str | LayerSpec, **ctx) -> LayerSpec:
        old = self._layers[index]
        if isinstance(layer, str):
            layer = LayerSpec(source=layer, context=ctx)
        elif ctx:
            layer = layer.model_copy(update={"context": {**layer.context, **ctx}})
        self._layers[index] = layer
        self._cache = self._cache[:index]
        self._contributions = self._contributions[:index]
        return old

    def fork(self) -> CompositionStack:
        new = CompositionStack(self._loader, list(self._layers))
        new._cache = list(self._cache)
        new._contributions = list(self._contributions)
        return new

    # -- snapshot / restore / transaction --

    def snapshot(self) -> CompositionStackSnapshot:
        """Capture the layer list and prefix cache without copying node trees."""
        return CompositionStackSnapshot(
            layers=tuple(self._layers),
            cache=tuple(self._cache),
            contributions=tuple(self._contributions),
        )

    def restore(self, snapshot: CompositionStackSnapshot) -> None:
        """Restore both layers and cache from a snapshot.

        Layer objects and cached CompositionResult objects are restored by
        reference; in-place mutation of a layer's source after pushing is
        outside the stack contract.
        """
        self._layers = list(snapshot.layers)
        self._cache = list(snapshot.cache)
        self._contributions = list(snapshot.contributions)

    def transaction(self) -> StackTransaction:
        """Return a context manager that rolls back unless `commit()` is called."""
        return StackTransaction(self)

    # -- inspection --

    def layer_info(self, index_or_label: int | str) -> LayerInfo:
        """Return prefix / contribution / composed for a single layer.

        `index_or_label` is either an int index (negative allowed) or a label
        match. Forces the stack to fully compose so prefix and composed are
        always available.
        """
        if isinstance(index_or_label, str):
            idx = self._index_for_label(index_or_label)
        else:
            idx = index_or_label
            if idx < 0:
                idx += len(self._layers)
        if idx < 0 or idx >= len(self._layers):
            raise IndexError(f"layer index {index_or_label} out of range")
        # ensure full composition so caches are populated through idx
        _ = self.composed
        layer = self._layers[idx]
        prefix = self._cache[idx - 1] if idx > 0 else None
        return LayerInfo(
            index=idx,
            label=layer.label,
            metadata=dict(layer.metadata),
            layer=layer,
            prefix=prefix,
            contribution=self._contributions[idx],
            composed=self._cache[idx],
        )

    def composed_at(self, index: int) -> CompositionResult:
        """Composed CompositionResult after layer `index`, recomposing if needed."""
        if index < 0:
            index = len(self._layers) + index
        if index < 0 or index >= len(self._layers):
            raise IndexError(f"layer index {index} out of range")
        _ = self.composed
        return self._cache[index]

    def _index_for_label(self, label: str) -> int:
        for i, layer in enumerate(self._layers):
            if layer.label == label:
                return i
        raise KeyError(f"no layer with label {label!r}")

    # -- derived --

    @property
    def composed(self) -> CompositionResult:
        if not self._layers:
            raise ValueError("empty stack")

        exports: dict[str, Any] = {}
        # find last layer needing exports so we only compute them when useful
        last_export_consumer = -1
        for j in range(len(self._layers) - 1, -1, -1):
            if self._layers[j].scope.receives_exports:
                last_export_consumer = j
                break

        for i in range(len(self._cache), len(self._layers)):
            layer = self._layers[i]

            # rebuild exports from cached prefix when resuming mid-stack
            if not exports and i > 0 and layer.scope.receives_exports:
                exports = exported_context_from(self._cache[i - 1])

            # inject exports: layer.context wins over exports
            if layer.scope.receives_exports and exports:
                ctx = {**exports, **layer.context}
            else:
                ctx = layer.context

            # inject PREV snapshot for EXPORTS_AND_PREV scope
            if layer.scope == LayerScope.EXPORTS_AND_PREV and i > 0:
                ctx = {**ctx, "PREV": _make_prev_snapshot(self._cache[i - 1], self._loader)}

            comp = self._compose_layer(layer, ctx)

            if i == 0:
                acc = self._loader.post_process_composed(comp)
            else:
                prev = self._cache[i - 1]
                mkey = cached_merge_key(layer.merge_key)
                acc = prev.merged(comp, mkey)
                if acc.trace is not None:
                    _record_layer_trace(acc, comp, i, layer)
                acc = self._loader.post_process_composed(acc)

            self._cache.append(acc)
            self._contributions.append(comp)

            if i < last_export_consumer:
                exports = exported_context_from(acc)

        return self._cache[-1]

    def construct(self, **kwargs):
        comp = self.composed
        if kwargs:
            self._loader.update_context(kwargs)
        return self._loader.load_node(comp.root)

    @property
    def layers(self) -> list[LayerSpec]:
        return self._layers

    # -- internal --

    def _compose_layer(self, layer: LayerSpec, effective_ctx: dict[str, Any] | None = None) -> CompositionResult:
        if isinstance(layer.source, CompositionResult):
            return layer.source

        ctx = effective_ctx if effective_ctx is not None else layer.context
        saved_ctx = dict(self._loader.context) if ctx else None
        if ctx:
            self._loader.update_context(ctx)

        try:
            if isinstance(layer.source, str):
                from dracon.include import compose_from_include_str, ensure_scheme
                return compose_from_include_str(
                    self._loader, ensure_scheme(layer.source),
                    custom_loaders=self._loader.custom_loaders,
                )
            elif isinstance(layer.source, Node):
                return CompositionResult(root=layer.source)
            else:
                raise TypeError(f"invalid layer source: {type(layer.source)}")
        finally:
            if saved_ctx is not None:
                self._loader.context.clear()
                self._loader.context.update(saved_ctx)


def _make_prev_snapshot(comp: CompositionResult, loader: DraconLoader) -> dict:
    """Construct a plain dict from the accumulated composition result for PREV injection."""
    from dracon.loader import DraconLoader as DL
    snap_loader = DL()
    snap_loader.yaml.constructor.yaml_base_dict_type = dict
    snap_loader.yaml.constructor.yaml_base_list_type = list
    return snap_loader.load_node(comp.root)


def _record_layer_trace(acc: CompositionResult, comp: CompositionResult, index: int, layer: LayerSpec):
    from dracon.loader import _record_file_layer_trace
    label = layer.label or _derive_label(layer)
    _record_file_layer_trace(acc, comp, index, label, metadata=layer.metadata or None)


def _derive_label(layer: LayerSpec) -> str:
    if isinstance(layer.source, str):
        return layer.source.rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    if isinstance(layer.source, CompositionResult):
        return "pre-composed"
    return "node"
