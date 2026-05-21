# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset

"""Predicate-keyed-mapping dialects.

Two related shapes share one tag + one registry:

- *Inherit-mode* (empty `input_params`): keys with shared semantics flow
  into descendants at compose time. Built-in `strip_suffix` covers the
  biocomp `*_params` cascade.
- *Select-mode* (non-empty `input_params`): predicate keys dispatch on a
  runtime value (CSS-shaped configs, route tables). Composition emits a
  `CallableSymbol` of kind ``'match'`` whose ``invoke(**input_params)``
  collects matching keys, sorts by specificity, and merges.

Strategies register via `register_cascade_strategy(strategy)`; the
`!cascade:NAME` instruction in `dracon/instructions.py` dispatches.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Any

from dracon.utils import dict_like, deepcopy
from dracon.merge import MergeKey, merged, cached_merge_key


# ── inherit-mode helper (step 06) ───────────────────────────────────────────


def cascade_inherit(tree: Any, *, key_normalize: Callable[[str], Optional[str]]) -> Any:
    """Apply inherit-mode cascade: ancestor mappings with the same normalized key
    flow into descendant mappings. Returns a new tree, never mutates input."""
    op = MergeKey(raw='<<{+<}[~<]', key_normalize=key_normalize)
    return _recurse(deepcopy(tree), ancestors={}, op=op, norm=key_normalize)


def _norm_str(key, norm):
    return norm(key) if isinstance(key, str) else None


def _project(d, exclude_norm, norm):
    # recursively strip same-norm children to break self-cycles on inheritance
    out = {}
    for k, v in d.items():
        if _norm_str(k, norm) == exclude_norm:
            continue
        out[k] = _project(v, exclude_norm, norm) if dict_like(v) else v
    return out


def _recurse(node, ancestors: dict, op: MergeKey, norm) -> Any:
    if not dict_like(node):
        return node

    # siblings: descendants inherit from same-level mappings too
    siblings = {nk: node[k] for k in node.keys() if dict_like(node[k])
                and (nk := _norm_str(k, norm)) is not None}

    out = type(node)() if hasattr(node, 'copy') else {}
    for k, v in node.items():
        nk = _norm_str(k, norm)
        if dict_like(v):
            scope = {**ancestors, **siblings}
            if nk is not None and nk in ancestors:
                v = merged(_project(ancestors[nk], nk, norm), v, op)
                scope.pop(nk, None)  # consumed: descendants don't re-merge against same-norm ancestor
            elif nk is not None:
                scope[nk] = v
            v = _recurse(v, scope, op, norm)
        out[k] = v
    return out


# ── strategy record + registry ──────────────────────────────────────────────


@dataclass(frozen=True)
class CascadeStrategy:
    """A predicate-keyed-mapping dialect.

    `input_params` discriminates mode. Empty -> inherit (compose-time tree
    transform via `apply`); non-empty -> select (runtime dispatch via
    `parse` + `matches` + `specificity` + `merge`).

    Select-mode tags implicitly open a `!live` scope for each `input_params`
    name, so `${name.x}` leaves inside the body stay callable against the
    per-invocation binding.
    """
    name: str
    input_params: tuple[str, ...] = ()

    # inherit
    apply: Optional[Callable[[Any], Any]] = None
    # select
    parse: Optional[Callable[[str], Any]] = None
    matches: Optional[Callable[[Any, Any], bool]] = None
    specificity: Optional[Callable[[Any], tuple]] = None
    merge: Optional[Callable[[Any, Any], Any]] = None
    recursive: bool = True

    def is_inherit(self) -> bool:
        return not self.input_params


_CASCADE_STRATEGIES: dict[str, CascadeStrategy] = {}


def register_cascade_strategy(strategy: CascadeStrategy) -> None:
    """Register a dialect under its `strategy.name`. Last write wins."""
    _CASCADE_STRATEGIES[strategy.name] = strategy


def get_cascade_strategy(name: str) -> CascadeStrategy:
    """Resolve a registered dialect; raises KeyError with the known list."""
    if name not in _CASCADE_STRATEGIES:
        raise KeyError(
            f"unknown cascade strategy: {name!r}. "
            f"Registered: {sorted(_CASCADE_STRATEGIES)}"
        )
    return _CASCADE_STRATEGIES[name]


# ── parametric resolution ───────────────────────────────────────────────────


_PARAMETRIC_BUILDERS: dict[str, Callable[[str], CascadeStrategy]] = {}


def _register_parametric(base_name: str, builder: Callable[[str], CascadeStrategy]) -> None:
    _PARAMETRIC_BUILDERS[base_name] = builder


def resolve_cascade_strategy(name: str, arg: Optional[str]) -> CascadeStrategy:
    """Look up `NAME` or `NAME(ARG)`. Falls back to a registered parametric builder."""
    if arg is None:
        return get_cascade_strategy(name)
    full = f"{name}:{arg}"
    if full in _CASCADE_STRATEGIES:
        return _CASCADE_STRATEGIES[full]
    builder = _PARAMETRIC_BUILDERS.get(name)
    if builder is None:
        raise KeyError(
            f"unknown parametric cascade strategy: {name!r}. "
            f"Registered builders: {sorted(_PARAMETRIC_BUILDERS)}"
        )
    strategy = builder(arg)
    _CASCADE_STRATEGIES[strategy.name] = strategy
    return strategy


# ── built-in: strip_suffix(SUFFIX) ──────────────────────────────────────────


def _build_strip_suffix(suffix: str) -> CascadeStrategy:
    token = f"_{suffix}" if not suffix.startswith('_') else suffix
    def _norm(k):
        if isinstance(k, str) and k.endswith(token):
            return k.removesuffix(token) or None
        return None
    return CascadeStrategy(
        name=f"strip_suffix:{suffix}",
        apply=lambda tree: cascade_inherit(tree, key_normalize=_norm),
    )


_register_parametric('strip_suffix', _build_strip_suffix)


# ── select-mode `match` strategy ────────────────────────────────────────────


def _cascade_select(rule_tree, kwargs, strategy: CascadeStrategy):
    """Walk rule_tree, collect (specificity, source_order, value) for matching
    keys, sort, and merge with new-wins semantics by default. Live-scope
    lazies in matched values are resolved against the dispatch kwargs."""
    input_value = (
        kwargs[strategy.input_params[0]]
        if len(strategy.input_params) == 1 else kwargs
    )
    matches: list = []
    items = rule_tree.items() if hasattr(rule_tree, 'items') else rule_tree
    for source_idx, (raw_key, value) in enumerate(items):
        parsed = strategy.parse(raw_key) if strategy.parse else None
        if parsed is None:
            continue
        if strategy.matches and not strategy.matches(parsed, input_value):
            continue
        spec = strategy.specificity(parsed) if strategy.specificity else (0,)
        matches.append((spec, source_idx, value))
    if not matches:
        return {}
    matches.sort(key=lambda t: (t[0], t[1]))
    merge_fn = strategy.merge or _default_merge
    result: Any = {}
    for _, _, v in matches:
        result = merge_fn(result, _resolve_live(v, kwargs))
    return _resolve_live(result, kwargs)


def _resolve_live(value, kwargs):
    """Recursively resolve LazyInterpolable nodes carrying a live scope using kwargs."""
    from dracon.lazy import LazyInterpolable
    if isinstance(value, LazyInterpolable) and value._scope_params:
        return value.invoke(**{k: kwargs[k] for k in value._scope_params if k in kwargs})
    if dict_like(value):
        return type(value)({k: _resolve_live(v, kwargs) for k, v in value.items()}) \
            if hasattr(value, 'items') else value
    if isinstance(value, list):
        return [_resolve_live(v, kwargs) for v in value]
    return value


def _default_merge(a, b):
    if dict_like(a) and dict_like(b):
        return merged(a, b, cached_merge_key('<<{+<}[~<]'))
    return b


class _MatchStrategy:
    """Select-mode dispatcher: a `CallableSymbol` of kind 'match'."""

    def interface(self, sym):
        from dracon.symbols import InterfaceSpec, ParamSpec, SymbolKind
        strategy = sym._cascade_strategy
        return InterfaceSpec(
            kind=SymbolKind.DISPATCH, name=sym._name,
            params=tuple(ParamSpec(name=p, required=True) for p in strategy.input_params),
            source=sym._source,
        )

    def invoke(self, sym, kwargs, *, invocation_context=None):
        strategy = sym._cascade_strategy
        missing = [p for p in strategy.input_params if p not in kwargs]
        if missing:
            raise ValueError(
                f"!cascade:{strategy.name} invocation missing required "
                f"parameters: {missing}"
            )
        return _cascade_select(sym._rule_tree, kwargs, strategy)

    def dump(self, sym, representer):
        strategy = sym._cascade_strategy
        return representer.represent_mapping(
            f'!cascade:{strategy.name}', sym._rule_tree,
        )

    def represented_type(self, sym):
        return None

    def reduce(self, sym):
        return (_reconstruct_match, (sym._cascade_strategy.name, sym._rule_tree, sym._name))

    def deepcopy(self, sym, memo):
        from dracon.symbols import CallableSymbol
        clone = CallableSymbol.__new__(CallableSymbol)
        memo[id(sym)] = clone
        clone._kind = 'match'
        clone._name = sym._name
        clone._source = sym._source
        clone._cached_interface = sym._cached_interface
        clone._callable = None
        clone._func_path = None
        clone._kwargs = None
        clone._template_node = None
        clone._loader = sym._loader
        clone._file_context = None
        clone._call_depth = 0
        clone._has_return = False
        clone._cached_params = None
        clone._stages = None
        clone._stage_kwargs = None
        clone._cascade_strategy = sym._cascade_strategy
        clone._rule_tree = deepcopy(sym._rule_tree)
        return clone


def _reconstruct_match(strategy_name: str, rule_tree, name: Optional[str]):
    from dracon.symbols import CallableSymbol
    strategy = get_cascade_strategy(strategy_name)
    return CallableSymbol.from_match(rule_tree, strategy, name=name)


def _register_match_strategy():
    from dracon.symbols import register_callable_strategy
    register_callable_strategy('match', _MatchStrategy())


_register_match_strategy()
