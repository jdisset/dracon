# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""Pipe-kind strategy for the unified CallableSymbol.

A pipe chains a sequence of callables; each stage's output threads into the
next via the unified Symbol interface.

`DraconPipe` is preserved as a factory alias that returns a `CallableSymbol`
of kind 'pipe'.
"""

import collections.abc

from dracon.symbols import (
    CallableSymbol, InterfaceSpec, SymbolKind, MISSING,
    auto_symbol, register_callable_strategy,
)

_SENTINEL = object()

# tags that are dracon builtins, never constructable types (decoupled from instructions.py)
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
    tag = getattr(node, 'tag', None)
    return tag and isinstance(tag, str) and tag.startswith('!') and tag not in _PIPE_BUILTIN_TAGS


def _stage_interface(stage):
    return auto_symbol(stage).interface()


def _stage_name(stage) -> str:
    iface_name = _stage_interface(stage).name
    if iface_name:
        return iface_name
    return getattr(stage, '__name__', None) or repr(stage)


def _is_pipe(obj) -> bool:
    return isinstance(obj, CallableSymbol) and obj._kind == 'pipe'


class _PipeStrategy:
    def interface(self, sym):
        seen_required: dict = {}
        seen_optional: dict = {}
        last_iface = None
        for stage, pre_kwargs in zip(sym._stages, sym._stage_kwargs):
            iface = _stage_interface(stage)
            last_iface = iface
            for p in iface.params:
                if p.name in pre_kwargs:
                    continue
                bucket = seen_required if p.required else seen_optional
                if p.name not in bucket:
                    bucket[p.name] = p
        params = tuple(list(seen_required.values()) + list(seen_optional.values()))
        ret_anno = MISSING
        ret_anno_name = None
        if last_iface is not None:
            ret_anno = last_iface.return_annotation
            ret_anno_name = last_iface.return_annotation_name
        return InterfaceSpec(
            kind=SymbolKind.PIPE, name=sym._name, params=params,
            return_annotation=ret_anno, return_annotation_name=ret_anno_name,
        )

    def invoke(self, sym, kwargs, *, invocation_context=None):
        return _run_pipe(sym, kwargs)

    def dump(self, sym, representer):
        items = []
        for stage, pre_kwargs in zip(sym._stages, sym._stage_kwargs):
            if hasattr(stage, 'dracon_dump_to_node'):
                # pre_kwargs already merged into the wrapped symbol's kwargs
                items.append(stage)
            elif pre_kwargs:
                items.append({_stage_name(stage): dict(pre_kwargs)})
            else:
                items.append(_stage_name(stage))
        return representer.represent_sequence('!pipe', items)

    def represented_type(self, sym):
        return None  # pipes compose callables, no type identity

    def reduce(self, sym):
        # stages may be context-bound callables; not generally picklable
        raise TypeError("CallableSymbol of kind 'pipe' is not picklable")

    def deepcopy(self, sym, memo):
        clone = CallableSymbol.__new__(CallableSymbol)
        memo[id(sym)] = clone
        clone._kind = 'pipe'
        clone._stages = sym._stages
        clone._stage_kwargs = sym._stage_kwargs
        clone._name = sym._name
        clone._cached_interface = None
        clone._source = None
        clone._callable = None
        clone._func_path = None
        clone._kwargs = None
        clone._template_node = None
        clone._loader = None
        clone._file_context = None
        clone._call_depth = 0
        clone._has_return = False
        clone._cached_params = None
        return clone


def _run_pipe(sym, kwargs):
    value = _SENTINEL
    for stage, pre_kwargs in zip(sym._stages, sym._stage_kwargs):
        call_kwargs = {**kwargs, **pre_kwargs}
        if value is not _SENTINEL:
            if isinstance(value, collections.abc.Mapping):
                call_kwargs.update(value)
            else:
                unfilled = _get_unfilled_require(stage, call_kwargs)
                if unfilled is not None:
                    call_kwargs[unfilled] = value
        value = stage(**call_kwargs)
    return value


register_callable_strategy('pipe', _PipeStrategy())


# ── factory alias preserving the legacy import surface ─────────────────────


def DraconPipe(stages, stage_kwargs, name=None) -> CallableSymbol:
    """Factory: build a pipe-kind CallableSymbol. Preserved for back-compat."""
    return CallableSymbol.from_pipe(stages, stage_kwargs, name=name)


# ── interface-based threading helpers ────────────────────────────────────────


def _get_unfilled_require(stage, filled_kwargs):
    """Find the single unfilled required param in stage given already-filled kwargs.

    Returns None if zero unfilled (stage runs independently, no threading).
    Raises CompositionError if 2+ unfilled requires (ambiguous).
    """
    from dracon.diagnostics import CompositionError
    iface = _stage_interface(stage)
    required = [p.name for p in iface.params if p.required]
    unfilled = [r for r in required if r not in filled_kwargs]
    if len(unfilled) == 0:
        return None
    if len(unfilled) > 1:
        raise CompositionError(
            f"pipe: stage has {len(unfilled)} unfilled !require parameters ({unfilled}), "
            f"expected exactly 1 to receive piped value. Pre-fill extras via inline kwargs."
        )
    return unfilled[0]


# ── pipe creation ────────────────────────────────────────────────────────────


def create_pipe_callable(value_node, loader, key_node):
    """Create a pipe-kind CallableSymbol from a !pipe sequence node."""
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
            resolved = evaluate_expression(
                item.value, engine=loader.interpolation_engine,
                context=item.context, source_context=getattr(item, 'source_context', None),
            )
            _validate_stage(resolved, item.value, source)
            _append_stage(stages, stage_kwargs, resolved, {})
        elif _has_custom_tag(item):
            from dracon.composer import CompositionResult
            resolved = loader.load_composition_result(CompositionResult(root=item))
            _validate_stage(resolved, item.tag, source)
            _append_stage(stages, stage_kwargs, resolved, {})
        elif isinstance(item, DraconScalarNode):
            stage_name = item.value
            resolved = _resolve_stage_name(stage_name, loader, item, source)
            _append_stage(stages, stage_kwargs, resolved, {})
        elif isinstance(item, DraconMappingNode):
            if len(item.value) != 1:
                raise CompositionError(
                    f"!pipe mapping stage must have exactly one key, got {len(item.value)}",
                    context=source,
                )
            k_node, v_node = item.value[0]
            stage_name = k_node.value
            resolved = _resolve_stage_name(stage_name, loader, k_node, source)
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

    return CallableSymbol.from_pipe(stages=stages, stage_kwargs=stage_kwargs, name=name)


def _resolve_stage_name(name, loader, node, source):
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
    from dracon.diagnostics import CompositionError
    if not callable(obj):
        raise CompositionError(
            f"!pipe: stage '{name}' is not callable (got {type(obj).__name__})",
            context=source,
        )


def _append_stage(stages, stage_kwargs, resolved, pre):
    """Append a stage, flattening nested pipe-kind CallableSymbol instances."""
    if _is_pipe(resolved):
        for s, sk in zip(resolved._stages, resolved._stage_kwargs):
            merged = {**sk, **pre} if pre else sk
            stages.append(s)
            stage_kwargs.append(merged)
    else:
        stages.append(resolved)
        stage_kwargs.append(pre)
