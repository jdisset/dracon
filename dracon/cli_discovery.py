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

from dracon.cli_declaration import CliDirective
from dracon.composer import CompositionResult
from dracon.diagnostics import CompositionError, DraconError
from dracon.loader import DraconLoader

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
        except (CompositionError, DraconError, FileNotFoundError, OSError) as e:
            if soft:
                logger.debug("discovery: skipping %r (%s)", source, e)
                continue
            raise
        aggregate.extend(_collect_directives(comp))

    return _dedupe_last_wins(aggregate)


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
