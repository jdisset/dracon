# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""DraconCallable: YAML template wrapped as a callable, created by !fn.

Implements the Symbol protocol: interface() / bind() / invoke() / materialize().
"""

from __future__ import annotations

from dracon.utils import deepcopy

_MAX_CALL_DEPTH = 32


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
        from dracon.symbols import InterfaceSpec, SymbolKind, ParamSpec, SymbolSourceInfo
        params = self._scan_params()
        source = None
        if self._source:
            source = SymbolSourceInfo(
                file_path=getattr(self._source, 'file_path', None),
                line=getattr(self._source, 'line', None),
            )
        self._cached_interface = InterfaceSpec(
            kind=SymbolKind.TEMPLATE, name=self._name,
            params=params, source=source,
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

    # ── param scanning (owns interface extraction) ───────────────────────

    def _scan_params(self):
        """Walk template node for !require/!set_default. Cached."""
        if self._cached_params is not None:
            req, opt = self._cached_params
        else:
            req, opt = self._do_scan_params()
            self._cached_params = (req, opt)
        from dracon.symbols import ParamSpec
        return tuple(
            [ParamSpec(name=n, required=True) for n in req]
            + [ParamSpec(name=n, required=False) for n in opt]
        )

    def _do_scan_params(self):
        from dracon.composer import DraconMappingNode
        from dracon.instructions import match_instruct, Require, SetDefault
        node = self._template_node
        if not isinstance(node, DraconMappingNode):
            return [], []
        required, optional = [], []
        for k_node, v_node in node.value:
            tag = getattr(k_node, 'tag', None)
            if not tag:
                continue
            inst = match_instruct(tag)
            if inst is None:
                continue
            name = getattr(k_node, 'value', None)
            if isinstance(inst, Require):
                required.append(name)
            elif isinstance(inst, SetDefault):
                optional.append(name)
        return required, optional

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
