# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""Template-kind strategy for the unified CallableSymbol.

Templates wrap a YAML !fn body. Each invocation deepcopies the template node,
injects kwargs as context, and runs composition + construction on a loader copy.

`DraconCallable` is preserved as a factory alias that returns a `CallableSymbol`
of kind 'template'.
"""

from __future__ import annotations

from dracon.symbols import (
    CallableSymbol, InterfaceSpec, SymbolKind, SymbolSourceInfo, MISSING,
    ParamSpec, resolve_annotation, register_callable_strategy,
)
from dracon.utils import deepcopy

_MAX_CALL_DEPTH = 32


def _scan_template_interface(node, loader) -> tuple:
    """Single pass over a template/deferred mapping body.

    Reads `!require[:Type]` / `!set_default[:Type]` / `!define?[:Type]`
    keys for params, and `!returns[:Type]` for the return annotation.

    Returns `(params_tuple, return_annotation_name | None)`.
    """
    from dracon.composer import DraconMappingNode
    from dracon.instructions import match_instruct, Require, SetDefault, Returns
    if not isinstance(node, DraconMappingNode):
        return (), None
    scope = getattr(loader, 'context', None) if loader is not None else None
    required: list[ParamSpec] = []
    optional: list[ParamSpec] = []
    ret_anno_name: str | None = None
    for k_node, v_node in node.value:
        tag = getattr(k_node, 'tag', None)
        if not tag:
            continue
        inst = match_instruct(tag)
        if inst is None:
            continue
        if isinstance(inst, Returns):
            if inst.annotation_name:
                ret_anno_name = inst.annotation_name
            else:
                v_val = getattr(v_node, 'value', None)
                if isinstance(v_val, str) and v_val.strip():
                    ret_anno_name = v_val.strip()
            continue
        if not isinstance(inst, (Require, SetDefault)):
            continue
        name = getattr(k_node, 'value', None)
        if name is None:
            continue
        anno_name = getattr(inst, 'annotation_name', None)
        anno_obj = resolve_annotation(anno_name, scope) if anno_name else MISSING
        v_val = getattr(v_node, 'value', None)
        if isinstance(v_val, str) and v_val:
            docs = v_val
        elif isinstance(v_node, DraconMappingNode):
            docs = None
            for kk, vv in v_node.value:
                if getattr(kk, 'value', None) == 'help':
                    h = getattr(vv, 'value', None)
                    if isinstance(h, str) and h:
                        docs = h
                    break
        else:
            docs = None
        is_required = isinstance(inst, Require)
        spec = ParamSpec(
            name=name, required=is_required, docs=docs,
            annotation=anno_obj, annotation_name=anno_name,
        )
        (required if is_required else optional).append(spec)
    return tuple(required + optional), ret_anno_name


class _TemplateStrategy:
    def interface(self, sym):
        if sym._cached_params is not None:
            params, ret_anno_name = sym._cached_params
        else:
            params, ret_anno_name = _scan_template_interface(sym._template_node, sym._loader)
            sym._cached_params = (params, ret_anno_name)
        source = None
        if sym._source:
            source = SymbolSourceInfo(
                file_path=getattr(sym._source, 'file_path', None),
                line=getattr(sym._source, 'line', None),
            )
        scope = getattr(sym._loader, 'context', None) if sym._loader else None
        ret_anno_obj = resolve_annotation(ret_anno_name, scope) if ret_anno_name else MISSING
        return InterfaceSpec(
            kind=SymbolKind.TEMPLATE, name=sym._name,
            params=params, source=source,
            return_annotation=ret_anno_obj,
            return_annotation_name=ret_anno_name,
        )

    def invoke(self, sym, kwargs, *, invocation_context=None):
        return _run_template(sym, kwargs, invocation_context=invocation_context)

    def dump(self, sym, representer):
        from dracon.composer import fast_copy_node_tree
        inner = representer.represent_data(fast_copy_node_tree(sym._template_node))
        inner.tag = f'!fn:{sym._name}' if sym._name else '!fn'
        return inner

    def represented_type(self, sym):
        return None  # templates have no single underlying Python type

    def reduce(self, sym):
        # template state is loader-bound; no clean dotted-path round-trip
        raise TypeError("CallableSymbol of kind 'template' is not picklable")

    def deepcopy(self, sym, memo):
        clone = CallableSymbol.__new__(CallableSymbol)
        memo[id(sym)] = clone
        clone._kind = 'template'
        clone._template_node = sym._template_node
        clone._loader = sym._loader
        clone._source = sym._source
        clone._file_context = sym._file_context
        clone._name = sym._name
        clone._call_depth = 0
        clone._cached_params = sym._cached_params
        clone._has_return = sym._has_return
        clone._cached_interface = sym._cached_interface
        clone._callable = None
        clone._func_path = None
        clone._kwargs = None
        clone._stages = None
        clone._stage_kwargs = None
        return clone


def _run_template(sym, kwargs, invocation_context=None):
    from dracon.composer import CompositionResult
    from dracon.diagnostics import CompositionError
    from dracon.lazy import LazyInterpolable, resolve_all_lazy

    if sym._call_depth >= _MAX_CALL_DEPTH:
        raise CompositionError(
            f"maximum call depth ({_MAX_CALL_DEPTH}) exceeded for "
            f"callable template '{sym._name or '?'}'"
            + (f" (defined at {sym._source})" if sym._source else "")
        )

    sym._call_depth += 1
    try:
        node = deepcopy(sym._template_node)
        loader_copy = sym._loader.copy()
        if invocation_context:
            loader_copy.update_context(invocation_context)
        ctx = {**sym._file_context, **kwargs} if sym._file_context else kwargs
        loader_copy.update_context(ctx)
        result = loader_copy.load_composition_result(CompositionResult(root=node))

        if isinstance(result, LazyInterpolable):
            result = resolve_all_lazy(result)

        if sym._has_return:
            from dracon.instructions import _FN_RETURN_KEY
            result = result[_FN_RETURN_KEY]
            if isinstance(result, LazyInterpolable):
                result = resolve_all_lazy(result)

        return result
    except CompositionError:
        raise
    except Exception as e:
        from dracon.diagnostics import DraconError
        ctx_info = f" (defined at {sym._source})" if sym._source else ""
        raise DraconError(
            f"error invoking callable template '{sym._name or '?'}'{ctx_info}: {e}",
            context=sym._source, cause=e,
        ) from e
    finally:
        sym._call_depth -= 1


register_callable_strategy('template', _TemplateStrategy())


# ── factory alias preserving the legacy import surface ──────────────────────


def DraconCallable(template_node, loader, *, source=None, file_context=None,
                   name=None, has_return=False) -> CallableSymbol:
    """Factory: build a template-kind CallableSymbol. Preserved for back-compat."""
    return CallableSymbol.from_template(
        template_node, loader, source=source, file_context=file_context,
        name=name, has_return=has_return,
    )
