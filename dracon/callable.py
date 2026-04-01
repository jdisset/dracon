# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""DraconCallable: YAML template wrapped as a callable, created by !fn."""

from dracon.utils import deepcopy

_MAX_CALL_DEPTH = 32


class DraconCallable:
    """Callable YAML template, created by !fn, invoked via tag or ${...}.

    Each invocation deepcopies the template node, injects kwargs as context,
    and runs the full composition + construction pipeline on an isolated
    loader copy. The template itself is never mutated.
    """

    __slots__ = ('_template_node', '_loader', '_source', '_name', '_file_context',
                 '_call_depth', '_cached_params', '_has_return')

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

    def __call__(self, **kwargs):
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
            # file_context first (DIR, FILE_PATH, etc.), then kwargs override
            ctx = {**self._file_context, **kwargs} if self._file_context else kwargs
            loader_copy.update_context(ctx)
            result = loader_copy.load_composition_result(CompositionResult(root=node))

            # auto-resolve LazyInterpolable (scalar templates return these)
            if isinstance(result, LazyInterpolable):
                result = resolve_all_lazy(result)

            # extract !fn return value if present
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
        # template and loader are shared, not copied.
        # each __call__ already deepcopies the template node.
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
        return clone

    def __repr__(self):
        return f"DraconCallable(name={self._name!r})"
