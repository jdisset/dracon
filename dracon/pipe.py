# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""DraconPipe: composed callable from a sequence of callables, created by !pipe."""

import collections.abc

_SENTINEL = object()

# tags that are dracon builtins, never constructable types (local copy to decouple from instructions.py)
_PIPE_BUILTIN_TAGS = frozenset({
    '!include', '!include?', '!noconstruct', '!unset', '!fn', '!pipe',
    '!define', '!define?', '!set_default', '!require', '!assert',
    'tag:yaml.org,2002:map', 'tag:yaml.org,2002:seq',
    'tag:yaml.org,2002:str', 'tag:yaml.org,2002:int',
    'tag:yaml.org,2002:float', 'tag:yaml.org,2002:bool',
    'tag:yaml.org,2002:null', 'tag:yaml.org,2002:binary',
    'tag:yaml.org,2002:timestamp',
})


def _has_custom_tag(node):
    """True if node has a custom YAML tag (not a builtin or default type tag)."""
    tag = getattr(node, 'tag', None)
    return tag and isinstance(tag, str) and tag.startswith('!') and tag not in _PIPE_BUILTIN_TAGS


def _stage_interface(stage):
    """Get InterfaceSpec for a stage, wrapping plain callables via auto_symbol."""
    from dracon.symbols import auto_symbol
    sym = auto_symbol(stage)
    return sym.interface()


class DraconPipe:
    """Composed callable that chains a sequence of callables.

    Each stage's output feeds into the next:
    - Mapping output: kwarg-unpacked into next stage (wins over all other kwargs)
    - Typed output: passed as single value to the next stage's unfilled !require

    Implements the Symbol protocol.
    """

    __slots__ = ('_stages', '_stage_kwargs', '_name', '_cached_interface')

    def __init__(self, stages, stage_kwargs, name=None):
        self._stages = tuple(stages)            # immutable sequence of callables
        self._stage_kwargs = tuple(stage_kwargs)  # immutable per-stage pre-filled kwargs
        self._name = name
        self._cached_interface = None

    # ── Symbol protocol ──────────────────────────────────────────────────

    def interface(self):
        if self._cached_interface is not None:
            return self._cached_interface
        from dracon.symbols import InterfaceSpec, SymbolKind, ParamSpec
        all_required, all_optional = [], []
        for stage, pre_kwargs in zip(self._stages, self._stage_kwargs):
            iface = _stage_interface(stage)
            for p in iface.params:
                if p.name in pre_kwargs:
                    continue
                if p.required:
                    if p.name not in all_required:
                        all_required.append(p.name)
                else:
                    if p.name not in all_optional:
                        all_optional.append(p.name)
        params = tuple(
            [ParamSpec(name=n, required=True) for n in all_required]
            + [ParamSpec(name=n, required=False) for n in all_optional]
        )
        self._cached_interface = InterfaceSpec(
            kind=SymbolKind.PIPE, name=self._name, params=params,
        )
        return self._cached_interface

    def bind(self, **kwargs):
        from dracon.symbols import BoundSymbol
        return BoundSymbol(self, **kwargs)

    def invoke(self, **kwargs):
        return self(**kwargs)

    def materialize(self):
        return self

    # ── existing API ─────────────────────────────────────────────────────

    def __call__(self, **kwargs):
        value = _SENTINEL
        for stage, pre_kwargs in zip(self._stages, self._stage_kwargs):
            call_kwargs = {**kwargs, **pre_kwargs}
            if value is not _SENTINEL:
                if isinstance(value, collections.abc.Mapping):
                    call_kwargs.update(value)
                else:
                    unfilled = _get_unfilled_require(stage, call_kwargs)
                    if unfilled is not None:
                        call_kwargs[unfilled] = value
                    # else: stage has all params, value passes through
            value = stage(**call_kwargs)
        return value

    def __deepcopy__(self, memo):
        clone = DraconPipe.__new__(DraconPipe)
        memo[id(self)] = clone
        clone._stages = self._stages
        clone._stage_kwargs = self._stage_kwargs
        clone._name = self._name
        clone._cached_interface = None
        return clone

    def __repr__(self):
        return f"DraconPipe(name={self._name!r}, stages={len(self._stages)})"


# ── interface-based threading helpers ────────────────────────────────────────


def _get_unfilled_require(stage, filled_kwargs):
    """Find the single unfilled required param in stage given already-filled kwargs.

    Uses the unified symbol interface instead of bespoke scanning.
    Returns None if zero unfilled (stage runs independently, no threading).
    Raises CompositionError if 2+ unfilled requires (ambiguous).
    """
    from dracon.diagnostics import CompositionError
    iface = _stage_interface(stage)
    required = [p.name for p in iface.params if p.required]
    unfilled = [r for r in required if r not in filled_kwargs]
    if len(unfilled) == 0:
        return None  # no threading needed, stage runs independently
    if len(unfilled) > 1:
        raise CompositionError(
            f"pipe: stage has {len(unfilled)} unfilled !require parameters ({unfilled}), "
            f"expected exactly 1 to receive piped value. Pre-fill extras via inline kwargs."
        )
    return unfilled[0]


# ── pipe creation ────────────────────────────────────────────────────────────


def create_pipe_callable(value_node, loader, key_node):
    """Create a DraconPipe from a !pipe sequence node.

    Called from Define.get_name_and_value() when value_node.tag == '!pipe'.
    """
    from dracon.diagnostics import CompositionError
    from dracon.composer import DraconMappingNode, DraconSequenceNode
    from dracon.nodes import DraconScalarNode, node_source
    from dracon.interpolation import InterpolableNode, evaluate_expression

    source = node_source(key_node)
    name = key_node.value

    if not isinstance(value_node, DraconSequenceNode):
        raise CompositionError(
            f"!pipe value must be a sequence, got {type(value_node).__name__}",
            context=source,
        )

    if not value_node.value:
        raise CompositionError("!pipe sequence must not be empty", context=source)

    stages = []
    stage_kwargs = []

    for item in value_node.value:
        if isinstance(item, InterpolableNode):
            # dynamic stage: ${cleaner}
            resolved = evaluate_expression(
                item.value, engine=loader.interpolation_engine,
                context=item.context, source_context=getattr(item, 'source_context', None),
            )
            _validate_stage(resolved, item.value, source)
            _append_stage(stages, stage_kwargs, resolved, {})
        elif _has_custom_tag(item):
            # tagged node (e.g. !fn:path { kwargs }) -- construct via loader
            from dracon.composer import CompositionResult
            resolved = loader.load_composition_result(CompositionResult(root=item))
            _validate_stage(resolved, item.tag, source)
            _append_stage(stages, stage_kwargs, resolved, {})
        elif isinstance(item, DraconScalarNode):
            # bare name: resolve from context
            stage_name = item.value
            resolved = _resolve_stage_name(stage_name, loader, item, source)
            _append_stage(stages, stage_kwargs, resolved, {})
        elif isinstance(item, DraconMappingNode):
            # name: {kwargs} -- exactly one entry
            if len(item.value) != 1:
                raise CompositionError(
                    f"!pipe mapping stage must have exactly one key, got {len(item.value)}",
                    context=source,
                )
            k_node, v_node = item.value[0]
            stage_name = k_node.value
            resolved = _resolve_stage_name(stage_name, loader, k_node, source)
            # construct the pre-fill kwargs
            from dracon.composer import CompositionResult
            pre = loader.load_composition_result(CompositionResult(root=v_node))
            if not isinstance(pre, dict):
                pre = dict(pre)
            _append_stage(stages, stage_kwargs, resolved, pre)
        else:
            raise CompositionError(
                f"!pipe stage must be a string, mapping, or interpolation, "
                f"got {type(item).__name__}",
                context=source,
            )

    return DraconPipe(stages=stages, stage_kwargs=stage_kwargs, name=name)


def _resolve_stage_name(name, loader, node, source):
    """Look up a stage name in loader context or node context."""
    from dracon.diagnostics import CompositionError
    resolved = loader.context.get(name)
    if resolved is None and hasattr(node, 'context'):
        resolved = (node.context or {}).get(name)
    if resolved is None:
        raise CompositionError(
            f"!pipe: stage '{name}' not found in context",
            context=source,
        )
    _validate_stage(resolved, name, source)
    return resolved


def _validate_stage(obj, name, source):
    """Validate that a resolved stage is callable."""
    from dracon.diagnostics import CompositionError
    if not callable(obj):
        raise CompositionError(
            f"!pipe: stage '{name}' is not callable (got {type(obj).__name__})",
            context=source,
        )


def _append_stage(stages, stage_kwargs, resolved, pre):
    """Append a stage, flattening nested DraconPipe instances."""
    if isinstance(resolved, DraconPipe):
        # flatten: inline the sub-pipe's stages
        for s, sk in zip(resolved._stages, resolved._stage_kwargs):
            merged = {**sk, **pre} if pre else sk
            stages.append(s)
            stage_kwargs.append(merged)
    else:
        stages.append(resolved)
        stage_kwargs.append(pre)
