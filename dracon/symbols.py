# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset

"""Core typed symbol model for the open vocabulary runtime."""

from __future__ import annotations

import copy
import inspect
import re
import typing
import ast
import builtins
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Literal, Protocol, TypeVar, runtime_checkable

T = TypeVar("T")

_MISSING = object()
MISSING = _MISSING


class SymbolKind(str, Enum):
    VALUE = "value"
    TYPE = "type"
    CALLABLE = "callable"
    TEMPLATE = "template"
    PIPE = "pipe"
    DEFERRED = "deferred"


@dataclass(frozen=True)
class ParamSpec:
    name: str
    required: bool
    default: Any = field(default_factory=lambda: _MISSING)
    annotation: Any = field(default_factory=lambda: _MISSING)
    annotation_name: str | None = None
    docs: str | None = None
    cli_short: str | None = None
    cli_hidden: bool = False


@dataclass(frozen=True)
class ContractSpec:
    kind: str
    name: str
    message: str | None = None


@dataclass(frozen=True)
class SymbolSourceInfo:
    file_path: str | None = None
    line: int | None = None
    column: int | None = None


@dataclass(frozen=True)
class InterfaceSpec:
    kind: SymbolKind
    name: str | None
    params: tuple[ParamSpec, ...] = ()
    contracts: tuple[ContractSpec, ...] = ()
    returns_mapping: bool | None = None
    return_annotation: Any = field(default_factory=lambda: _MISSING)
    return_annotation_name: str | None = None
    source: SymbolSourceInfo | None = None
    docs: str | None = None


@runtime_checkable
class Symbol(Protocol[T]):
    def interface(self) -> InterfaceSpec: ...
    def bind(self, **kwargs: Any) -> Symbol[Any]: ...
    def invoke(self, **kwargs: Any) -> T: ...
    def materialize(self) -> Any: ...
    def represented_type(self) -> type | None: ...


# ── concrete symbols ─────────────────────────────────────────────────────────


class ValueSymbol:
    """Wraps a plain value as a Symbol."""
    __slots__ = ('_value', '_name', '_source')

    def __init__(self, value: Any, *, name: str | None = None, source: SymbolSourceInfo | None = None):
        self._value = value
        self._name = name
        self._source = source

    def interface(self) -> InterfaceSpec:
        return InterfaceSpec(kind=SymbolKind.VALUE, name=self._name, source=self._source)

    def bind(self, **kwargs: Any) -> Symbol[Any]:
        return self

    def invoke(self, **kwargs: Any) -> Any:
        return self._value

    def materialize(self) -> Any:
        return self._value

    def represented_type(self) -> type | None:
        return self._value if isinstance(self._value, type) else None


# ── strategy registry ────────────────────────────────────────────────────────

CallableKind = Literal['plain', 'template', 'partial', 'pipe']


class CallableStrategy(Protocol):
    def interface(self, sym: "CallableSymbol") -> InterfaceSpec: ...
    def invoke(self, sym: "CallableSymbol", kwargs: dict, *, invocation_context: Any = None) -> Any: ...
    def dump(self, sym: "CallableSymbol", representer: Any) -> Any: ...
    def represented_type(self, sym: "CallableSymbol") -> type | None: ...
    def reduce(self, sym: "CallableSymbol") -> Any: ...
    def deepcopy(self, sym: "CallableSymbol", memo: dict) -> "CallableSymbol": ...


_STRATEGIES: dict[str, CallableStrategy] = {}


def register_callable_strategy(kind: str, strategy: CallableStrategy) -> None:
    _STRATEGIES[kind] = strategy


class CallableSymbol:
    """Unified callable Symbol covering plain / template / partial / pipe.

    Use the bare constructor for a plain Python callable or type. Use the
    classmethod factories for the other kinds:

    - ``CallableSymbol(fn)`` / ``CallableSymbol(SomeClass)``  -> plain
    - ``CallableSymbol.from_template(node, loader, ...)``       -> template
    - ``CallableSymbol.from_partial(path, fn, kwargs)``         -> partial
    - ``CallableSymbol.from_pipe(stages, stage_kwargs, ...)``   -> pipe

    Per-kind logic lives in a strategy registry; this class is the dispatcher.
    """

    __slots__ = (
        '_kind', '_name', '_source', '_cached_interface',
        # plain / partial
        '_callable', '_func_path', '_kwargs',
        # template
        '_template_node', '_loader', '_file_context', '_call_depth', '_has_return',
        '_cached_params',
        # pipe
        '_stages', '_stage_kwargs',
    )

    def __init__(
        self, obj: Any = None, *,
        name: str | None = None, source: SymbolSourceInfo | None = None,
        _kind: CallableKind = 'plain',
    ):
        self._kind = _kind
        self._name = name
        self._source = source
        self._cached_interface = None
        self._callable = obj
        self._func_path = None
        self._kwargs = None
        self._template_node = None
        self._loader = None
        self._file_context = None
        self._call_depth = 0
        self._has_return = False
        self._cached_params = None
        self._stages = None
        self._stage_kwargs = None

    # ── factory methods ─────────────────────────────────────────────────

    @classmethod
    def from_template(cls, template_node: Any, loader: Any, *,
                      source: Any = None, file_context: Any = None,
                      name: str | None = None, has_return: bool = False) -> "CallableSymbol":
        sym = cls.__new__(cls)
        sym._kind = 'template'
        sym._name = name
        sym._source = source
        sym._cached_interface = None
        sym._callable = None
        sym._func_path = None
        sym._kwargs = None
        sym._template_node = template_node
        sym._loader = loader
        sym._file_context = file_context
        sym._call_depth = 0
        sym._has_return = has_return
        sym._cached_params = None
        sym._stages = None
        sym._stage_kwargs = None
        return sym

    @classmethod
    def from_partial(cls, func_path: str, func: Any, kwargs: dict) -> "CallableSymbol":
        sym = cls.__new__(cls)
        sym._kind = 'partial'
        sym._name = func_path
        sym._source = None
        sym._cached_interface = None
        sym._callable = func
        sym._func_path = func_path
        sym._kwargs = kwargs
        sym._template_node = None
        sym._loader = None
        sym._file_context = None
        sym._call_depth = 0
        sym._has_return = False
        sym._cached_params = None
        sym._stages = None
        sym._stage_kwargs = None
        return sym

    @classmethod
    def from_pipe(cls, stages: Any, stage_kwargs: Any, *, name: str | None = None) -> "CallableSymbol":
        sym = cls.__new__(cls)
        sym._kind = 'pipe'
        sym._name = name
        sym._source = None
        sym._cached_interface = None
        sym._callable = None
        sym._func_path = None
        sym._kwargs = None
        sym._template_node = None
        sym._loader = None
        sym._file_context = None
        sym._call_depth = 0
        sym._has_return = False
        sym._cached_params = None
        sym._stages = tuple(stages)
        sym._stage_kwargs = tuple(stage_kwargs)
        return sym

    # ── Symbol protocol (dispatched) ────────────────────────────────────

    def interface(self) -> InterfaceSpec:
        if self._cached_interface is not None:
            return self._cached_interface
        self._cached_interface = _STRATEGIES[self._kind].interface(self)
        return self._cached_interface

    def bind(self, **kwargs: Any) -> Symbol[Any]:
        return BoundSymbol(self, **kwargs)

    def invoke(self, kwargs: dict | None = None, *, invocation_context: Any = None, **kw: Any) -> Any:
        # accept legacy positional dict (templates) plus **kwargs (Symbol protocol)
        if kwargs is None:
            kwargs = kw
        elif kw:
            kwargs = {**kwargs, **kw}
        return _STRATEGIES[self._kind].invoke(self, kwargs, invocation_context=invocation_context)

    def materialize(self) -> Any:
        # plain unwraps; everything else is the materialized form
        if self._kind == 'plain':
            return self._callable
        return self

    def represented_type(self) -> type | None:
        return _STRATEGIES[self._kind].represented_type(self)

    # ── invocation as plain callable ────────────────────────────────────

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if self._kind == 'plain':
            return self._callable(*args, **kwargs)
        if self._kind == 'partial':
            merged = {**self._kwargs, **kwargs}
            return self._callable(*args, **merged)
        # template / pipe: positional args not supported, kwargs only
        return self.invoke(**kwargs)

    # ── dump / pickle / deepcopy ────────────────────────────────────────

    def dracon_dump_to_node(self, representer: Any) -> Any:
        return _STRATEGIES[self._kind].dump(self, representer)

    def __reduce__(self) -> Any:
        return _STRATEGIES[self._kind].reduce(self)

    def __setstate__(self, state: dict) -> None:
        # slotted class: pickle/copy default routes state through __dict__; map onto slots
        for k, v in state.items():
            object.__setattr__(self, k, v)

    def __deepcopy__(self, memo: dict) -> "CallableSymbol":
        return _STRATEGIES[self._kind].deepcopy(self, memo)

    def __repr__(self) -> str:
        if self._kind == 'partial':
            return f"CallableSymbol.partial({self._func_path!r}, kwargs={list(self._kwargs or [])})"
        if self._kind == 'template':
            return f"CallableSymbol.template(name={self._name!r})"
        if self._kind == 'pipe':
            return f"CallableSymbol.pipe(name={self._name!r}, stages={len(self._stages or ())})"
        return f"CallableSymbol({self._callable!r})"


# ── built-in plain / partial strategies ──────────────────────────────────────

class _PlainStrategy:
    def interface(self, sym):
        target = sym._callable
        kind = SymbolKind.TYPE if isinstance(target, type) else SymbolKind.CALLABLE
        params = _params_from_model(target) if _is_pydantic_model(target) else _params_from_callable(target)
        ret_anno, ret_name = _return_annotation_from_callable(target)
        return InterfaceSpec(
            kind=kind, name=sym._name, params=params, source=sym._source,
            return_annotation=ret_anno, return_annotation_name=ret_name,
        )

    def invoke(self, sym, kwargs, *, invocation_context=None):
        return sym._callable(**kwargs)

    def dump(self, sym, representer):
        # plain symbols are dumped via their underlying value (e.g. a type)
        return representer.represent_data(sym._callable)

    def represented_type(self, sym):
        return sym._callable if isinstance(sym._callable, type) else None

    def reduce(self, sym):
        # plain wraps a callable; pickling round-trips the callable directly
        return (CallableSymbol, (sym._callable,), {'_name': sym._name})

    def deepcopy(self, sym, memo):
        from dracon.utils import deepcopy as _dc
        clone = CallableSymbol.__new__(CallableSymbol)
        memo[id(sym)] = clone
        clone._kind = 'plain'
        clone._callable = sym._callable
        clone._name = sym._name
        clone._source = sym._source
        clone._cached_interface = sym._cached_interface
        clone._func_path = None
        clone._kwargs = None
        clone._template_node = None
        clone._loader = None
        clone._file_context = None
        clone._call_depth = 0
        clone._has_return = False
        clone._cached_params = None
        clone._stages = None
        clone._stage_kwargs = None
        return clone


class _PartialStrategy:
    def interface(self, sym):
        all_params = _params_from_callable(sym._callable)
        bound_names = frozenset(sym._kwargs)
        remaining = tuple(p for p in all_params if p.name not in bound_names)
        ret_anno, ret_name = _return_annotation_from_callable(sym._callable)
        return InterfaceSpec(
            kind=SymbolKind.CALLABLE, name=sym._func_path, params=remaining,
            return_annotation=ret_anno, return_annotation_name=ret_name,
        )

    def invoke(self, sym, kwargs, *, invocation_context=None):
        merged = {**sym._kwargs, **kwargs}
        return sym._callable(**merged)

    def dump(self, sym, representer):
        tag = f'!fn:{sym._func_path}'
        if sym._kwargs:
            return representer.represent_mapping(tag, sym._kwargs)
        return representer.represent_scalar(tag, '')

    def represented_type(self, sym):
        return sym._callable if isinstance(sym._callable, type) else None

    def reduce(self, sym):
        return (_reconstruct_partial, (sym._func_path, sym._kwargs))

    def deepcopy(self, sym, memo):
        from dracon.utils import deepcopy as _dc
        clone = CallableSymbol.__new__(CallableSymbol)
        memo[id(sym)] = clone
        clone._kind = 'partial'
        clone._name = sym._name
        clone._source = None
        clone._cached_interface = sym._cached_interface
        clone._callable = sym._callable
        clone._func_path = sym._func_path
        clone._kwargs = _dc(sym._kwargs, memo)
        clone._template_node = None
        clone._loader = None
        clone._file_context = None
        clone._call_depth = 0
        clone._has_return = False
        clone._cached_params = None
        clone._stages = None
        clone._stage_kwargs = None
        return clone


def _reconstruct_partial(func_path, kwargs):
    """Pickle reconstruction: re-imports the function from its dotted path."""
    from typing import Any
    from dracon.draconstructor import resolve_type
    if func_path.startswith('py:'):
        from dracon.composer import CompositionResult
        from dracon.include import parse_include_str
        from dracon.keypath import KeyPath
        from dracon.loaders.py import PyValueNode, read_from_py

        components = parse_include_str(func_path)
        _scheme, path = components.main_path.split(':', 1)
        raw, _ctx = read_from_py(path)
        comp = CompositionResult(root=raw)
        if components.key_path:
            comp = comp.rerooted(KeyPath(components.key_path))
        root = comp.root
        if not isinstance(root, PyValueNode):
            raise ValueError(f"cannot unpickle CallableSymbol partial: '{func_path}' is not a Python symbol")
        return CallableSymbol.from_partial(func_path, root.py_value, kwargs)
    if '.' not in func_path:
        raise ValueError(
            f"cannot unpickle CallableSymbol partial with context-only name '{func_path}' "
            f"-- function must be importable via dotted path"
        )
    func = resolve_type(f'!{func_path}')
    if func is Any:
        raise ValueError(f"cannot unpickle CallableSymbol partial: '{func_path}' is not importable")
    return CallableSymbol.from_partial(func_path, func, kwargs)


register_callable_strategy('plain', _PlainStrategy())
register_callable_strategy('partial', _PartialStrategy())


class BoundSymbol:
    """A symbol with pre-filled kwargs. Binding a bound symbol merges kwargs."""
    __slots__ = ('_inner', '_kwargs')

    def __repr__(self) -> str:
        name = self._inner.interface().name or '?'
        return f"BoundSymbol({name!r}, kwargs={list(self._kwargs)})"

    def __init__(self, inner: Symbol[Any], **kwargs: Any):
        if isinstance(inner, BoundSymbol):
            self._inner = inner._inner
            self._kwargs = {**inner._kwargs, **kwargs}
        else:
            self._inner = inner
            self._kwargs = dict(kwargs)

    def interface(self) -> InterfaceSpec:
        base = self._inner.interface()
        bound_names = frozenset(self._kwargs)
        remaining = tuple(p for p in base.params if p.name not in bound_names)
        return InterfaceSpec(
            kind=base.kind, name=base.name, params=remaining,
            contracts=base.contracts, returns_mapping=base.returns_mapping,
            return_annotation=base.return_annotation,
            return_annotation_name=base.return_annotation_name,
            source=base.source, docs=base.docs,
        )

    def bind(self, **kwargs: Any) -> Symbol[Any]:
        return BoundSymbol(self, **kwargs)

    def invoke(self, **kwargs: Any) -> Any:
        merged = {**self._kwargs, **kwargs}
        return self._inner.invoke(**merged)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        merged = {**self._kwargs, **kwargs}
        inner = self._inner.materialize()
        return inner(*args, **merged)

    def materialize(self) -> Any:
        if self._kwargs:
            return self  # bound symbol with kwargs is the materialized form
        return self._inner.materialize()

    def represented_type(self) -> type | None:
        return None  # bound symbols carry kwargs, not type identity

    def dracon_dump_to_node(self, representer: Any) -> Any:
        inner_iface = self._inner.interface()
        tag = f'!fn:{inner_iface.name}' if inner_iface.name else '!fn'
        if self._kwargs:
            return representer.represent_mapping(tag, self._kwargs)
        return representer.represent_scalar(tag, '')


# ── helpers ──────────────────────────────────────────────────────────────────

def _params_from_callable(obj: Any) -> tuple[ParamSpec, ...]:
    """Extract ParamSpec tuple from a callable's signature.

    Preserves Python annotations: real type objects in `annotation`,
    a stable string form in `annotation_name`. String forward refs
    are resolved when possible (modules with `from __future__ import
    annotations`); unresolvable strings stay as strings in `annotation`.
    """
    sig = _signature(obj)
    if sig is None:
        return ()
    docs_map = _docstring_param_docs(obj)
    params = []
    for name, p in sig.parameters.items():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        anno = p.annotation
        if anno is p.empty:
            anno_obj: Any = _MISSING
            anno_name: str | None = None
        else:
            anno_obj = anno
            anno_name = format_annotation(anno)
        docs = docs_map.get(name)
        if p.default is p.empty:
            params.append(ParamSpec(
                name=name, required=True,
                annotation=anno_obj, annotation_name=anno_name, docs=docs,
            ))
        else:
            default_val = copy.deepcopy(p.default) if isinstance(p.default, (list, dict, set)) else p.default
            params.append(ParamSpec(
                name=name, required=False, default=default_val,
                annotation=anno_obj, annotation_name=anno_name, docs=docs,
            ))
    return tuple(params)


_NUMPY_HEADER_RE = re.compile(r'^[ \t]*(Parameters|Args|Arguments)\s*[:\n]', re.MULTILINE)
_GOOGLE_PARAM_RE = re.compile(r'^[ \t]*([A-Za-z_]\w*)\s*(?:\([^)]*\))?\s*:\s*(.*)$')


def _docstring_param_docs(obj: Any) -> dict[str, str]:
    """Per-parameter help text harvested from numpy- or google-style docstrings.

    Numpy: ``name : type`` header line followed by indented description.
    Google: ``name (type): description`` on one line, optionally continued.
    Returns ``{}`` on no docstring or unrecognised shape.
    """
    doc = inspect.getdoc(obj) or ""
    match = _NUMPY_HEADER_RE.search(doc)
    if not match:
        return {}
    body = doc[match.end():]
    # numpy puts a `----` underline below the header; skip it if present
    lines = body.lstrip('\n').splitlines()
    if lines and set(lines[0].strip()) <= {'-'}:
        lines = lines[1:]
    out: dict[str, str] = {}
    current: str | None = None
    desc: list[str] = []
    base_indent: int | None = None
    for raw in lines:
        if not raw.strip():
            if current is not None and desc:
                desc.append('')
            continue
        indent = len(raw) - len(raw.lstrip())
        if base_indent is None:
            base_indent = indent
        # dedent ends the parameters block
        if indent < base_indent:
            break
        m = _GOOGLE_PARAM_RE.match(raw)
        if m and indent == base_indent:
            if current is not None:
                out[current] = '\n'.join(desc).strip()
            current = m.group(1)
            tail = m.group(2).strip()
            desc = [tail] if tail else []
        elif current is not None:
            desc.append(raw.strip())
    if current is not None:
        out[current] = '\n'.join(desc).strip()
    return {k: v for k, v in out.items() if v}


def register_template(
    fn: Callable | type,
    *,
    name: str | None = None,
    loader: Any | None = None,
    allow_extras: bool = False,
) -> CallableSymbol:
    """Register a Python callable as a typed `!fn:`-invocable symbol.

    Equivalent to ``loader.context[name] = fn`` (which already builds a typed
    ``CallableSymbol``), with three policy adds: ``*args`` is rejected,
    ``**kwargs`` is opt-in via ``allow_extras=True``, and ``name`` overrides
    the callable's ``__name__``. Re-registration replaces the prior entry.
    """
    sig = _signature(fn)
    if sig is None:
        raise ValueError(f"register_template: cannot introspect {fn!r}")
    for p in sig.parameters.values():
        if p.kind is inspect.Parameter.VAR_POSITIONAL:
            raise ValueError(
                f"register_template: {fn!r} has *args; templates only support kwargs"
            )
        if p.kind is inspect.Parameter.VAR_KEYWORD and not allow_extras:
            raise ValueError(
                f"register_template: {fn!r} has **kwargs; "
                f"pass allow_extras=True to permit unknown kwargs"
            )
    effective_name = name or getattr(fn, '__name__', None)
    if not effective_name:
        raise ValueError(f"register_template: cannot derive a name from {fn!r}")
    try:
        src_file = inspect.getsourcefile(fn)
        src_line = inspect.getsourcelines(fn)[1]
        source = SymbolSourceInfo(file_path=src_file, line=src_line)
    except (TypeError, OSError):
        source = None
    sym = CallableSymbol(fn, name=effective_name, source=source)
    if loader is not None:
        from dracon.symbol_table import SymbolEntry
        loader.context.define(SymbolEntry(name=effective_name, symbol=sym, canonical=False))
    return sym


def _is_pydantic_model(obj: Any) -> bool:
    if not isinstance(obj, type):
        return False
    try:
        from pydantic import BaseModel
    except ImportError:
        return False
    return issubclass(obj, BaseModel) and obj is not BaseModel


def _params_from_model(model_cls: Any) -> tuple[ParamSpec, ...]:
    """Walk a pydantic model's fields; surface `Arg(...)` metadata onto ParamSpec.

    Field annotation + default flow into `annotation` / `default`; `Arg(short=...)`
    / `Arg(help=...)` / `Arg(hidden=...)` flow into `cli_short` / `docs` / `cli_hidden`.
    """
    from pydantic_core import PydanticUndefined
    from dracon.cli_param import CliParam

    out: list[ParamSpec] = []
    for fname, finfo in model_cls.model_fields.items():
        anno = finfo.annotation
        anno_name = format_annotation(anno) if anno is not None else None
        if finfo.default is PydanticUndefined and finfo.default_factory is None:
            default: Any = _MISSING
            required = True
        else:
            default = finfo.default if finfo.default is not PydanticUndefined else _MISSING
            required = False
        cli_short: str | None = None
        cli_hidden = False
        docs: str | None = finfo.description
        for m in finfo.metadata:
            if isinstance(m, CliParam):
                if m.short:
                    cli_short = m.short
                if m.hidden:
                    cli_hidden = True
                if m.help:
                    docs = m.help
                break
        out.append(ParamSpec(
            name=fname, required=required, default=default,
            annotation=anno if anno is not None else _MISSING,
            annotation_name=anno_name, docs=docs,
            cli_short=cli_short, cli_hidden=cli_hidden,
        ))
    return tuple(out)


def _return_annotation_from_callable(obj: Any) -> tuple[Any, str | None]:
    """Return (annotation_obj, annotation_name) for a callable's return type."""
    sig = _signature(obj)
    if sig is None:
        return _MISSING, None
    ret = sig.return_annotation
    if ret is sig.empty:
        return _MISSING, None
    return ret, format_annotation(ret)


def _signature(obj: Any) -> "inspect.Signature | None":
    """`inspect.signature` with annotation evaluation enabled.

    When the source module uses `from __future__ import annotations`,
    `inspect.signature` returns string annotations by default. `eval_str=True`
    resolves those strings to real objects when names are available;
    falls back to plain signature() if evaluation fails.
    """
    try:
        return inspect.signature(obj, eval_str=True)
    except (ValueError, TypeError):
        pass
    except (NameError, AttributeError, SyntaxError):
        pass
    try:
        return inspect.signature(obj)
    except (ValueError, TypeError):
        return None


def format_annotation(anno: Any) -> str:
    """Stable string form of a Python annotation.

    Used for ParamSpec.annotation_name and JSON output. Bare types render
    as `Name`; generics recurse through `__origin__` / `__args__` so
    `list[Event]` stays readable instead of leaking module paths.
    """
    if anno is _MISSING:
        return ''
    if anno is None or anno is type(None):
        return 'None'
    if isinstance(anno, str):
        return anno
    if isinstance(anno, type):
        return getattr(anno, '__name__', None) or repr(anno)
    origin = getattr(anno, '__origin__', None)
    args = getattr(anno, '__args__', None)
    if origin is not None and args is not None:
        origin_name = format_annotation(origin)
        if origin is typing.Union:  # render as "X | Y"
            return ' | '.join(format_annotation(a) for a in args)
        inner = ', '.join(format_annotation(a) for a in args)
        return f"{origin_name}[{inner}]"
    try:
        s = repr(anno)
    except Exception:
        return str(anno)
    if s.startswith('typing.'):
        return s[len('typing.'):]
    return s


def resolve_annotation(name: str | None, scope: Any) -> Any:
    """Look up a type-annotation name in a symbol scope.

    `scope` is anything mapping-like (a `SymbolTable` or plain dict). Tries
    the exact string first, then falls back to the bare class name with
    subscripts/quotes stripped -- enough for `list[Event]` to resolve to
    `Event`. Returns `MISSING` when nothing matches; callers keep the
    string form on `annotation_name`.
    """
    if not name:
        return _MISSING
    name = name.strip()
    if not name:
        return _MISSING
    for candidate in (name, name.rstrip("'\"")):
        if scope is not None and candidate and candidate in scope:
            try:
                return scope[candidate]
            except Exception:
                pass
    resolved = _resolve_annotation_expr(name, scope)
    if resolved is not _MISSING:
        return resolved
    base_name = name.split('[', 1)[0].strip()
    if base_name and scope is not None and base_name in scope:
        try:
            return scope[base_name]
        except Exception:
            pass
    return _MISSING


def _resolve_annotation_expr(expr: str, scope: Any) -> Any:
    try:
        parsed = ast.parse(expr, mode='eval')
    except SyntaxError:
        return _MISSING
    return _resolve_annotation_ast(parsed.body, scope)


def _lookup_annotation_name(name: str, scope: Any) -> Any:
    if name == 'None':
        return type(None)
    if name == 'typing':
        return typing
    if scope is not None and name in scope:
        try:
            return scope[name]
        except Exception:
            pass
    if hasattr(builtins, name):
        return getattr(builtins, name)
    if hasattr(typing, name):
        return getattr(typing, name)
    return _MISSING


def _resolve_annotation_ast(node: ast.AST, scope: Any) -> Any:
    if isinstance(node, ast.Name):
        return _lookup_annotation_name(node.id, scope)
    if isinstance(node, ast.Constant):
        if node.value is None:
            return type(None)
        if isinstance(node.value, str):
            return _lookup_annotation_name(node.value, scope)
        return _MISSING
    if isinstance(node, ast.Attribute):
        base = _resolve_annotation_ast(node.value, scope)
        if base is _MISSING:
            return _MISSING
        return getattr(base, node.attr, _MISSING)
    if isinstance(node, ast.Tuple):
        values = tuple(_resolve_annotation_ast(elt, scope) for elt in node.elts)
        if any(value is _MISSING for value in values):
            return _MISSING
        return values
    if isinstance(node, ast.Subscript):
        origin = _resolve_annotation_ast(node.value, scope)
        args = _resolve_annotation_ast(node.slice, scope)
        if origin is _MISSING or args is _MISSING:
            return _MISSING
        try:
            return origin[args]
        except Exception:
            return _MISSING
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left = _resolve_annotation_ast(node.left, scope)
        right = _resolve_annotation_ast(node.right, scope)
        if left is _MISSING or right is _MISSING:
            return _MISSING
        try:
            return left | right
        except Exception:
            return _MISSING
    return _MISSING


def auto_symbol(value: Any, *, name: str | None = None, source: SymbolSourceInfo | None = None) -> Symbol[Any]:
    """Create the appropriate Symbol subclass for a value.

    DraconCallable, DraconPartial, DraconPipe, DeferredNode instances
    implement Symbol and are returned as-is. Types/classes are wrapped
    in CallableSymbol (even if they have protocol methods, since calling
    .materialize() on the class itself rather than an instance would fail).
    Plain callables get wrapped in CallableSymbol.
    Everything else becomes ValueSymbol.
    """
    # types/classes always go through CallableSymbol, even if the class
    # structurally matches the Symbol protocol (its methods are unbound)
    if isinstance(value, type):
        return CallableSymbol(value, name=name, source=source)
    # instances that already satisfy the protocol (DraconCallable, DraconPartial, DraconPipe, DeferredNode, etc.)
    if isinstance(value, (ValueSymbol, CallableSymbol, BoundSymbol)):
        return value
    if (hasattr(value, 'interface') and hasattr(value, 'bind')
        and hasattr(value, 'invoke') and hasattr(value, 'materialize')
        and hasattr(value, 'represented_type')):
        return value
    if callable(value):
        return CallableSymbol(value, name=name, source=source)
    return ValueSymbol(value, name=name, source=source)
