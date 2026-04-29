"""Python symbol loader for the `!include py:...` scheme.

This loader unifies Python symbol resolution under dracon's include machinery.
The same `!include scheme:path[@selector]` grammar that works for YAML sources
(`file:`, `pkg:`, `cascade:`, ...) now works for Python sources too.

Path grammar (after the `py:` prefix is stripped):

- ``dotted.path`` — imported via ``importlib.import_module``. If the full path
  isn't importable as a module, the last segment is treated as an attribute of
  the prefix (same fallback used by ``resolve_type``).
- ``/abs/file.py`` or ``./rel/file.py`` (or ``$VAR/file.py`` after variable
  substitution done by the outer include machinery) — loaded via
  ``importlib.util.spec_from_file_location`` with no sys.path mutation.

Selector form (``@Name``) is stripped by the outer include layer and applied
via composition-result rerooting — so this loader always returns a namespace
mapping of public names (underscore-prefixed names filtered out; ``__all__``
honoured when present). When no ``@`` is present and the dotted path resolves
to a single symbol (not a module), that symbol is returned directly; this
keeps ``!include py:math.sqrt`` terse for the common single-binding case.

Construction of a py-sourced node is handled by the constructor via the
``!__py__`` tag on ``PyValueNode``, which carries the real Python object in
``.py_value``.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
import types
from pathlib import Path
from typing import Any, Iterable

from dracon.nodes import DraconScalarNode, DraconMappingNode


PY_VALUE_TAG = '!__py__'


class PyValueNode(DraconScalarNode):
    """Scalar node carrying a direct Python object (not a YAML string).

    The ``value`` field holds a short human-readable label (for diagnostics);
    the real object is in ``.py_value``. The constructor recognises this
    node's tag (``!__py__``) and returns ``.py_value`` verbatim.
    """

    def __init__(self, py_value: Any, label: str = '', **kw):
        super().__init__(tag=PY_VALUE_TAG, value=label or _short_repr(py_value), **kw)
        self.py_value = py_value

    def __getstate__(self):
        state = super().__getstate__()
        state['py_value'] = self.py_value
        return state

    def __setstate__(self, state):
        self.py_value = state.pop('py_value', None)
        super().__setstate__(state)


def _short_repr(value: Any) -> str:
    name = getattr(value, '__qualname__', None) or getattr(value, '__name__', None)
    if name:
        mod = getattr(value, '__module__', None)
        return f"{mod}.{name}" if mod else name
    return type(value).__name__


def _looks_like_file_path(ref: str) -> bool:
    """Heuristic: does this look like a filesystem path rather than a dotted name?"""
    if ref.endswith('.py') or ref.endswith('.pyw'):
        return True
    if ref.startswith(('/', '~', '.')) or ref.startswith('./') or ref.startswith('../'):
        return True
    # windows drive letter (C:\ etc.) — unlikely to clash with a module name
    if len(ref) > 2 and ref[1] == ':' and ref[2] in ('/', '\\'):
        return True
    return False


def _public_names(namespace_obj: Any) -> Iterable[str]:
    """Public names for a module-like object, honouring __all__ when present."""
    explicit = getattr(namespace_obj, '__all__', None)
    if explicit is not None:
        return list(explicit)
    return [n for n in dir(namespace_obj) if not n.startswith('_')]


def _module_cache_key(p: Path) -> str:
    # stable key per absolute path so re-includes hit the cache
    return f"_dracon_py_file_{abs(hash(str(p)))}"


def _load_module_from_file(file_path: str) -> types.ModuleType:
    p = Path(file_path).expanduser()
    if not p.is_absolute():
        p = p.resolve()
    if not p.exists():
        raise FileNotFoundError(f"py: file not found: {file_path}")

    cache_key = _module_cache_key(p)
    cached = sys.modules.get(cache_key)
    if cached is not None:
        return cached

    spec = importlib.util.spec_from_file_location(cache_key, p)
    if spec is None or spec.loader is None:
        raise ImportError(f"py: cannot create import spec for {p}")
    module = importlib.util.module_from_spec(spec)
    # register before exec so circular imports in the file can reference it
    sys.modules[cache_key] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(cache_key, None)
        raise
    return module


def _resolve_dotted(ref: str) -> Any:
    """Resolve a dotted path either as a full module or as module.attr.

    Returns the resolved object. Raises ImportError / AttributeError on miss.
    """
    try:
        return importlib.import_module(ref)
    except ImportError:
        if '.' not in ref:
            raise
        parent_path, name = ref.rsplit('.', 1)
        parent = importlib.import_module(parent_path)
        if not hasattr(parent, name):
            raise ImportError(
                f"py: module '{parent_path}' has no attribute '{name}'"
            )
        return getattr(parent, name)


def resolve_py_reference(ref: str) -> Any:
    """Resolve a `py:` reference to its Python object.

    This is the single source of truth for how `py:` references are turned
    into Python values. Used both by the include loader and by the `!fn:`
    scheme-URI handler (so both paths stay consistent).
    """
    if _looks_like_file_path(ref):
        return _load_module_from_file(ref)
    return _resolve_dotted(ref)


def _namespace_mapping_node(namespace_obj: Any) -> DraconMappingNode:
    pairs = []
    for name in _public_names(namespace_obj):
        try:
            value = getattr(namespace_obj, name)
        except AttributeError:
            continue
        key_node = DraconScalarNode(tag='tag:yaml.org,2002:str', value=name)
        pairs.append((key_node, PyValueNode(value, label=name)))
    return DraconMappingNode(tag='tag:yaml.org,2002:map', value=pairs)


def read_from_py(path: str, node=None, draconloader=None, **_) -> tuple[Any, dict]:
    """Entry point registered as the ``py`` scheme.

    Returns ``(node, context)`` where ``node`` is either a mapping of public
    names (when ``path`` resolves to a module) or a single :class:`PyValueNode`
    (when ``path`` resolves to a specific attribute via the dotted-fallback).
    """
    obj = resolve_py_reference(path)
    if isinstance(obj, types.ModuleType):
        return _namespace_mapping_node(obj), {}
    # single-symbol resolution: !include py:math.sqrt — path pointed straight
    # at a non-module attribute.
    return PyValueNode(obj, label=path), {}
