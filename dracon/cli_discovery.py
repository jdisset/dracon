# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Jean Disset

"""CLI discovery pre-pass.

Composes user-supplied `+`-layered configs far enough to walk the
top-level instruction tree and return their `CliDirective` records.

Pure function: no construction, no pydantic validation. Unsatisfied
`!require`s do not raise here -- they are re-validated later, once the
real CLI run has finished collecting argv values.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Mapping, Optional

from dracon.cli_declaration import CliDirective, parse_directive_body
from dracon.cli_param import CliParam
from dracon.composer import CompositionResult
from dracon.diagnostics import CompositionError, DraconError
from dracon.interpolation_utils import transform_dollar_vars
from dracon.loader import DraconLoader, compose_config_from_str
from dracon.loaders.load_utils import FILE_CONTEXT_KEYS
from dracon.symbols import MISSING, InterfaceSpec, ParamSpec, SymbolKind

logger = logging.getLogger(__name__)

_BARE_VAR_REF = re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}')

# kinds whose params surface as cli flags; VALUE/DEFERRED carry runtime bindings, not flags
_CLI_FLAG_KINDS = frozenset({
    SymbolKind.TYPE, SymbolKind.CALLABLE,
    SymbolKind.TEMPLATE, SymbolKind.PIPE,
})


def collect_cli_params(comp_res: CompositionResult, loader: DraconLoader) -> list[CliParam]:
    """SSOT walker: YAML directives + flag-bearing symbols in the loader's table.

    Symbols whose `interface().kind` is in `_CLI_FLAG_KINDS` contribute one
    `CliParam` per param. YAML-side directives win on name collision (they
    are appended last and `_dedupe_last_wins` keeps the final occurrence).
    """
    out = _symbol_table_params(loader)
    out.extend(comp_res.cli_directives)
    return _dedupe_last_wins(out)


def _param_to_cli(p: ParamSpec, iface: InterfaceSpec) -> CliParam:
    return CliParam(
        real_name=p.name,
        source="yaml",
        target="context",
        kind="require" if p.required else "set_default",
        help=p.docs,
        short=p.cli_short,
        hidden=p.cli_hidden,
        default=p.default if p.default is not MISSING else MISSING,
        arg_type=p.annotation if p.annotation is not MISSING else None,
        source_context=iface.source,
    )


def discover_cli_directives(
    conf_sources: list[str],
    seed_context: Optional[Mapping[str, Any]] = None,
    *,
    loader_factory: Callable[..., DraconLoader] = DraconLoader,
    soft: bool = False,
) -> list[CliParam]:
    """Compose layered configs only far enough to collect declarations.

    Args:
        conf_sources: source strings as they appear after the leading `+`
            on the command line (e.g. ``"file:./extras.yaml"``,
            ``"pkg:my_pkg:configs/extras.yaml"``, or a raw YAML string).
        seed_context: names already known to the loader (the CLI's
            initial context plus any ``++name=value`` already harvested
            from argv). Treated as immutable: the caller's mapping is
            not mutated.
        loader_factory: factory used to build the throwaway
            ``DraconLoader``. Defaults to ``DraconLoader``. Callers can
            inject ``context_types``, ``custom_loaders``, etc.
        soft: when True, swallow per-source composition errors and
            return whatever directives were collected from the layers
            that did compose. Used by ``--help`` so missing or broken
            layers do not abort the help screen.

    Returns:
        Deduplicated list of ``CliDirective``. When two layers declare
        the same ``name``, the later layer wins (last-writer semantics,
        matching how ``defined_vars`` merge today).
    """
    if not conf_sources:
        return []

    seed = dict(seed_context or {})
    loader = loader_factory(
        context=seed,
        enable_interpolation=True,
        base_dict_type=dict,
        base_list_type=list,
    )
    # discovery is deliberately fail-soft on unsatisfied !require: argv
    # has not been parsed yet, so a missing name is not (yet) an error.
    loader._skip_require_check = True

    aggregate: list[CliParam] = []
    for source in conf_sources:
        try:
            comp = loader.compose(source)
            aggregate.extend(_collect_directives(comp, loader))
        except (CompositionError, DraconError, FileNotFoundError, OSError) as e:
            # full composition can fail when downstream interpolations or
            # includes need argv-supplied context. In that case fall back to
            # a static YAML-level scan so the top-level !require / !set_default
            # directives still surface in --help.
            static = _static_scan(source, loader)
            if static:
                logger.debug(
                    "discovery: full compose failed for %r (%s); using static scan with %d directives",
                    source, e, len(static),
                )
                aggregate.extend(static)
            elif soft:
                logger.debug("discovery: skipping %r (%s)", source, e)
                continue
            else:
                raise

    # symbol-table params go at the front so yaml directives win the dedup
    return _dedupe_last_wins(_symbol_table_params(loader) + aggregate)


def _static_scan(
    source: str,
    loader: DraconLoader,
    _seen: Optional[set] = None,
) -> list[CliParam]:
    """Fallback used when full composition fails (typically because an
    interpolation or include needs argv-supplied context that isn't yet
    set).

    Walks the parsed YAML structurally without composing or resolving
    interpolations, harvesting `!require` / `!set_default` declarations
    wherever it goes. Descends into mapping/sequence values, treats
    `!deferred`-tagged subtrees as transparent, follows `!include`
    references whose paths resolve from the source's own file context
    (`$DIR`, `${FILE_STEM}`, ...), and skips `!fn` template bodies
    (those declarations live in a separate scope).

    Re-uses the existing instruction matchers and `parse_directive_body`
    so there's exactly one place that knows how to recognise a directive
    -- the instruction registry."""
    if _seen is None:
        _seen = set()
    if source in _seen:
        return []
    _seen.add(source)

    read = _read_source_text(source, loader)
    if read is None:
        return []
    content, file_ctx = read
    try:
        comp = compose_config_from_str(loader.yaml, content)
    except Exception as e:
        logger.debug("static scan: yaml compose failed for %r (%s)", source, e)
        return []
    root = getattr(comp, 'root', None)
    if root is None:
        return []

    out: list[CliParam] = []
    _scan_node(root, loader, file_ctx, _seen, out)
    return out


def _scan_node(
    node,
    loader: DraconLoader,
    file_ctx: Mapping[str, Any],
    seen: set,
    out: list[CliParam],
) -> None:
    """Recursively walk a parsed YAML node tree, harvesting directives
    from mapping keys and following includes. Pure structural -- no
    composition, no interpolation evaluation. `file_ctx` is the source's
    file-metadata dict, used to statically resolve `$DIR` /
    `${FILE_STEM}` shorthands in include paths."""
    from dracon.instructions import Require, SetDefault
    from dracon.include import IncludeNode

    if isinstance(node, IncludeNode):
        path = getattr(node, 'value', None)
        if isinstance(path, str):
            resolved = _expand_file_context(path, file_ctx)
            if '$' not in resolved:
                out.extend(_static_scan(resolved, loader, seen))
        return

    val = getattr(node, 'value', None)
    if not isinstance(val, list):
        return

    if val and isinstance(val[0], tuple):
        for key_node, value_node in val:
            key_tag = getattr(key_node, 'tag', None) or ''
            # !fn template bodies fire in a separate scope at invocation
            # time; their inner declarations are NOT outer-scope flags.
            if key_tag.startswith('!fn'):
                continue

            var_name = getattr(key_node, 'value', None)
            harvested = False
            if isinstance(var_name, str) and var_name.isidentifier():
                require = Require.match(key_tag)
                set_default = SetDefault.match(key_tag) if require is None else None
                if require is not None:
                    kind, python_type = "require", None
                elif set_default is not None:
                    kind, python_type = "set_default", set_default.target_type
                else:
                    kind = None
                if kind:
                    try:
                        directive, _ = parse_directive_body(
                            var_name, value_node, kind, python_type, key_node=key_node,
                        )
                        out.append(directive)
                        harvested = True
                    except Exception as e:
                        logger.debug("static scan: skipping %s %r (%s)", kind, var_name, e)

            # don't recurse into a directive's own value body (it's the
            # default/help mapping, not nested structure to scan).
            if not harvested:
                _scan_node(value_node, loader, file_ctx, seen, out)
    else:
        for item in val:
            _scan_node(item, loader, file_ctx, seen, out)


def _expand_file_context(path: str, file_ctx: Mapping[str, Any]) -> str:
    """Mirror the compose-time pipeline (`transform_dollar_vars` then
    `${NAME}` resolution) but only against the source's own file
    context. Names not in `file_ctx` keep their `${...}` -- the
    caller's `$`-check then rejects truly-dynamic paths the static
    fallback can't resolve without argv."""
    if '$' not in path or not file_ctx:
        return path
    return _BARE_VAR_REF.sub(
        lambda m: str(file_ctx[m.group(1)]) if m.group(1) in file_ctx else m.group(0),
        transform_dollar_vars(path),
    )


def _read_source_text(
    source: str, loader: DraconLoader
) -> Optional[tuple[str, dict]]:
    """Resolve a source string to (raw YAML text, file-context dict) via
    the loader's scheme registry. Reuses the same scheme normalisation
    as `loader.compose`, so bare paths get the `file:` scheme treatment."""
    from dracon.include import ensure_scheme

    scheme, _, rest = ensure_scheme(source).partition(':')
    fn = (loader.custom_loaders or {}).get(scheme)
    if fn is None:
        return None
    try:
        result, ctx = fn(rest, node=None, draconloader=loader)
    except Exception as e:
        logger.debug("static scan: %r loader failed for %r (%s)", scheme, source, e)
        return None
    if not isinstance(result, str):
        return None
    return result, (ctx if isinstance(ctx, dict) else {})


def _collect_directives(
    comp: CompositionResult,
    loader: DraconLoader,
    _seen: Optional[set] = None,
) -> list[CliParam]:
    """Collect directives at this composition's surface, then walk each
    `DeferredNode`'s inner Node tree structurally and harvest declarations.

    Uses the same `_scan_node` walker as the static fallback -- no compose
    per deferred, no interpolation evaluation. Cost is O(tree size), not
    O(tree size * compose passes), which matters when `!each` generates
    many deferred clones (each with a `<<: !include` to the same fragment).
    `_seen` carries source strings, so the included fragment is only
    actually parsed once even with N clones.
    """
    out = list(comp.cli_directives)
    if _seen is None:
        _seen = set()

    if comp.node_map:
        from dracon.deferred import DeferredNode
        from dracon.nodes import Node
        for node in comp.node_map.values():
            if not isinstance(node, DeferredNode):
                continue
            key = id(node)
            if key in _seen:
                continue
            _seen.add(key)
            inner = getattr(node, 'value', None)
            if isinstance(inner, Node):
                ctx = getattr(node, 'context', None) or {}
                file_ctx = {k: ctx[k] for k in FILE_CONTEXT_KEYS if k in ctx}
                _scan_node(inner, loader, file_ctx, _seen, out)

    return out


def _symbol_table_params(loader: DraconLoader) -> list[CliParam]:
    """Walk loader's symbol table; yield CliParams for flag-bearing kinds.

    Excludes built-in / dracon-internal symbols (`listdir`, `Path`, `__scope__`,
    file-context keys, ...) so only user-registered callables, models, and
    templates contribute flags.
    """
    from dracon.symbol_table import _is_user_symbol
    out: list[CliParam] = []
    table = getattr(loader, 'symbols', None) or getattr(loader, 'context', None)
    if table is None or not hasattr(table, 'interface'):
        return out
    for name in list(table):
        if not _is_user_symbol(name):
            continue
        try:
            iface = table.interface(name)
        except Exception:
            continue
        if iface is None or iface.kind not in _CLI_FLAG_KINDS:
            continue
        for p in iface.params:
            if p.cli_hidden:
                continue
            out.append(_param_to_cli(p, iface))
    return out


def _dedupe_last_wins(params: list[CliParam]) -> list[CliParam]:
    """Stable dedup by name, last occurrence wins.

    Preserves the source order of first appearance for stable iteration
    so help output mirrors the order the user wrote the layers in.
    """
    by_name: dict[str, CliParam] = {}
    order: list[str] = []
    for p in params:
        if p.real_name not in by_name:
            order.append(p.real_name)
        by_name[p.real_name] = p
    return [by_name[n] for n in order]
