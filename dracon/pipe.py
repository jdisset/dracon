# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""DraconPipe: composed callable from a sequence of callables, created by !pipe."""

import collections.abc

_SENTINEL = object()

def _has_custom_tag(node):
    """True if node has a custom YAML tag (not a builtin or default type tag)."""
    from dracon.instructions import _BUILTIN_TAGS
    tag = getattr(node, 'tag', None)
    return tag and isinstance(tag, str) and tag.startswith('!') and tag not in _BUILTIN_TAGS


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
        req, opt = _scan_pipe_params(self)
        params = tuple(
            [ParamSpec(name=n, required=True) for n in req]
            + [ParamSpec(name=n, required=False) for n in opt]
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
                    call_kwargs[unfilled] = value
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


# ── signature introspection ──────────────────────────────────────────────────


def _scan_template_params(callable_obj):
    """Extract (required, optional) param names from a callable.

    Returns (list[str], list[str]) -- required param names, optional param names.
    Delegates to the Symbol protocol's interface() when available,
    falls back to inspect.signature for plain callables.
    """
    # Symbol protocol: DraconCallable, DraconPartial, DraconPipe all have interface()
    if hasattr(callable_obj, 'interface') and not isinstance(callable_obj, type):
        iface = callable_obj.interface()
        required = [p.name for p in iface.params if p.required]
        optional = [p.name for p in iface.params if not p.required]
        return required, optional
    if callable(callable_obj):
        return _scan_python_callable_params(callable_obj)
    return [], []


def _scan_dracon_callable_params(fn):
    """Backward compat wrapper. Delegates to fn._do_scan_params()."""
    if fn._cached_params is not None:
        return fn._cached_params
    result = fn._do_scan_params()
    fn._cached_params = result
    return result


def _scan_pipe_params(pipe):
    """Compute params for a DraconPipe from its stages."""
    all_required = []
    all_optional = []
    for stage, pre_kwargs in zip(pipe._stages, pipe._stage_kwargs):
        req, opt = _scan_template_params(stage)
        for r in req:
            if r not in pre_kwargs and r not in all_required:
                all_required.append(r)
        for o in opt:
            if o not in pre_kwargs and o not in all_optional:
                all_optional.append(o)
    return all_required, all_optional


def _scan_python_callable_params(fn):
    """Use inspect.signature for plain Python callables."""
    import inspect
    try:
        sig = inspect.signature(fn)
    except (ValueError, TypeError):
        return [], []
    required = []
    optional = []
    for name, param in sig.parameters.items():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        if param.default is param.empty:
            required.append(name)
        else:
            optional.append(name)
    return required, optional


def _get_unfilled_require(stage, filled_kwargs):
    """Find the single unfilled !require in stage given already-filled kwargs.

    Raises CompositionError if zero or 2+ unfilled requires.
    """
    from dracon.diagnostics import CompositionError
    required, _ = _scan_template_params(stage)
    unfilled = [r for r in required if r not in filled_kwargs]
    if len(unfilled) == 0:
        raise CompositionError(
            f"pipe: stage has no unfilled !require parameters to receive piped value. "
            f"Required params: {required}, filled: {list(filled_kwargs.keys())}"
        )
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
