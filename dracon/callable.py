# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""DraconCallable: YAML template wrapped as a callable, created by !fn.

Implements the Symbol protocol: interface() / bind() / invoke() / materialize().
"""

from __future__ import annotations

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
    from dracon.symbols import ParamSpec, MISSING, resolve_annotation
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
            # mapping body: pull `help` if present
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


class DraconCallable:
    """Callable YAML template, created by !fn, invoked via tag or ${...}.

    Each invocation deepcopies the template node, injects kwargs as context,
    and runs the full composition + construction pipeline on an isolated
    loader copy. The template itself is never mutated.

    Implements the Symbol protocol.
    """

    __slots__ = ('_template_node', '_loader', '_source', '_name', '_file_context',
                 '_call_depth', '_cached_params', '_has_return', '_cached_interface')

    def __init__(self, template_node, loader, source=None, file_context=None,
                 name=None, has_return=False):
        self._template_node = template_node
        self._loader = loader
        self._source = source
        self._file_context = file_context
        self._name = name
        self._call_depth = 0
        self._cached_params = None
        self._has_return = has_return
        self._cached_interface = None

    # ── Symbol protocol ──────────────────────────────────────────────────

    def interface(self):
        if self._cached_interface is not None:
            return self._cached_interface
        from dracon.symbols import (
            InterfaceSpec, SymbolKind, SymbolSourceInfo, MISSING, resolve_annotation,
        )
        if self._cached_params is not None:
            params, ret_anno_name = self._cached_params
        else:
            params, ret_anno_name = _scan_template_interface(self._template_node, self._loader)
            self._cached_params = (params, ret_anno_name)
        source = None
        if self._source:
            source = SymbolSourceInfo(
                file_path=getattr(self._source, 'file_path', None),
                line=getattr(self._source, 'line', None),
            )
        scope = getattr(self._loader, 'context', None) if self._loader else None
        ret_anno_obj = resolve_annotation(ret_anno_name, scope) if ret_anno_name else MISSING
        self._cached_interface = InterfaceSpec(
            kind=SymbolKind.TEMPLATE, name=self._name,
            params=params, source=source,
            return_annotation=ret_anno_obj,
            return_annotation_name=ret_anno_name,
        )
        return self._cached_interface

    def bind(self, **kwargs):
        from dracon.symbols import BoundSymbol
        return BoundSymbol(self, **kwargs)

    def invoke(self, kwargs=None, *, invocation_context=None, **kw):
        """Invoke with explicit invocation context from the calling scope.

        Accepts either positional dict (legacy) or **kwargs (Symbol protocol).
        invocation_context, when provided, is merged into the loader copy
        before file_context and kwargs, so that propagated callables/types
        from the invocation site are visible during nested tag resolution.
        """
        if kwargs is None:
            kwargs = kw
        elif kw:
            kwargs = {**kwargs, **kw}
        return self._run(kwargs, invocation_context=invocation_context)

    def materialize(self):
        return self

    def represented_type(self):
        return None  # templates have no single underlying Python type

    def dracon_dump_to_node(self, representer):
        # copy the template body so the representer sees fresh identities
        # and loaded callables don't recurse through back-references.
        from dracon.composer import fast_copy_node_tree
        inner = representer.represent_data(fast_copy_node_tree(self._template_node))
        inner.tag = f'!fn:{self._name}' if self._name else '!fn'
        return inner

    # ── internal ─────────────────────────────────────────────────────────

    def __call__(self, **kwargs):
        return self._run(kwargs)

    def _run(self, kwargs, invocation_context=None):
        from dracon.composer import CompositionResult
        from dracon.diagnostics import CompositionError
        from dracon.lazy import LazyInterpolable, resolve_all_lazy

        if self._call_depth >= _MAX_CALL_DEPTH:
            raise CompositionError(
                f"maximum call depth ({_MAX_CALL_DEPTH}) exceeded for "
                f"callable template '{self._name or '?'}'"
                + (f" (defined at {self._source})" if self._source else "")
            )

        self._call_depth += 1
        try:
            node = deepcopy(self._template_node)
            loader_copy = self._loader.copy()
            if invocation_context:
                loader_copy.update_context(invocation_context)
            ctx = {**self._file_context, **kwargs} if self._file_context else kwargs
            loader_copy.update_context(ctx)
            result = loader_copy.load_composition_result(CompositionResult(root=node))

            if isinstance(result, LazyInterpolable):
                result = resolve_all_lazy(result)

            if self._has_return:
                from dracon.instructions import _FN_RETURN_KEY
                result = result[_FN_RETURN_KEY]
                if isinstance(result, LazyInterpolable):
                    result = resolve_all_lazy(result)

            return result
        except CompositionError:
            raise
        except Exception as e:
            from dracon.diagnostics import DraconError
            ctx_info = f" (defined at {self._source})" if self._source else ""
            raise DraconError(
                f"error invoking callable template '{self._name or '?'}'{ctx_info}: {e}",
                context=self._source, cause=e,
            ) from e
        finally:
            self._call_depth -= 1

    def __deepcopy__(self, memo):
        clone = DraconCallable.__new__(DraconCallable)
        memo[id(self)] = clone
        clone._template_node = self._template_node
        clone._loader = self._loader
        clone._source = self._source
        clone._file_context = self._file_context
        clone._name = self._name
        clone._call_depth = 0
        clone._cached_params = self._cached_params
        clone._has_return = self._has_return
        clone._cached_interface = self._cached_interface
        return clone

    def __repr__(self):
        return f"DraconCallable(name={self._name!r})"
