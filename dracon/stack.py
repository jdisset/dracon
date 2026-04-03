# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

from __future__ import annotations

from enum import Enum
from typing import Any, TYPE_CHECKING

from pydantic import BaseModel, ConfigDict
from ruamel.yaml.nodes import Node

from dracon.composer import CompositionResult
from dracon.merge import cached_merge_key

if TYPE_CHECKING:
    from dracon.loader import DraconLoader


class LayerScope(str, Enum):
    ISOLATED = "isolated"
    EXPORTS = "exports"
    EXPORTS_AND_PREV = "prev"


class LayerSpec(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    source: str | Node | CompositionResult
    context: dict[str, Any] = {}
    merge_key: str = "<<{<+}[<~]"
    scope: LayerScope = LayerScope.ISOLATED
    label: str | None = None


class CompositionStack:
    __slots__ = ("_loader", "_layers", "_cache")

    def __init__(self, loader: DraconLoader, layers: list[LayerSpec] | None = None):
        self._loader = loader
        self._layers: list[LayerSpec] = layers or []
        self._cache: list[CompositionResult] = []

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
        return layer

    def replace(self, index: int, layer: str | LayerSpec, **ctx) -> LayerSpec:
        old = self._layers[index]
        if isinstance(layer, str):
            layer = LayerSpec(source=layer, context=ctx)
        elif ctx:
            layer = layer.model_copy(update={"context": {**layer.context, **ctx}})
        self._layers[index] = layer
        self._cache = self._cache[:index]
        return old

    def fork(self) -> CompositionStack:
        new = CompositionStack(self._loader, list(self._layers))
        new._cache = list(self._cache)
        return new

    # -- derived --

    @property
    def composed(self) -> CompositionResult:
        if not self._layers:
            raise ValueError("empty stack")

        for i in range(len(self._cache), len(self._layers)):
            layer = self._layers[i]
            comp = self._compose_layer(layer)

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

    def _compose_layer(self, layer: LayerSpec) -> CompositionResult:
        if isinstance(layer.source, CompositionResult):
            return layer.source

        saved_ctx = dict(self._loader.context) if layer.context else None
        if layer.context:
            self._loader.update_context(layer.context)

        try:
            if isinstance(layer.source, str):
                from dracon.include import compose_from_include_str
                source = layer.source
                if ":" not in source:
                    source = f"file:{source}"
                return compose_from_include_str(
                    self._loader, source,
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


def _record_layer_trace(acc: CompositionResult, comp: CompositionResult, index: int, layer: LayerSpec):
    from dracon.loader import _record_file_layer_trace
    label = layer.label or _derive_label(layer)
    _record_file_layer_trace(acc, comp, index, label)


def _derive_label(layer: LayerSpec) -> str:
    if isinstance(layer.source, str):
        return layer.source.rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    if isinstance(layer.source, CompositionResult):
        return "pre-composed"
    return "node"
