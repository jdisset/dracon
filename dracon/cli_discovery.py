# Copyright (c) 2025 Jean Disset
# MIT License - see LICENSE file for details.

"""CLI discovery pre-pass.

Composes user-supplied `+`-layered configs far enough to walk the
top-level instruction tree and return their `CliDirective` records.

Pure function: no construction, no pydantic validation. Unsatisfied
`!require`s do not raise here -- they are re-validated later, once the
real CLI run has finished collecting argv values.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Mapping, Optional

from dracon.cli_declaration import CliDirective, parse_directive_body
from dracon.composer import CompositionResult
from dracon.diagnostics import CompositionError, DraconError
from dracon.loader import DraconLoader, compose_config_from_str

logger = logging.getLogger(__name__)


def discover_cli_directives(
    conf_sources: list[str],
    seed_context: Optional[Mapping[str, Any]] = None,
    *,
    loader_factory: Callable[..., DraconLoader] = DraconLoader,
    soft: bool = False,
) -> list[CliDirective]:
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

    aggregate: list[CliDirective] = []
    for source in conf_sources:
        try:
            comp = loader.compose(source)
            aggregate.extend(_collect_directives(comp))
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

    return _dedupe_last_wins(aggregate)


def _static_scan(source: str, loader: DraconLoader) -> list[CliDirective]:
    """Fallback used when full composition fails (typically because an
    interpolation or include needs argv-supplied context that isn't yet
    set). Re-uses the existing instruction matchers and the shared
    `parse_directive_body` parser, so there's exactly one place that
    knows how to recognise a directive — the instruction registry."""
    from dracon.instructions import Require, SetDefault

    content = _read_source_text(source, loader)
    if content is None:
        return []
    try:
        comp = compose_config_from_str(loader.yaml, content)
    except Exception as e:
        logger.debug("static scan: yaml compose failed for %r (%s)", source, e)
        return []
    root = getattr(comp, 'root', None)
    if root is None or not hasattr(root, 'value'):
        return []

    out: list[CliDirective] = []
    for key_node, value_node in root.value:
        tag = getattr(key_node, 'tag', None) or ''
        var_name = getattr(key_node, 'value', None)
        if not isinstance(var_name, str) or not var_name.isidentifier():
            continue
        # the instruction matchers ARE the SSOT for tag classification.
        require = Require.match(tag)
        set_default = SetDefault.match(tag) if require is None else None
        if require is not None:
            kind, python_type = "require", None
        elif set_default is not None:
            kind, python_type = "set_default", set_default.target_type
        else:
            continue
        try:
            directive, _ = parse_directive_body(
                var_name, value_node, kind, python_type, key_node=key_node,
            )
        except Exception as e:
            logger.debug("static scan: skipping %s %r (%s)", kind, var_name, e)
            continue
        out.append(directive)
    return out


def _read_source_text(source: str, loader: DraconLoader) -> Optional[str]:
    """Resolve a source string to raw YAML text via the loader's scheme
    registry. Reuses the same scheme normalisation as `loader.compose`,
    so bare paths get the `file:` scheme treatment."""
    from dracon.include import ensure_scheme

    scheme, _, rest = ensure_scheme(source).partition(':')
    fn = (loader.custom_loaders or {}).get(scheme)
    if fn is None:
        return None
    try:
        result, _ = fn(rest, node=None, draconloader=loader)
    except Exception as e:
        logger.debug("static scan: %r loader failed for %r (%s)", scheme, source, e)
        return None
    return result if isinstance(result, str) else None


def _collect_directives(comp: CompositionResult) -> list[CliDirective]:
    return list(comp.cli_directives)


def _dedupe_last_wins(directives: list[CliDirective]) -> list[CliDirective]:
    """Stable dedup by name, last occurrence wins.

    Preserves the source order of first appearance for stable iteration
    so help output mirrors the order the user wrote the layers in.
    """
    by_name: dict[str, CliDirective] = {}
    order: list[str] = []
    for d in directives:
        if d.name not in by_name:
            order.append(d.name)
        by_name[d.name] = d
    return [by_name[n] for n in order]
